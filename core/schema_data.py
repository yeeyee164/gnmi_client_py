# -*- encoding: utf-8 -*-
"""
schema_data.py

Constructs compiled libyang DataNode trees from abstract operational Change objects
or Python dictionaries without protocol-specific metadata.
"""
from __future__ import annotations
import re
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

    @classmethod
    def populate_tree(
        cls,
        schema_context: SchemaContext,
        base_path: str,
        val: Any,
        root_node: Any = None,
    ) -> Any:
        """
        Recursively binds a structured Python dictionary, list, or scalar value
        to the specified YANG base_path within the compiled SchemaContext.
        """
        clean_base = base_path.strip()
        if not clean_base.startswith("/"):
            clean_base = "/" + clean_base

        if isinstance(val, dict):
            if not val:
                node = schema_context.create_data_path(clean_base)
                return node if root_node is None else (root_node.merge(node) or root_node)
            for k, v in val.items():
                child_path = f"{clean_base}/{k}"
                root_node = cls.populate_tree(schema_context, child_path, v, root_node)
            return root_node
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    # Inspect schema node for base_path to extract list keys
                    schema_path = re.sub(r"\[[^\]]+\]", "", clean_base)
                    try:
                        snodes = list(schema_context.find_path(schema_path))
                    except Exception:
                        snodes = []
                    item_path = clean_base
                    if snodes and hasattr(snodes[0], "keys"):
                        key_leafs = [k.name() for k in snodes[0].keys()]
                        key_preds = []
                        for k in key_leafs:
                            if k in item:
                                val_escaped = str(item[k]).replace('"', '\\"')
                                key_preds.append(f'{k}="{val_escaped}"')
                        if key_preds:
                            pred_str = "][".join(key_preds)
                            item_path = f"{clean_base}[{pred_str}]"
                    root_node = cls.populate_tree(schema_context, item_path, item, root_node)
                else:
                    val_str = str(item).lower() if isinstance(item, bool) else (str(item) if item is not None else "")
                    node = schema_context.create_data_path(clean_base, value=val_str)
                    root_node = node if root_node is None else (root_node.merge(node) or root_node)
            return root_node
        else:
            val_str = str(val).lower() if isinstance(val, bool) else (str(val) if val is not None else None)
            node = schema_context.create_data_path(clean_base, value=val_str)
            return node if root_node is None else (root_node.merge(node) or root_node)

    @classmethod
    def build_from_changes(cls, schema_context: SchemaContext, changes: Sequence[Change]) -> Any:
        """
        Populates a libyang data tree from a sequence of `Change` objects.
        Explicitly binds each change's path to its scalar or structured value.
        """
        root_node = None

        for ch in changes:
            path = ch.path if ch.path.startswith("/") else "/" + ch.path
            val = ch.value

            try:
                if ch.operation in (ChangeType.DELETE, ChangeType.REMOVE) and val is None:
                    node = schema_context.create_data_path(path)
                elif isinstance(val, (dict, list)):
                    node = cls.populate_tree(schema_context, path, val)
                else:
                    val_str = str(val).lower() if isinstance(val, bool) else (str(val) if val is not None else None)
                    node = schema_context.create_data_path(path, value=val_str)

                if root_node is None:
                    root_node = node
                elif node is not None:
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
            node = schema_context.parse_data_mem(json_str, fmt="json")
            if node and hasattr(node, "name") and node.name() == "schema-mounts" and hasattr(node, "siblings"):
                for sib in node.siblings():
                    if sib.name() != "schema-mounts":
                        return sib
            return node
        except Exception as e:
            raise SchemaSerializationError(
                f"Failed to construct DataNode from dictionary: {e}"
            ) from e