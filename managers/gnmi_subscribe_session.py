import time
import json
import traceback
import hashlib
import grpc
import traceback
import queue

from specs.client import GNMIClient, gnmi_pb2
from util.encoding import str_to_bytes, STR_TO_GNMI_ENCODING

#define some global variables
NANOSECOND = 1000000000

class GNMISubscribeSession:
    """
    Handles a single gNMI connection to a single target.
    It doesn't know or care about other threads - need to handle critical sections.
    """

    def __init__(self, target_ip, target_port, paths, mode, data_queue, subscription_name,
                 username="", password="", prefix="", encoding="json_ietf",
                 insecure=False, **kwargs):
        self.target_ip = target_ip
        self.target_port = target_port
        self.username = username
        self.password = password
        self.prefix = prefix
        self.paths = paths
        self.mode = mode
        self.encoding = encoding
        self.insecure = insecure
        self.subscription_name = subscription_name

        # queue from manager
        self.data_queue = data_queue

        # build necessary payloads
        self.args = kwargs
        self.tgt_info = self._build_router_info()

        # set session id
        raw_id_str = f"{target_ip}:{target_port}:{subscription_name}:{time.time()}"
        self.session_id = hashlib.md5(str_to_bytes(raw_id_str)).hexdigest()[:10]
        
        # State control flag for clean thread shutdown
        self.is_running = False 
        # Thread-safe queue for manual POLL triggers
        self.poll_queue = queue.Queue()

    def _build_subscribe_request(self) -> gnmi_pb2.SubscribeRequest:
        """ Constructs the SubscribeRequest object """
        sub_list = gnmi_pb2.SubscriptionList()

        # determine mode
        if self.mode.lower() == 'once':
            sub_list.mode = gnmi_pb2.SubscriptionList.ONCE
        elif self.mode.lower() == 'poll':
            sub_list.mode = gnmi_pb2.SubscriptionList.POLL
        else:
            sub_list.mode = gnmi_pb2.SubscriptionList.STREAM

        # determine encoding        
        sub_list.encoding = STR_TO_GNMI_ENCODING[self.encoding.lower()]

        sub_list.updates_only = self.args.get('updates_only', False)

        # build individual subscriptions
        for path_obj in self.paths:
            sub = sub_list.subscription.add()
            sub.path.CopyFrom(path_obj)

            if self.mode.lower() == 'stream':
                smode = self.args.get('sub_mode', 'sample').lower()
                if smode == 'sample':
                    sub.mode = gnmi_pb2.SubscriptionMode.SAMPLE
                    sub.sample_interval = self.args.get('sample_interval', 0) * NANOSECOND
                elif smode == 'on_change':
                    sub.mode = gnmi_pb2.SubscriptionMode.ON_CHANGE
                else:
                    sub.mode = gnmi_pb2.SubscriptionMode.TARGET_DEFINED

        request = gnmi_pb2.SubscribeRequest(subscribe=sub_list)
        return request

    def _build_router_info(self):
        """
        Create router information for Subscribe RPC.
        It contains target address and account information.
        """
        router = {
            'target': (self.target_ip, self.target_port)
        }

        if self.username != "" and self.password != "":
            router['username'] = self.username
            router['password'] = self.password
        
        return router
            
    def start(self):
        self.is_running = True
        print(f"[Worker {self.session_id} | {self.target_ip}]"
              f" Starting '{self.subscription_name}' ({self.mode.upper()}) session...")

        target = self.tgt_info['target']

        def request_generator():
            yield self._build_subscribe_request()

            # keep generator alive
            while self.is_running:
                try:
                    # Wait for a trigger from the poll_queue
                    trigger = self.poll_queue.get(timeout=0.5)
                    if trigger == "POLL":
                        # create a new Poll message
                        poll_req = gnmi_pb2.SubscribeRequest(poll=gnmi_pb2.Poll())
                        yield poll_req
                except queue.Empty:
                    continue
        
        try:
            with GNMIClient(target=target, username=self.username, password=self.password, insecure=self.insecure) as client:
                response_stream = client.subscribe(request_generator())
                
                for raw_response in response_stream:
                    # Break the loop if the Manager tells this thread to stop
                    if not self.is_running:
                        response_stream.cancel()
                        break
                        
                    self.data_queue.put({
                        'session_id': self.session_id,
                        'target': ":".join([self.target_ip, str(self.target_port)]),
                        'subscription_name' : self.subscription_name,
                        'rpc' : 'subscribe',
                        'data': raw_response
                    })
                    
        except grpc.RpcError as e:
            print(f"[Worker {self.session_id} | {self.target_ip}] gRPC Error  '{e.code()}': {e.details()}")
        except Exception as e:
            traceback.print_exception(e)
            print(f"[Worker {self.session_id} | {self.target_ip}] Error in '{self.subscription_name}': {e}")
        finally:
            print(f"[Worker {self.session_id} | {self.target_ip}] Disconnected from '{self.subscription_name}'.")
    
    def stop(self):
        self.is_running = False

    def trigger_poll(self):
        """By calling this method, you can inject empty Poll message only if you have requested Poll."""
        if self.mode.lower() == 'poll':
            self.poll_queue.put("POLL")
        else:
            print(f"[Worker {self.session_id} | {self.target_ip}] Ignored POLL trigger. Session is in '{self.mode}' mode.")
