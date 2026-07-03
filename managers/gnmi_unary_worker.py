import time
import hashlib
from pygnmi.client import gNMIclient
from util.encoding import str_to_bytes

class BaseUnaryWorker:
    """
    Base class for single request-response gNMI workers
    """
    def __init__(self, target_ip, target_port, username="",
                 password="", prefix="", encoding="json_ietf", **kwargs):
        self.target_ip = target_ip
        self.target_port = target_port
        self.username = username
        self.password = password
        self.prefix = prefix
        self.encoding = encoding

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
        print(f"[Worker {self.target_ip}] Requesting Capabilities...")
        with gNMIclient(target=self.target_tuple, username=self.username,
                        password=self.password, insecure=True) as gc:
            result = gc.capabilities()
            return self._format_result("Capabilities", result)

class GetWorker(BaseUnaryWorker):
    def __init__(self, target_ip, target_port, paths, **kwargs):
        super().__init__(target_ip, target_port, **kwargs)
        self.paths = paths
    
    def start(self):
        print(f"[Worker {self.target_ip}] Requesting Get...")
        with gNMIclient(target=self.target_tuple, username=self.username,
                        password=self.password, insecure=True, encoding=self.encoding) as gc:
            result = gc.get(prefix=self.prefix, path=self.paths, encoding=self.encoding)
            return self._format_result("Get", result)

class SetWorker(BaseUnaryWorker):
    def __init__(self, target_ip, target_port, updates=None, replaces=None, deletes=None, **kwargs):
        """
        In SetRequest, it handles three case of requests
        * update -> [('path', 'leaf', 'value'), ...]
        * delete -> [('path', 'leaf'), ...]
        * replace -> [('path', 'leaf', 'value'), ...]
        """
        super().__init__(target_ip, target_port, **kwargs)
        self.updates = updates
        self.replaces = replaces
        self.deletes = deletes
    
    def start(self):
        print(f"[Worker {self.target_ip}] Requesting Set...")
        with gNMIclient(target=self.target_tuple, username=self.username,
                        password=self.password, insecure=True, encoding=self.encoding) as gc:
            result = gc.set(prefix=self.prefix, update=self.updates, replace=self.replaces, delete=self.deletes)
            return self._format_result("Set", result)