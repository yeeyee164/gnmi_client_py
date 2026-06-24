import time
import json
import traceback
import hashlib

from pygnmi.client import gNMIclient, telemetryParser
from util.encoding import str_to_bytes


NANOSECOND = 1000000000

class GNMISession:
    """
    Handles a single gNMI connection to a single target.
    It doesn't know or care about other threads - need to handle critical sections.
    """

    def __init__(self, target_ip, target_port, paths, mode, data_queue, subscription_name,
                 username="", password="", prefix="", encoding="json_ietf", **kwargs):
        self.target_ip = target_ip
        self.target_port = target_port
        self.username = username
        self.password = password
        self.prefix = prefix
        self.paths = paths
        self.mode = mode
        self.encoding = encoding
        self.subscription_name = subscription_name

        # queue from manager
        self.data_queue = data_queue

        # build necessary payloads
        self.args = kwargs
        self.tgt_info = self._build_router_info()
        self.payload = self._build_payload(kwargs)

        # set session id
        raw_id_str = f"{target_ip}:{target_port}:{subscription_name}:{time.time()}"
        self.session_id = hashlib.md5(str_to_bytes(raw_id_str)).hexdigest()[:10]
        
        # State control flag for clean thread shutdown
        self.is_running = False 

    def _build_payload(self, args):
        """
            TODO: make a request builder
        """

        # subscribe mode
        mode = self.mode
        subscribe_req = {
            'subscription':[
                {
                    "path": p
                } for p in self.paths
            ],
            'mode' : f'{mode}',
            'encoding': f'{self.encoding.lower()}',
        }

        # additional arguments
        if self.prefix != '':
            subscribe_req['prefix'] = self.prefix
        
        subscribe_req['update_only'] = self.args.get('update_only', False)

        # handle stream modes
        if mode.lower() == 'stream':
            si = self.args.get('sample_interval', 0) * NANOSECOND
            stream_mode_var = {
                'stream_mode': args.get('sub_mode', 'target_defined'),
                'sample_interval': si,
            }

            if 'stream_mode' in stream_mode_var:
                smode = stream_mode_var['stream_mode']
                sreq = subscribe_req['subscription']
                for subscription in sreq:
                    subscription['mode'] = smode

                if smode.lower() == 'sample':
                    for subscription in sreq:
                        subscription['sample_interval'] = stream_mode_var['sample_interval']

        return subscribe_req

    def _build_router_info(self):
        router = {
            'target': (self.target_ip, self.target_port)
        }

        if self.username != "" and self.password != "":
            router['username'] = self.username
            router['password'] = self.password
        
        return router
            
    def start(self):
        self.is_running = True
        payload = self.payload
        print(f"[Worker {self.session_id} | {self.target_ip}]"
              f" Starting '{self.subscription_name}' ({self.mode.upper()}) session...")

        target = self.tgt_info['target']
        
        try:
            with gNMIclient(target=target, username=self.username, password=self.password, insecure=True) as gc:
                response_iterator = gc.subscribe(subscribe=payload)
                
                for raw_response in response_iterator:
                    # Break the loop if the Manager tells this thread to stop
                    if not self.is_running:
                        break
                        
                    parsed_data = telemetryParser(raw_response)
                    # Test: printing received data
                    # print(json.dumps(parsed_data, indent=2))

                    # Note: In a real app, you might want to push this data to a Thread Queue 
                    # or write it to a database instead of just printing it.
                    # print(f"[{self.target_ip}] Data received!") 

                    self.data_queue.put({
                        'session_id': self.session_id,
                        'target': ":".join([self.target_ip, str(self.target_port)]),
                        'subscription_name' : self.subscription_name,
                        'data': parsed_data
                    })
                    
        except Exception as e:
            traceback.print_exception(e)
            print(f"[Worker {self.session_id} | {self.target_ip}] Error in '{self.subscription_name}': {e}")
        finally:
            print(f"[Worker {self.session_id} | {self.target_ip}] Disconnected from '{self.subscription_name}'.")
    
    def stop(self):
        self.is_running = False