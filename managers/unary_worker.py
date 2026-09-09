import time
import hashlib
import logging
import dataclasses

from util.utils import str_to_bytes
from managers.factory import ClientFactory, ValidatorFactory

logger = logging.getLogger(__name__)

class BaseUnaryWorker:
    """
    Base class for single request-response workers
    """
    def __init__(self, target_ip=None, target_port=None, username="",
                 password="", protocol='gnmi',
                 security=None, config=None, **kwargs):
        self.config = config
        if config is not None:
            self.target_ip = config.target_ip
            self.target_port = config.target_port
            self.username = config.username
            self.password = config.password
            self.protocol = config.protocol.lower() if config.protocol else 'gnmi'
            self.security = config.security
            self.kwargs = dataclasses.asdict(config)
            for k in ['target', 'security', 'username', 'password', 'protocol']:
                self.kwargs.pop(k, None)
            self.kwargs.update(kwargs)
        else:
            self.target_ip = target_ip
            self.target_port = target_port
            self.username = username
            self.password = password
            self.protocol = protocol.lower() if protocol else 'gnmi'
            self.security = security
            self.kwargs = kwargs

        self.target = f'{self.target_ip}:{self.target_port}'

        raw_id_str = f"{self.target_ip}:{self.target_port}:{time.time()}"
        self.session_id = hashlib.md5(str_to_bytes(raw_id_str)).hexdigest()[:10]

        # validator - TODO
        # self.validator = ValidatorFactory.get_validator(self.protocol)
    
    def _format_result(self, default_rpc_name, data):
        """Standardizes the output dictionary for the handlers"""

        return {
            'session_id': self.session_id,
            'target': self.target,
            'rpc': self.kwargs.get('operation', default_rpc_name),
            'data': data,
        }

    def _get_client(self):
        """Asks the factory for a client based on the requested protocol"""
        client_kwargs = dict(self.kwargs)
        for k in ['target', 'security', 'username', 'password', 'protocol']:
            client_kwargs.pop(k, None)
        return ClientFactory.get_client(
            protocol=self.protocol, target=self.target, 
            username=self.username, password=self.password,
            security=self.security, **client_kwargs
        )

class CapabilityWorker(BaseUnaryWorker):
    def start(self):
        logger.debug(f"[Worker(Capability) {self.target_ip}] Requesting Capability...")

        try:
            with self._get_client() as client:
                result = client.capability(**self.kwargs)
                return self._format_result("capability", result)
                
        except Exception as e:
            logger.error(f'[Worker(Capability) {self.target_ip}] Error: {e}')
            return self._format_result("capability", e)

    def __str__(self):
        return "Capabilities"

class GetWorker(BaseUnaryWorker):
    def __init__(self, target_ip=None, target_port=None, config=None, **kwargs):
        super().__init__(target_ip=target_ip, target_port=target_port, config=config, **kwargs)
        if self.config and hasattr(self.config, 'paths'):
            self.paths = self.config.paths
        else:
            paths = kwargs.get('paths', [])
            self.paths = paths

    def start(self):
        logger.debug(f"[Worker(Get) {self.target_ip}] Requesting Get...")

        try:
            #1. validate inputs
            # TODO: it will be handled by protocol-agnostic validator
            # for path in self.paths:
            #     self.validator.validate_path(path)

            #2. create a client session
            with self._get_client() as client:
                result = client.get(**self.kwargs)
                return self._format_result("get", result)
                
        except Exception as e:
            logger.error(f'[Worker(Get) {self.target_ip}] Error: {e}')
            return self._format_result("get", e)

    def __str__(self):
        return "Get"

class SetWorker(BaseUnaryWorker):
    def __init__(self, target_ip=None, target_port=None, updates=None, replaces=None, deletes=None, config=None, **kwargs):
        """
        In SetRequest, it handles three case of requests
        * update -> [('path', 'value'), ...]
        * delete -> ['path', ...]
        * replace -> [('path', 'value'), ...]
        """
        super().__init__(target_ip=target_ip, target_port=target_port, config=config, **kwargs)
        if self.config:
            self.updates = getattr(self.config, 'updates', None) or updates or []
            self.replaces = getattr(self.config, 'replaces', None) or replaces or []
            self.deletes = getattr(self.config, 'deletes', None) or deletes or []
        else:
            self.updates = updates or []
            self.replaces = replaces or []
            self.deletes = deletes or []

    def start(self):
        logger.debug(f"[Worker(Set) {self.target_ip}] Requesting Set...")
        try:
            #1. validate inputs
            # TODO: it will be handled by protocol-agnostic validator
            # for path in self.updates + self.replaces:
            #     self.validator.validate_path(path, 'set')

            #2. create a client session
            with self._get_client() as client:
                result = client.set(**self.kwargs)
                return self._format_result("Set", result)
        except Exception as e:
            logger.error(f"[Worker(Set) {self.target_ip}] Error: {e}")
            return self._format_result("Set", e)

    def __str__(self):
        return "Set"