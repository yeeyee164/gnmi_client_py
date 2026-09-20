from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any
from modules.security import SecurityProfile
from config.operations import OperationConfig

class Protocol(str, Enum):
    GNMI = "gnmi"
    NETCONF = "netconf"
    RESTCONF = "restconf"

@dataclass(frozen=True, kw_only=True)
class ConnectionConfig:
    """Pure network transport and authentication parameters."""
    target: str
    username: str = ""
    password: str = ""
    security: SecurityProfile = field(default_factory=SecurityProfile)
    insecure: bool = False

    @property
    def target_ip(self) -> str:
        """Extract IP address or hostname from target, supporting IPv4, bracketed IPv6, and hostnames."""
        if not self.target:
            return ""
        if self.target.startswith('['):
            closing_bracket = self.target.find(']')
            if closing_bracket != -1:
                return self.target[1:closing_bracket]
        if ':' in self.target:
            parts = self.target.split(':')
            if len(parts) == 2 and parts[1].isdigit():
                return parts[0]
        return self.target.strip('[]')

    @property
    def target_port(self) -> int:
        """Extract port number from target, or return 0 if omitted."""
        if not self.target:
            return 0
        if self.target.startswith('['):
            closing_bracket = self.target.find(']')
            if closing_bracket != -1 and closing_bracket < len(self.target) - 1:
                remainder = self.target[closing_bracket + 1:]
                if remainder.startswith(':'):
                    try:
                        return int(remainder[1:])
                    except ValueError:
                        return 0
            return 0
        if ':' in self.target:
            parts = self.target.split(':')
            if len(parts) == 2 and parts[1].isdigit():
                return int(parts[1])
        return 0

@dataclass(frozen=True, kw_only=True)
class ExecutionConfig:
    """Execution policies common to all operations."""
    timeout: int = 30
    retry_count: int = 0
    times: int = 1

@dataclass(frozen=True, kw_only=True)
class SessionConfig:
    """Top-level session definition pairing connection, protocol, and intent."""
    connection: ConnectionConfig
    protocol: Protocol
    operation: OperationConfig
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)

    @property
    def target(self) -> str:
        return self.connection.target

    @property
    def target_ip(self) -> str:
        return self.connection.target_ip

    @property
    def target_port(self) -> int:
        return self.connection.target_port

    @property
    def username(self) -> str:
        return self.connection.username

    @property
    def password(self) -> str:
        return self.connection.password

    @property
    def security(self) -> SecurityProfile:
        return self.connection.security

    @property
    def insecure(self) -> bool:
        return self.connection.insecure

    @property
    def times(self) -> int:
        return self.execution.times

    @property
    def prefix(self) -> str:
        if hasattr(self.operation, 'prefix') and self.operation.prefix:
            return self.operation.prefix
        if hasattr(self.operation, 'selector') and hasattr(self.operation.selector, 'prefix'):
            return self.operation.selector.prefix
        return ""

    @property
    def paths(self) -> list[str]:
        if hasattr(self.operation, 'selector') and hasattr(self.operation.selector, 'paths'):
            return list(self.operation.selector.paths)
        return []

    @property
    def updates(self) -> list:
        from config.operations import SetOperation, ChangeType
        if isinstance(self.operation, SetOperation):
            return [(c.path, c.value) for c in self.operation.changes if c.operation == ChangeType.MERGE]
        return []

    @property
    def replaces(self) -> list:
        from config.operations import SetOperation, ChangeType
        if isinstance(self.operation, SetOperation):
            return [(c.path, c.value) for c in self.operation.changes if c.operation == ChangeType.REPLACE]
        return []

    @property
    def deletes(self) -> list:
        from config.operations import SetOperation, ChangeType
        if isinstance(self.operation, SetOperation):
            return [c.path for c in self.operation.changes if c.operation == ChangeType.DELETE]
        return []

    @property
    def target_datastore(self) -> str:
        if hasattr(self.operation, 'protocol_options') and hasattr(self.operation.protocol_options, 'target_datastore'):
            return self.operation.protocol_options.target_datastore
        return "candidate"

    @property
    def config(self) -> Optional[str]:
        if hasattr(self.operation, 'protocol_options') and hasattr(self.operation.protocol_options, 'config'):
            return self.operation.protocol_options.config
        return None

    @property
    def default_operation(self) -> str:
        if hasattr(self.operation, 'protocol_options') and hasattr(self.operation.protocol_options, 'default_operation'):
            return self.operation.protocol_options.default_operation
        return "merge"

    @property
    def error_option(self) -> str:
        if hasattr(self.operation, 'protocol_options') and hasattr(self.operation.protocol_options, 'error_option'):
            return self.operation.protocol_options.error_option
        return "stop-on-error"

    @property
    def sample_interval(self) -> int:
        if hasattr(self.operation, 'delivery') and hasattr(self.operation.delivery, 'interval'):
            return self.operation.delivery.interval
        return 0

    @property
    def subscription_name(self) -> str:
        if hasattr(self.operation, 'subscription_name'):
            return self.operation.subscription_name
        return "default"

