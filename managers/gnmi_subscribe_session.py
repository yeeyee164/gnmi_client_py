import time
import json
import hashlib
import grpc
import queue
import traceback

from managers.client_factory import ClientFactory
from util.encoding import str_to_bytes

class GNMISession:
    """
    Handles a single gNMI Subscribe service to a single target.
    It doesn't know or care about other threads - need to handle critical sections.
    """

    def __init__(self, target_ip, target_port, paths, mode, data_queue, subscription_name,
                 username="", password="", prefix="", encoding="json_ietf",
                 protocol="gnmi", **kwargs):
        self.target_ip = target_ip
        self.target_port = target_port
        self.username = username
        self.password = password
        self.prefix = prefix
        self.paths = paths
        self.mode = mode
        self.encoding = encoding
        self.protocol = protocol.lower()
        self.subscription_name = subscription_name

        # secure/insecure connection settings
        self.insecure = kwargs.get('insecure', False)

        # some global options such as debug flag
        self.debug = kwargs.get('debug', False)

        # queue from manager
        self.data_queue = data_queue

        # build necessary payloads
        self.args = kwargs
        self.target = f'{self.target_ip}:{self.target_port}'

        # set session id
        raw_id_str = f"{target_ip}:{target_port}:{subscription_name}:{time.time()}"
        self.session_id = hashlib.md5(str_to_bytes(raw_id_str)).hexdigest()[:10]
        
        # State control flag for clean thread shutdown
        self.is_running = False 
        # Thread-safe queue for manual POLL triggers
        self.poll_queue = queue.Queue()

            
    def start(self):
        self.is_running = True
        print(f"[Worker {self.session_id} | {self.target_ip}]"
              f" Starting '{self.subscription_name}' ({self.mode.upper()}) session...")

        def request_generator():
            """yields standard Python dictionaries to the Client"""

            try:
                yield {
                    'action': 'subscribe',
                    'paths': self.paths,
                    'mode': self.mode,
                    'encoding': self.encoding,
                    'prefix': self.prefix,
                    'update_only': self.args.get('update_only', False),
                    'sub_mode': self.args.get('sub_mode', 'sample'),
                    'sample_interval': self.args.get('sample_interval', 0)
                }

                # keep generator alive
                while self.is_running:
                    try:
                        # Wait for a trigger from the poll_queue
                        trigger = self.poll_queue.get(timeout=0.5)
                        if trigger == "POLL":
                            yield {'action': 'poll'}
                    except queue.Empty:
                        continue
            except Exception as e:
                print(f"\n[Worker {self.session_id}] Generator error: {e}")
        
        try:
            with ClientFactory.get_client(
                protocol=self.protocol, target=self.target,
                username=self.username, password=self.password,
                insecure=self.insecure, debug=self.debug) as client:
                response_stream = client.subscribe(request_generator())
                
                for raw_response in response_stream:
                    # Break the loop if the Manager tells this thread to stop
                    if not self.is_running:
                        response_stream.cancel()
                        break
                        
                    self.data_queue.put({
                        'session_id': self.session_id,
                        'target': self.target,
                        'subscription_name' : self.subscription_name,
                        'rpc' : 'subscribe',
                        'data': raw_response
                    })
                    
        except grpc.RpcError as e:
            print(f"[Worker {self.session_id} | {self.target_ip}] gRPC Error '{e.code()}': {e.details()}")
        except Exception as e:
            traceback.print_stack()
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
