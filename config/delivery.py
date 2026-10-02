from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union


class DeliveryMode(str, Enum):
    # Core Protocol-Neutral Members (RFC 8641 / YANG-Push)
    PERIODIC = "periodic"                  # Time-interval sampling (RFC 8641 / gNMI SAMPLE)
    EVENT_DRIVEN = "event_driven"          # State mutations & notifications (RFC 8641 / RFC 5277 / gNMI ON_CHANGE)
    SNAPSHOT = "snapshot"                  # One-time state capture (gNMI ONCE / NETCONF unary get)
    ON_DEMAND = "on_demand"                # Explicit client/user-triggered polling (gNMI POLL)
    SERVER_DETERMINED = "server_determined" # Server/Target selects optimal mode based on schema

    @classmethod
    def _missing_(cls, value: object) -> Optional["DeliveryMode"]:
        """Support case-insensitivity and hyphen/underscore interchangeability."""
        if isinstance(value, str):
            norm = value.strip().lower().replace("-", "_")
            for member in cls:
                if member.value == norm:
                    return member
        return None


@dataclass(frozen=True, kw_only=True)
class DeliveryPolicy:
    mode: DeliveryMode = DeliveryMode.PERIODIC
    interval: int = 0         # Sample interval in seconds
    heartbeat: int = 0        # Heartbeat interval in seconds
    suppress_redundant: bool = False # Skip duplicated outputs

    def __post_init__(self) -> None:
        if isinstance(self.mode, str) and not isinstance(self.mode, DeliveryMode):
            object.__setattr__(self, "mode", DeliveryMode(self.mode))

    @classmethod
    def from_raw(cls, mode: Union[str, DeliveryMode], **kwargs) -> "DeliveryPolicy":
        """Factory method accepting string or DeliveryMode."""
        if isinstance(mode, str):
            resolved_mode = DeliveryMode(mode)
        else:
            resolved_mode = mode
        return cls(mode=resolved_mode, **kwargs)

    def validate(self) -> None:
        """Validate delivery policy values."""
        if self.interval < 0:
            raise ValueError(f"interval must be >= 0, got {self.interval}")
        if self.heartbeat < 0:
            raise ValueError(f"heartbeat must be >= 0, got {self.heartbeat}")

