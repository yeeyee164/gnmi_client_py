from dataclasses import dataclass
from typing import Optional

from config.protocol_options.base import BaseProtocolOptions


@dataclass(frozen=True, kw_only=True)
class NetconfOptions(BaseProtocolOptions):
    """NETCONF-specific protocol options."""
    target_datastore: str = "candidate"
    source: str = "running"
    source_datastore: Optional[str] = None
    config: Optional[str] = None
    default_operation: str = "merge"
    test_option: Optional[str] = None
    error_option: str = "stop-on-error"
    commit: bool = True
    device: str = "default"
    lock_target: bool = False

    def __post_init__(self):
        if self.source_datastore is not None and self.source == "running":
            object.__setattr__(self, 'source', self.source_datastore)
        elif self.source_datastore is None:
            object.__setattr__(self, 'source_datastore', self.source)

    def validate(self) -> None:
        """Validate NETCONF options consistency and valid parameters."""
        valid_datastores = {"running", "candidate", "startup", "intended", "operational"}
        if self.target_datastore and self.target_datastore.lower() not in valid_datastores:
            raise ValueError(
                f"Invalid target_datastore '{self.target_datastore}'. Must be one of {sorted(valid_datastores)}."
            )

        effective_source = self.source_datastore or self.source
        if effective_source and effective_source.lower() not in valid_datastores:
            raise ValueError(
                f"Invalid source_datastore '{effective_source}'. Must be one of {sorted(valid_datastores)}."
            )

        valid_default_operations = {"merge", "replace", "none"}
        if self.default_operation and self.default_operation.lower() not in valid_default_operations:
            raise ValueError(
                f"Invalid default_operation '{self.default_operation}'. Must be one of {sorted(valid_default_operations)}."
            )

        valid_error_options = {"stop-on-error", "continue-on-error", "rollback-on-error"}
        if self.error_option and self.error_option.lower() not in valid_error_options:
            raise ValueError(
                f"Invalid error_option '{self.error_option}'. Must be one of {sorted(valid_error_options)}."
            )

        if self.test_option is not None:
            valid_test_options = {"test-then-set", "set", "test-only"}
            if self.test_option.lower() not in valid_test_options:
                raise ValueError(
                    f"Invalid test_option '{self.test_option}'. Must be one of {sorted(valid_test_options)}."
                )
