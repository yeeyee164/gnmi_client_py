from dataclasses import dataclass
from enum import Enum

class DeliveryMode(str, Enum):
    PERIODIC = "periodic"     # gNMI SAMPLE
    ON_CHANGE = "on_change"   # gNMI ON_CHANGE
    SNAPSHOT = "snapshot"     # gNMI ONCE
    POLL = "poll"             # gNMI POLL
    TARGET_DEFINED = "target_defined" # gNMI TARGET_DEFINED

@dataclass(frozen=True, kw_only=True)
class DeliveryPolicy:
    mode: DeliveryMode = DeliveryMode.PERIODIC
    interval: int = 0         # Sample interval in seconds
    heartbeat: int = 0        # Heartbeat interval in seconds
    suppress_redundant: bool = False # Skip duplicated outputs

    def validate(self) -> None:
        """Validate delivery policy values."""
        if self.interval < 0:
            raise ValueError(f"interval must be >= 0, got {self.interval}")
        if self.heartbeat < 0:
            raise ValueError(f"heartbeat must be >= 0, got {self.heartbeat}")

# Backward compatibility / spec alias
DeliveryConfig = DeliveryPolicy
