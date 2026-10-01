from dataclasses import dataclass
from abc import ABC
from typing import Any, Tuple

class Selector(ABC):
    """Base selector for target data identification."""
    def validate(self) -> None:
        """Validate selector consistency."""
        pass

@dataclass(frozen=True, kw_only=True)
class PathSelector(Selector):
    """Path-based targeting (native to gNMI and RESTCONF; translatable to XPath)."""
    paths: tuple[str, ...] = ()
    prefix: str = ""

    def __init__(self, paths: Any = (), prefix: str = "", **kwargs):
        p = kwargs.get('paths', paths)
        pr = kwargs.get('prefix', prefix)
        if isinstance(p, str):
            object.__setattr__(self, 'paths', (p,))
        elif isinstance(p, (list, tuple, set)):
            object.__setattr__(self, 'paths', tuple(p))
        else:
            object.__setattr__(self, 'paths', tuple(p))
        object.__setattr__(self, 'prefix', pr)

@dataclass(frozen=True, kw_only=True)
class FilterSelector(Selector):
    """Expression-based filtering (XPath or XML Subtree for NETCONF)."""
    expression: str
    filter_type: str = "xpath"  # xpath, subtree

# Backward compatibility / spec alias
SelectorConfig = Selector
