import time
import hashlib
import grpc

from util.encoding import str_to_bytes
from managers.factory import ClientFactory, ValidatorFactory

class BaseUnaryWorker:
    """
    Base class for single request-response workers
    """
    def __init__(self, target_ip, target_port, username="",
                 password="", prefix="", encoding="json_ietf", 
                 protocol='gnmi', **kwargs):
        self.target_ip = target_ip
        self.target_port = target_port
        self.username = username
        self.password = password
        self.prefix = prefix
        self.encoding = encoding
        self.protocol = protocol.lower()
        self.target = f'{self.target_ip}:{self.target_port}'

        raw_id_str = f"{target_ip}:{target_port}:{time.time()}"
        self.session_id = hashlib.md5(str_to_bytes(raw_id_str)).hexdigest()[:10]

        # kwargs
        self.inseucre = kwargs.get('insecure', False)
        self.security = kwargs.get('security', None)

        # validator
        self.validator = ValidatorFactory.get_validator(self.protocol)
    
    def _format_result(self, rpc_name, data):
        """Standardizes the output dictionary for the handlers"""

        return {
            'session_id': self.session_id,
            'target': self.target,
            'rpc': rpc_name,
            'data': data,
        }

    def _get_client(self):
        """Asks the factory for a client based on the requested protocol"""
        return ClientFactory.get_client(
            protocol=self.protocol, target=self.target, 
            username=self.username, password=self.password,
            insecure=self.inseucre, security=self.security
        )

class CapabilityWorker(BaseUnaryWorker):
    def start(self):
        print(f"[Worker(Capability) {self.target_ip}] Requesting Capability...")

        try:
            with self._get_client() as client:
                result = client.capability()
                return self._format_result("capability", result)
                
        except grpc.RpcError as e:
            print(f'[Worker(Capability) {self.target_ip}] gRPC error: {e.code()} - {e.details()}')
            return None

    def __str__(self):
        return "Capabilities"

class GetWorker(BaseUnaryWorker):
    def __init__(self, target_ip, target_port, paths, **kwargs):
        super().__init__(target_ip, target_port, **kwargs)
        self.paths = paths

    def start(self):
        print(f"[Worker(Get) {self.target_ip}] Requesting Get...")

        try:
            #1. validate inputs
            for path in self.paths:
                self.validator.validate_path(path)

            #2. create a client session
            with self._get_client() as client:
                result = client.get(paths=self.paths, encoding=self.encoding, prefix=self.prefix)
                return self._format_result("get", result)
                
        except grpc.RpcError as e:
            print(f'[Worker(Get) {self.target_ip}] gRPC error: {e.code()} - {e.details()}')
            return None

    def __str__(self):
        return "Get"

class SetWorker(BaseUnaryWorker):
    def __init__(self, target_ip, target_port, updates=None, replaces=None, deletes=None, **kwargs):
        """
        In SetRequest, it handles three case of requests
        * update -> [('path', 'value'), ...]
        * delete -> ['path', ...]
        * replace -> [('path', 'value'), ...]
        """
        super().__init__(target_ip, target_port, **kwargs)
        self.updates = updates or []
        self.replaces = replaces or []
        self.deletes = deletes or []

    def start(self):
        print(f"[Worker(Set) {self.target_ip}] Requesting Set...")
        try:
            #1. validate inputs
            for path in self.updates + self.replaces:
                self.validator.validate_path(path, 'set')

            #2. create a client session
            with self._get_client() as client:
                result = client.set(prefix=self.prefix,
                                    update=self.updates,
                                    replace=self.replaces,
                                    delete=self.deletes)
                return self._format_result("Set", result)
        except grpc.RpcError as e:
            print(f"[Worker(Set) {self.target_ip}] gRPC Error: {e.code()} - {e.details()}")
            return None

    def __str__(self):
        return "Set"