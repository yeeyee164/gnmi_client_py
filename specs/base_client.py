from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Iterator, Any, Optional

from config.operations import (
    CapabilitiesOperation,
    GetOperation,
    SetOperation,
    SubscribeOperation,
    GetSchemaOperation,
)

class BaseClient(ABC):
    """
    Abstract Base Class for all Northbound Protocol Clients such as NETCONF, gNMI, RESTCONF...
    Establishes a unified interface so managers and workers can operate protocol-agnostically.
    """

    def __enter__(self):
        """Initializes connection of session context manager."""
        return self

    @abstractmethod
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Safely tears down connection or session context manager"""
        pass

    # =========================================================================
    # Semantic Intent Operations
    # =========================================================================

    def execute_capabilities(self, operation: CapabilitiesOperation) -> Any:
        """Executes capabilities discovery based on CapabilitiesOperation."""
        return NotImplementedError("execute_capabilities must be implemented by concrete client")

    def execute_get(self, operation: GetOperation) -> Any:
        """Executes a get/read operation based on GetOperation."""
        raise NotImplementedError("execute_get must be implemented by concrete client")

    def execute_set(self, operation: SetOperation) -> Any:
        """Executes a set/edit operation based on SetOperation."""
        raise NotImplementedError("execute_set must be implemented by concrete client")

    def execute_subscribe(self, operation: SubscribeOperation) -> Iterator[Any]:
        """Executes a streaming telemetry / notification operation based on SubscribeOperation."""
        raise NotImplementedError("execute_subscribe must be implemented by concrete client")

    def execute_schema(self, operation: GetSchemaOperation) -> Any:
        """Executes schema retrieval based on GetSchemaOperation."""
        raise NotImplementedError("execute_schema must be implemented by concrete client")
