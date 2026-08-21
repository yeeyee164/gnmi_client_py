import time
import json
import hashlib
import grpc
import queue
import traceback
import logging

from managers.factory import ClientFactory, ValidatorFactory
from util.utils import str_to_bytes

logger = logging.getLogger(__name__)

class SubscribeSession:
    """
    Handles a single Subscribe service to a single target.
    It doesn't know or care about other threads - need to handle critical sections.

    NOTE: It may contain protocol-specific features.
    """

    def __init__(self, target_ip, target_port, data_queue,
                 protocol="gnmi", username="", password="",
                 security=None, subscription_name="default_sub", **kwargs):
        self.target_ip = target_ip
        self.target_port = target_port
        self.username = username
        self.password = password
        self.protocol = protocol.lower()
        self.subscription_name = subscription_name
        self.security = security
        self.kwargs = kwargs

        # validator - TODO
        # self.validator = ValidatorFactory.get_validator(self.protocol)

        # secure/insecure connection settings
        #self.insecure = kwargs.get('insecure', False)

        # some global options such as debug flag
        self.debug = kwargs.get('debug', False)

        # queue from manager
        self.data_queue = data_queue

        # build necessary payloads
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
        logger.debug(f"[Worker {self.session_id} | {self.target_ip}]"
              f" Starting '{self.subscription_name}' ({self.kwargs.get('mode', '').upper()}) session...")

        def request_generator():
            """yields standard Python dictionaries to the Client"""

            try:
                yield {
                    'action': self.kwargs.get('operation', 'unknown'),
                    **self.kwargs
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
            except GeneratorExit:
                pass
            except Exception as e:
                logger.error(f"\n[Worker {self.session_id}] Generator error: {e}")
        
        try:
            #validate inputs before instantiating client
            # TODO: it will be handled by protocol-agnostic validator
            # for path in self.paths:
            #     self.validator.validate_path(path)
            
            with ClientFactory.get_client(
                protocol=self.protocol, target=self.target,
                username=self.username, password=self.password,
                security=self.security, **self.kwargs) as client:
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
                        'rpc' : self.kwargs.get('operation', 'unknown'),
                        'data': raw_response
                    })
                    
        except grpc.RpcError as e:
            logger.error(f"[Worker {self.session_id} | {self.target_ip}] gRPC Error '{e.code()}': {e.details()}")
        except Exception as e:
            traceback.print_stack()
            logger.error(f"[Worker {self.session_id} | {self.target_ip}] Error in '{self.subscription_name}': {e}")
        finally:
            logger.info(f"[Worker {self.session_id} | {self.target_ip}] Disconnected from '{self.subscription_name}'.")
    
    def stop(self):
        self.is_running = False

    def trigger_poll(self):
        """By calling this method, you can inject empty Poll message only if you have requested Poll."""
        if self.kwargs.get('mode','').lower() == 'poll':
            self.poll_queue.put("POLL")
        else:
            logger.warning(f"[Worker {self.session_id} | {self.target_ip}] Ignored polling trigger. Session is in '{self.kwargs.get('mode', 'no')}' mode.")
