# -*- encoding: utf-8 -*-
"""
schema_validator.py

Operation-aware validation engine checking XPath schema validity, writability
(config true vs config false), mandatory list keys, and payload constraints.
"""
from __future__ import annotations
import logging
from typing import Optional, Union, Any

from config.selectors import PathSelector
from config.operations import (
    OperationConfig,
    GetOperation,
    GetConfigOperation,
    SetOperation,
    EditConfigOperation,
)
from core.schema_context import SchemaContext
from core.schema_errors import (
    SchemaValidationError,
    InvalidSchemaPathError,
)

logger = logging.getLogger(__name__)


class SchemaValidator:
    """
    Validates operational paths and payloads against compiled libyang SchemaContext.
    """

    @staticmethod
    def _extract_path_str(path: Union[str, PathSelector]) -> str:
        if isinstance(path, str):
            return path
        if hasattr(path, "paths") and path.paths:
            return path.paths[0]
        if hasattr(path, "path") and path.path:
            return path.path
        return str(path)

    def validate_path(
        self,
        path: Union[str, PathSelector],
        schema_context: SchemaContext,
        operation: Optional[OperationConfig] = None,
    ) -> Any:
        """
        Verifies that an XPath points to a valid schema node within the compiled context,
        and enforces operation constraints (e.g. read-only config false rejection for Set).
        Returns the matched SchemaNode.
        """
        path_str = self._extract_path_str(path)
        if not path_str or path_str == "/":
            return None

        # Clean gNMI-style leading origin prefixes if present, e.g. "openconfig:/..."
        cleaned_path = path_str
        if not cleaned_path.startswith("/"):
            cleaned_path = "/" + cleaned_path

        # Strip list keys from path for find_path lookup (libyang find_path requires schema node path or path expression)
        # e.g., /ietf-interfaces:interfaces/interface[name='eth0']/description -> /ietf-interfaces:interfaces/interface/description
        import re
        schema_lookup_path = re.sub(r'\[[^\]]+\]', '', cleaned_path)

        try:
            nodes = list(schema_context.find_path(schema_lookup_path))
            if not nodes:
                raise InvalidSchemaPathError(
                    f"Path '{path_str}' does not resolve to any schema node in the compiled context."
                )
            schema_node = nodes[0]
        except Exception as e:
            if isinstance(e, InvalidSchemaPathError):
                raise
            raise InvalidSchemaPathError(
                f"Path '{path_str}' is invalid in the compiled schema context: {e}"
            ) from e

        # Operation-aware checks
        is_set_operation = isinstance(operation, (SetOperation, EditConfigOperation)) or (
            operation is not None and getattr(operation, "__class__", None).__name__ in ("SetOperation", "EditConfigOperation")
        )

        if is_set_operation:
            # Check read-only state
            if hasattr(schema_node, "config_false") and schema_node.config_false():
                raise SchemaValidationError(
                    f"Path '{path_str}' targets a read-only node ('config false') "
                    f"which cannot be mutated by a Set/EditConfig operation."
                )

        return schema_node

    def validate_payload(
        self,
        path: Union[str, PathSelector],
        value: Any,
        schema_context: SchemaContext,
        operation: Optional[OperationConfig] = None,
    ) -> None:
        """
        Verifies that a value conforms to the schema constraints for the given path.
        """
        path_str = self._extract_path_str(path)
        if not path_str or value is None:
            return

        # First ensure path is schema-valid
        self.validate_path(path_str, schema_context, operation=operation)

        # Ensure leading slash for data path
        data_path = path_str if path_str.startswith("/") else "/" + path_str

        # Test building data path in libyang
        try:
            if isinstance(value, (dict, list)):
                from core.schema_data import DataBuilder
                DataBuilder.populate_tree(schema_context, data_path, value)
            else:
                val_str = str(value).lower() if isinstance(value, bool) else (str(value) if value is not None else None)
                if val_str is not None:
                    schema_context.create_data_path(data_path, value=val_str)
        except Exception as e:
            if isinstance(e, SchemaValidationError):
                raise
            raise SchemaValidationError(
                f"Payload validation failed at path '{path_str}' for value '{value}': {e}"
            ) from e

