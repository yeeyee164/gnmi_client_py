from dataclasses import dataclass

@dataclass(frozen=True, kw_only=True)
class GNMIOptions:
    """gNMI-specific protocol options."""
    encoding: str = "json_ietf"
    updates_only: bool = False

