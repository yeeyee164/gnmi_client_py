"""
validate.py defines a validation class that probably raises an exception
if failed to pass.
"""
import ipaddress
import modules.path as mp
from ui.cmd import ParsedConfig

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