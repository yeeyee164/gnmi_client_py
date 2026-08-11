"""
validate.py defines a validation class that probably raises an exception
if failed to pass.
"""
from abc import ABC, abstractmethod

import ipaddress
import modules.path as mp
from ui.cmd import ParsedConfig

class PathValidationError(Exception):
    """Custom exception raised when a path is invalid for the requested protocol or RPC"""
    pass

class BaseValidator(ABC):

    @abstractmethod
    def validate_path(self, path_str:str, operation:str):
        """
        Validate if a path is legal for the given protocol and operation.
        Must raise PathValidationError if the rules are violated.

        Args:
            `path_str`: a path string will be tested
            `operation`: denotes specific protocols or operations related with `path_str`
        """
        pass

class GNMIValidator(BaseValidator):

    def validate_path(self, path_str:str, operation=""):
        """Validate a path for gNMI requests"""

        try:
            # 1. make str to Path -> it also does path validation
            gnmi_path = mp.parse_path(path_str)
            elems = gnmi_path.elem

            # 2. when the operation is 'Set', it cannot contain wildcards
            if operation.lower() == 'set':
                for elem in elems:
                    if elem.name in ['*', '...']:
                        raise mp.MalformedXPathError("set operation cannot use wildcards")

                    for key_val in elem.key.values():
                        if key_val in ['*', '...']:
                            raise mp.MalformedXPathKeyError("set operation cannot use wildcards as a key")
        except Exception as e:
            raise PathValidationError(e)

class ValidateConfig:
    @staticmethod
    def validate(cfg: ParsedConfig):
        """
        method validate validates given config  
        """

        try:
            # validate 'targets'
            for tgt in cfg.targets:
                # "IP:PORT" -> IP, ":", PORT
                ip, separator, port = tgt.rpartition(':')

                if not separator:
                    raise ValueError("wrong address format")
                
                # Strip brackets if it's an IPv6 address literal
                ip = ip.strip('[]')

                ipaddress.ip_address(ip)

                port = int(port)
                if not (1 <= port <= 2**16-1):
                    raise ValueError("port should have a value between 1 to 65535")

            # validate for each subscription
            for se in cfg.sessions:
                # validate given path
                for path in se.paths:
                    data = mp.parse_path(path)
                    if data is None:
                        raise mp.EmptyPathElemNameError
        except Exception as e: #propagate exception
            raise e