from __future__ import annotations

from specs.base_client import BaseClient, UnsupportedOperationError
from specs.gnmi_client import GNMIClient, NANOSECOND
from specs.netconf_client import NetconfClient, NETCONF_BASE_NS, NETCONF_NS

__all__ = [
    "BaseClient",
    "UnsupportedOperationError",
    "GNMIClient",
    "NetconfClient",
    "NANOSECOND",
    "NETCONF_BASE_NS",
    "NETCONF_NS",
]
