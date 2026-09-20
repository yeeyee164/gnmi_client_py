from dataclasses import dataclass
from enum import Enum

class DeliveryMode(str, Enum):
    PERIODIC = "periodic"     # gNMI SAMPLE
    ON_CHANGE = "on_change"   # gNMI ON_CHANGE
    SNAPSHOT = "snapshot"     # gNMI ONCE
    POLL = "poll"             # gNMI POLL

@dataclass(frozen=True, kw_only=True)
class DeliveryPolicy:
    mode: DeliveryMode = DeliveryMode.PERIODIC
    interval: int = 0         # Sample interval in seconds
    heartbeat: int = 0        # Heartbeat interval in seconds
    suppress_redundant: bool = False

