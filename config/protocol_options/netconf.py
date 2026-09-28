from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True, kw_only=True)
class NetconfOptions:
    """NETCONF-specific protocol options."""
    target_datastore: str = "candidate"
    source: str = "running"
    config: Optional[str] = None
    default_operation: str = "merge"
    test_option: Optional[str] = None
    error_option: str = "stop-on-error"
    commit: bool = True
    device: str = "default"

