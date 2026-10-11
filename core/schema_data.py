# -*- encoding: utf-8 -*-
"""
schema_data.py

Constructs compiled libyang DataNode trees from abstract operational Change objects
or Python dictionaries without protocol-specific metadata.
"""
from __future__ import annotations
import json
import logging
from typing import Sequence, Union, Any, Optional

from config.operations import Change, ChangeType
from core.schema_context import SchemaContext
from core.schema_errors import SchemaSerializationError

logger = logging.getLogger(__name__)


class DataBuilder:
    """
    Transforms Change mutation intents or structured Python dictionaries into libyang DataNode trees.
    """

    @staticmethod
    def build_from_changes(schema_context: SchemaContext, changes: Sequence[Change]) -> Any:
        """
        Populates a libyang data tree from a sequence of `Change` objects.

        `Change` denotes current request of 'Set' operations.
        """
        root_node = None

        for ch in changes:
            path = ch.path if ch.path.startswith("/") else "/" + ch.path
            val = ch.value

            # If deleting or removing without value
            if ch.operation in (ChangeType.DELETE, ChangeType.REMOVE) and val is None:
                val = ""

            try:
                if isinstance(val, (dict, list)):
                    # For structured dictionaries, parse via JSON memory if possible
                    json_data = json.dumps(val)
                    node = schema_context.parse_data_mem(json_data, fmt="json")
                else:
                    val_str = str(val) if val is not None else None
                    node = schema_context.create_data_path(path, value=val_str)

                if root_node is None:
                    root_node = node
                else:
                    root_node.merge(node)
            except Exception as e:
                raise SchemaSerializationError(
                    f"Failed to construct YANG DataNode for change '{ch.path}': {e}"
                ) from e

        return root_node

    @staticmethod
    def build_from_dict(schema_context: SchemaContext, data: dict) -> Any:
        """
        Parses a dictionary formatted in RFC 7951 JSON representation into a DataNode.
        """
        try:
            json_str = json.dumps(data)
            return schema_context.parse_data_mem(json_str, fmt="json")
        except Exception as e:
            raise SchemaSerializationError(
                f"Failed to construct DataNode from dictionary: {e}"
            ) from e