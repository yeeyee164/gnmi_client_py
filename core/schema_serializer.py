# -*- encoding: utf-8 -*-
"""
schema_serializer.py

Serializes libyang DataNode trees into cleanly namespaced XML (for NETCONF)
and RFC 7951 JSON (for gNMI), keeping protocol-specific wrapping decoupled.
"""
from __future__ import annotations
import logging
import xml.etree.ElementTree as ET
from typing import Sequence, Optional, Any, Union

from config.operations import Change, ChangeType
from core.schema_context import SchemaContext
from core.schema_data import DataBuilder
from core.schema_errors import SchemaSerializationError

NETCONF_BASE_NS = "urn:ietf:params:xml:ns:netconf:base:1.0"

logger = logging.getLogger(__name__)


class SchemaSerializer:
    """
    Translates libyang DataNode structures into wire-ready XML or RFC 7951 JSON strings.
    """

    def to_xml(self, data_node: Any, with_siblings: bool = True) -> str:
        """
        Serializes a libyang DataNode to an XML string with fully resolved namespaces.
        """
        if data_node is None:
            return ""
        try:
            raw_xml = data_node.print_mem("xml", with_siblings=with_siblings)
            if raw_xml is None:
                # If root was empty, search siblings for non-empty content
                if hasattr(data_node, "siblings"):
                    for sib in data_node.siblings():
                        if sib.name() != "schema-mounts":
                            sib_xml = sib.print_mem("xml", with_siblings=False)
                            if sib_xml:
                                return sib_xml.strip()
                return ""
            return raw_xml.strip()
        except Exception as e:
            raise SchemaSerializationError(f"Failed to serialize DataNode to XML: {e}") from e

    def to_json_ietf(self, data_node: Any, with_siblings: bool = True) -> str:
        """
        Serializes a libyang DataNode to RFC 7951 JSON.
        """
        if data_node is None:
            return ""
        try:
            raw_json = data_node.print_mem("json", with_siblings=with_siblings)
            if raw_json is None:
                if hasattr(data_node, "siblings"):
                    for sib in data_node.siblings():
                        if sib.name() != "schema-mounts":
                            sib_json = sib.print_mem("json", with_siblings=False)
                            if sib_json:
                                return sib_json.strip()
                return "{}"
            return raw_json.strip()
        except Exception as e:
            raise SchemaSerializationError(f"Failed to serialize DataNode to RFC 7951 JSON: {e}") from e

    def serialize_netconf_edit_config(
        self,
        schema_context: SchemaContext,
        changes: Sequence[Change],
        default_operation: str = "merge",
    ) -> str:
        """
        Builds XML subtree for NETCONF <edit-config> with attached nc:operation metadata.
        """
        if not changes:
            return ""

        # Build data tree
        dnode = DataBuilder.build_from_changes(schema_context, changes)
        xml_str = self.to_xml(dnode)
        if not xml_str:
            return ""

        # Attach nc:operation attribute to root opening tag if differing from "merge"
        change_op_map = {
            ChangeType.MERGE: "merge",
            ChangeType.REPLACE: "replace",
            ChangeType.DELETE: "delete",
            ChangeType.CREATE: "create",
            ChangeType.REMOVE: "remove",
        }
        primary_op = change_op_map.get(changes[0].operation, default_operation)
        if primary_op != "merge":
            import re
            nc_attr = f'xmlns:nc="{NETCONF_BASE_NS}" nc:operation="{primary_op}"'
            xml_str = re.sub(r'^(<[a-zA-Z0-9_\-\.\:]+)', rf'\1 {nc_attr}', xml_str, count=1)

        return xml_str

    def serialize_gnmi_update(
        self,
        schema_context: SchemaContext,
        change: Change,
    ) -> str:
        """
        Serializes a single gNMI Change to RFC 7951 JSON string.
        """
        dnode = DataBuilder.build_from_changes(schema_context, [change])
        return self.to_json_ietf(dnode)