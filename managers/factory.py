# -*- encoding: utf-8 -*-
"""
factory.py

It supports common interface for each northbound protocols.

Currently supported common interfaces:
* client picker: `ClientFactory`
* simple validator: `ValidatorFactory`
"""
from specs.client import GNMIClient, NetconfClient
from modules.validate import GNMIValidator

class ClientFactory:
    """
    Instantiates and returns the appropriate client driver based on the requested protocol.
    """
    @staticmethod
    def get_client(protocol: str, target: str, username: str = "", password: str = "", **kwargs):
        """
        By calling `get_client` class method, you can instantiate and create a client session
        with `protocol`.

        Args:
            `protocol`: Client for Northbound Protocol. Currently only gNMI is supported.
            `target`: a string formatted of "IP addr:PORT"
        """
        protocol = protocol.lower()
        
        if protocol == "gnmi":
            return GNMIClient(target, username, password, **kwargs)
        elif protocol == "netconf":
            return NetconfClient(target, username, password, **kwargs)
        elif protocol == "restconf":
            raise NotImplementedError("RESTCONF client support is coming soon!")
        else:
            raise ValueError(f"Unsupported protocol: '{protocol}'. Available: [gnmi]")

class ValidatorFactory:
    """
    Instantiates and returns the appropriate offline validator based on the
    requested protocol.
    """
    @staticmethod
    def get_validator(protocol: str):
        protocol = protocol.lower()

        if protocol == 'gnmi':
            return GNMIValidator()
        elif protocol == 'netconf':
            raise NotImplementedError("NETCONF validator support is comming soon")
        elif protocol == 'restconf':
            raise NotImplementedError("RESTCONF validator support is comming soon")
        else:
            raise ValueError(f"Not supported protocol: {protocol}")