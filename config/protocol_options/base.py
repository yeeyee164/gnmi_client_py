from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseProtocolOptions(ABC):
    """Abstract base class for all protocol-specific configuration options."""

    @abstractmethod
    def validate(self) -> None:
        """Validate options consistency.

        Raises:
            ValueError: If options violate protocol constraints or ranges.
        """
        pass

    def to_dict(self) -> Dict[str, Any]:
        """Convert options to a serializable dictionary."""
        return {
            k: v for k, v in self.__dict__.items() if not k.startswith("_")
        }
