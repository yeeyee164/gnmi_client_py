from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from config.selectors import Selector, PathSelector
from config.delivery import DeliveryPolicy

class OperationConfig:
    """Base marker for all semantic operational intents."""
    pass

@dataclass(frozen=True, kw_only=True)
class CapabilitiesOperation(OperationConfig):
    """Discovery of supported models, encodings, and extensions."""
    pass

@dataclass(frozen=True, kw_only=True)
class GetSchemaOperation(OperationConfig):
    """Retrieval of schema definitions (RFC 6022 / YANG files)."""
    identifier: str
    version: Optional[str] = None
    format: str = "yang"

@dataclass(frozen=True, kw_only=True)
class GetOperation(OperationConfig):
    """Retrieval of operational or configuration state."""
    selector: Selector
    read_scope: str = "all"  # all, config, state, operational
    protocol_options: Any = None

class ChangeType(str, Enum):
    MERGE = "merge"
    REPLACE = "replace"
    DELETE = "delete"

@dataclass(frozen=True, kw_only=True)
class Change:
    """Atomic mutation intent."""
    path: str
    operation: ChangeType = ChangeType.MERGE
    value: Any = None

    def __eq__(self, path_val:tuple):
        return (self.path, self.operation, self.value) == path_val

@dataclass(frozen=True, kw_only=True)
class SetOperation(OperationConfig):
    """Mutation of configuration datastores."""
    changes: tuple[Change, ...] = ()
    prefix: str = ""
    protocol_options: Any = None

    def __init__(self, changes: Any = (), prefix: str = "", protocol_options: Any = None, **kwargs):
        c = kwargs.get('changes', changes)
        pr = kwargs.get('prefix', prefix)
        po = kwargs.get('protocol_options', protocol_options)
        if isinstance(c, tuple):
            object.__setattr__(self, 'changes', c)
        elif isinstance(c, (list, set)):
            object.__setattr__(self, 'changes', tuple(c))
        else:
            object.__setattr__(self, 'changes', tuple(c))
        object.__setattr__(self, 'prefix', pr)
        object.__setattr__(self, 'protocol_options', po)

@dataclass(frozen=True, kw_only=True)
class SubscribeOperation(OperationConfig):
    """Continuous or snapshot data subscription."""
    selector: Selector
    delivery: DeliveryPolicy
    subscription_name: str = "default"
    protocol_options: Any = None
