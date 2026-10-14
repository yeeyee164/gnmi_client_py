# -*- encoding: utf-8 -*-
"""
netconf_validator.py

Validator for NETCONF paths, XPath filter expressions, XML subtree filters,
and compiled YANG schema nodes.
"""
from __future__ import annotations
import xml.etree.ElementTree as ET
from typing import Optional, Union, Any

from modules.validate import BaseValidator, PathValidationError
from core.schema_context import SchemaContext
from core.schema_manager import SchemaManager
from core.schema_validator import SchemaValidator
from core.schema_errors import SchemaValidationError, InvalidSchemaPathError
from config.operations import OperationConfig


class NetconfValidator(BaseValidator):
    """
    Validates NETCONF paths, subtree XML filters, and compiled schema nodes.
    """

    def validate_path(
        self,
        path_str: str,
        operation: str = "",
        filter_type: str = "xpath",
        schema_context: Optional[SchemaContext] = None,
        profile_id: Optional[str] = None,
        op_config: Optional[OperationConfig] = None,
    ) -> None:
        """
        Validates a NETCONF path or filter expression.
        Performs syntactic checks on XML subtrees / XPaths, and validates
        against compiled YANG schema if schema_context or profile_id is provided.
        """
        if not path_str or not path_str.strip():
            raise PathValidationError("Empty path or filter expression.")

        path_clean = path_str.strip()

        try:
            # 1. Subtree filter validation
            if filter_type == "subtree" or path_clean.startswith("<"):
                try:
                    ET.fromstring(path_clean)
                except Exception as e:
                    raise PathValidationError(f"Invalid XML subtree filter: {e}") from e

            # 2. Basic XPath syntax checks
            else:
                if "///" in path_clean:
                    raise PathValidationError(f"Invalid XPath syntax: {path_str}")

            # 3. Compiled YANG schema validation
            if schema_context is not None:
                SchemaValidator().validate_path(path_clean, schema_context, operation=op_config)
            elif profile_id is not None:
                SchemaManager().validate_path(path_clean, profile_id, operation=op_config)

        except (SchemaValidationError, InvalidSchemaPathError) as e:
            raise PathValidationError(str(e)) from e
        except PathValidationError:
            raise
        except Exception as e:
            raise PathValidationError(f"Validation failed for '{path_str}': {e}") from e

