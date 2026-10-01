from dataclasses import dataclass
from enum import Enum
from typing import Optional

from config.protocol_options.base import BaseProtocolOptions


class GnmiEncoding(str, Enum):
    JSON = "json"
    JSON_IETF = "json_ietf"
    BYTES = "bytes"
    PROTO = "proto"
    ASCII = "ascii"


class GnmiSubscriptionMode(str, Enum):
    SAMPLE = "sample"
    ON_CHANGE = "on_change"
    TARGET_DEFINED = "target_defined"


@dataclass(frozen=True, kw_only=True)
class GnmiOptions(BaseProtocolOptions):
    """gNMI-specific protocol options."""
    encoding: str = "json_ietf"
    updates_only: bool = False
    sub_mode: Optional[str] = None
    sample_interval_ns: int = 0
    heartbeat_interval_ns: int = 0
    suppress_redundant: bool = False

    def validate(self) -> None:
        """Validate gNMI options ranges and consistency."""
        valid_encodings = {"json", "json_ietf", "bytes", "proto", "ascii"}
        enc_str = self.encoding.value if hasattr(self.encoding, "value") else str(self.encoding).lower()
        if enc_str not in valid_encodings:
            raise ValueError(
                f"Invalid gNMI encoding '{self.encoding}'. Must be one of {sorted(valid_encodings)}."
            )

        if self.sub_mode is not None:
            valid_sub_modes = {"sample", "on_change", "target_defined"}
            sub_str = self.sub_mode.value if hasattr(self.sub_mode, "value") else str(self.sub_mode).lower()
            if sub_str not in valid_sub_modes:
                raise ValueError(
                    f"Invalid gNMI subscription mode '{self.sub_mode}'. Must be one of {sorted(valid_sub_modes)}."
                )

        if self.sample_interval_ns < 0:
            raise ValueError(f"sample_interval_ns must be >= 0, got {self.sample_interval_ns}")

        if self.heartbeat_interval_ns < 0:
            raise ValueError(f"heartbeat_interval_ns must be >= 0, got {self.heartbeat_interval_ns}")


# Backward compatibility alias
GNMIOptions = GnmiOptions
