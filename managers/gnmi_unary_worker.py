import time
import hashlib
import grpc

from specs.client import GNMIClient
from util.encoding import str_to_bytes

class BaseUnaryWorker:
    """
    Base class for single request-response gNMI workers
    """
    def __init__(self, target_ip, target_port, username="",
                 password="", prefix="", encoding="json_ietf", 
                 insecure=False, **kwargs):
        self.target_ip = target_ip
        self.target_port = target_port
        self.username = username
        self.password = password
        self.prefix = prefix
        self.encoding = encoding
        self.insecure = insecure

        self.target_tuple = (self.target_ip, self.target_port)

        raw_id_str = f"{target_ip}:{target_port}:{time.time()}"
        self.session_id = hashlib.md5(str_to_bytes(raw_id_str)).hexdigest()[:10]
    
    def _format_result(self, rpc_name, data):
        """Standardizes the output dictionary for the handlers"""

        return {
            'session_id': self.session_id,
            'target': f"{self.target_ip}:{self.target_port}",
            'rpc': rpc_name,
            'data': data,
        }

class CapabilitiesWorker(BaseUnaryWorker):
    def start(self):
        print(f"[Worker(Capabilities) {self.target_ip}] Requesting Capabilities...")

        try:
            with GNMIClient(target=self.target_tuple, username=self.username,
                            password=self.password, insecure=self.insecure) as client:
                result = client.capabilities()
                return self._format_result("capabilities", result)
                
        except grpc.RpcError as e:
            print(f'[Worker(Capabilities) {self.target_ip}] gRPC error: {e.code()} - {e.details()}')
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
            with GNMIClient(target=self.target_tuple, username=self.username,
                            password=self.password, insecure=self.insecure) as client:
                result = client.get(paths=self.paths, encoding=self.encoding)
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
            with GNMIClient(target=self.target_tuple, username=self.username,
                            password=self.password, insecure=self.insecure) as client:
                result = client.set(prefix=self.prefix,
                                    update=self.updates,
                                    replace=self.replaces,
                                    delete=self.deletes,
                                    encoding=self.encoding)
                return self._format_result("Set", result)
        except grpc.RpcError as e:
            print(f"[Worker(Set) {self.target_ip}] gRPC Error: {e.code()} - {e.details()}")
            return None

    def __str__(self):
        return "Set"