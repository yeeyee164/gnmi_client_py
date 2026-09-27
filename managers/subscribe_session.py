import time
import json
import hashlib
import queue
import traceback
import logging
import dataclasses
from typing import Optional, Any

from managers.factory import ClientFactory, ValidatorFactory
from util.utils import str_to_bytes
from config.model import SessionConfig
from config.operations import SubscribeOperation
from config.selectors import PathSelector
from config.delivery import DeliveryMode
from config.protocol_options.gnmi import GNMIOptions

logger = logging.getLogger(__name__)

class SubscribeSession:
    """
    Handles a single Subscribe service to a single target.
    It doesn't know or care about other threads - need to handle critical sections.
    """

    def __init__(self, target_ip=None, target_port=None, data_queue=None,
                 protocol="gnmi", username="", password="",
                 security=None, subscription_name="default_sub",
                 config=None, **kwargs):
        self.data_queue = data_queue
        self.config = config
        self.session = config

        if config is not None:
            if isinstance(config, SessionConfig) or hasattr(config, 'connection'):
                self.target_ip = config.target_ip
                self.target_port = config.target_port
                self.username = config.username
                self.password = config.password
                proto_val = config.protocol
                self.protocol = proto_val.value if hasattr(proto_val, 'value') else str(proto_val).lower()
                self.security = config.security
                self.insecure = config.insecure
                self.operation = config.operation
                self.subscription_name = getattr(config.operation, 'subscription_name', 'default_sub')
                self.kwargs = dict(kwargs)
            else:
                self.target_ip = config.target_ip
                self.target_port = config.target_port
                self.username = config.username
                self.password = config.password
                self.protocol = config.protocol.lower() if config.protocol else "gnmi"
                self.security = config.security
                self.insecure = getattr(config, 'insecure', False)
                self.operation = getattr(config, 'operation', 'subscribe')
                self.subscription_name = getattr(config, 'subscription_name', subscription_name)
                self.kwargs = dataclasses.asdict(config)
                for k in ['target', 'security', 'username', 'password', 'protocol']:
                    self.kwargs.pop(k, None)
                self.kwargs.update(kwargs)

        self.debug = self.kwargs.get('debug', False)
        self.target = f'{self.target_ip}:{self.target_port}'

        raw_id_str = f"{self.target_ip}:{self.target_port}:{self.subscription_name}:{time.time()}"
        self.session_id = hashlib.md5(str_to_bytes(raw_id_str)).hexdigest()[:10]
        
        self.is_running = False 
        self.poll_queue = queue.Queue()

    def is_poll_mode(self) -> bool:
        if isinstance(self.operation, SubscribeOperation):
            return self.operation.delivery.mode == DeliveryMode.POLL
        return self.kwargs.get('mode', '').lower() == 'poll'

    def start(self):
        self.is_running = True
        mode_str = self.operation.delivery.mode.value if isinstance(self.operation, SubscribeOperation) else self.kwargs.get('mode', '').upper()
        logger.debug(f"[Worker {self.session_id} | {self.target_ip}]"
              f" Starting '{self.subscription_name}' ({mode_str}) session...")

        def request_generator():
            try:
                if isinstance(self.operation, SubscribeOperation):
                    paths = []
                    prefix = ""
                    if isinstance(self.operation.selector, PathSelector):
                        paths = list(self.operation.selector.paths)
                        prefix = self.operation.selector.prefix

                    mode_map = {
                        DeliveryMode.PERIODIC: 'stream',
                        DeliveryMode.ON_CHANGE: 'stream',
                        DeliveryMode.SNAPSHOT: 'once',
                        DeliveryMode.POLL: 'poll',
                    }
                    stream_mode_map = {
                        DeliveryMode.PERIODIC: 'sample',
                        DeliveryMode.ON_CHANGE: 'on_change',
                        DeliveryMode.SNAPSHOT: 'sample',
                        DeliveryMode.POLL: 'sample',
                    }
                    d_mode = self.operation.delivery.mode
                    req_mode = mode_map.get(d_mode, 'stream')
                    stream_mode = stream_mode_map.get(d_mode, 'sample')

                    enc = "json_ietf"
                    updates_only = False
                    if isinstance(self.operation.protocol_options, GNMIOptions):
                        enc = self.operation.protocol_options.encoding
                        updates_only = self.operation.protocol_options.updates_only

                    yield {
                        'action': 'subscribe',
                        'operation': 'subscribe',
                        'mode': req_mode,
                        'stream_mode': stream_mode,
                        'sub_mode': stream_mode,
                        'paths': paths,
                        'prefix': prefix,
                        'sample_interval': self.operation.delivery.interval,
                        'heartbeat_interval': self.operation.delivery.heartbeat,
                        'suppress_redundant': self.operation.delivery.suppress_redundant,
                        'encoding': enc,
                        'updates_only': updates_only,
                        'protocol': self.protocol,
                    }
                else:
                    yield {
                        'action': self.kwargs.get('operation', 'unknown'),
                        **self.kwargs
                    }

                while self.is_running:
                    try:
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
            client_kwargs = dict(self.kwargs) if hasattr(self, 'kwargs') and self.kwargs else {}
            for k in ['target', 'security', 'username', 'password', 'protocol']:
                client_kwargs.pop(k, None)
            if hasattr(self, 'insecure'):
                client_kwargs.setdefault('insecure', self.insecure)

            with ClientFactory.get_client(
                protocol=self.protocol, target=self.target,
                username=self.username, password=self.password,
                security=self.security, **client_kwargs) as client:
                response_stream = client.subscribe(request_generator())
                
                for raw_response in response_stream:
                    if not self.is_running:
                        cancel_func = getattr(response_stream, 'cancel', None)
                        if callable(cancel_func):
                            cancel_func()
                        break
                        
                    self.data_queue.put({
                        'session_id': self.session_id,
                        'target': self.target,
                        'subscription_name': self.subscription_name,
                        'rpc': 'subscribe' if isinstance(self.operation, SubscribeOperation) else self.kwargs.get('operation', 'unknown'),
                        'data': raw_response,
                        'protocol': self.protocol,
                    })
                    
        except Exception as e:
            #traceback.print_stack()
            #logger.error(f"[Worker {self.session_id} | {self.target_ip}] Error in '{self.subscription_name}': {e}")
            # NOTE: It always invoked during the termination of POLL
            pass
        finally:
            logger.info(f"[Worker {self.session_id} | {self.target_ip}] Disconnected from '{self.subscription_name}'.")
    
    def stop(self):
        self.is_running = False

    def trigger_poll(self):
        """By calling this method, you can inject empty Poll message only if you have requested Poll."""
        if self.is_poll_mode():
            self.poll_queue.put("POLL")
        else:
            mode_desc = self.operation.delivery.mode.value if isinstance(self.operation, SubscribeOperation) else self.kwargs.get('mode', 'no')
            logger.warning(f"[Worker {self.session_id} | {self.target_ip}] Ignored polling trigger. Session is in '{mode_desc}' mode.")
