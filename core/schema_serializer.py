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
        r"""
        Builds XML subtree for NETCONF \<edit-config\> with attached nc:operation metadata
        faithfully preserved on each targeted element.
        """
        if not changes:
            return ""

        # Build data tree
        dnode = DataBuilder.build_from_changes(schema_context, changes)
        xml_str = self.to_xml(dnode)
        if not xml_str:
            return ""

        import re
        change_op_map = {
            ChangeType.MERGE: "merge",
            ChangeType.REPLACE: "replace",
            ChangeType.DELETE: "delete",
            ChangeType.CREATE: "create",
            ChangeType.REMOVE: "remove",
        }

        # Register namespaces from the generated XML
        for pfx, uri in re.findall(r'xmlns(?::([a-zA-Z0-9_\-]+))?="([^"]+)"', xml_str):
            ET.register_namespace(pfx or "", uri)
        ET.register_namespace("nc", NETCONF_BASE_NS)

        try:
            root = ET.fromstring(xml_str)
        except Exception:
            # Fallback if ElementTree parsing fails on fragment
            return xml_str

        def _find_element_by_xpath(r: ET.Element, xpath: str) -> Optional[ET.Element]:
            cleaned = xpath.strip()
            if cleaned.startswith("/"):
                cleaned = cleaned[1:]
            steps = re.findall(r"(?:[^/\[]+(?:\[[^\]]+\])*)", cleaned)
            if not steps:
                return None

            def _tag_matches(elem_tag: str, step_tag: str) -> bool:
                name = step_tag.split(":")[-1]
                elem_name = elem_tag.split("}")[-1] if "}" in elem_tag else elem_tag
                return elem_name == name

            first_step = steps[0]
            first_tag = re.sub(r"\[[^\]]+\]", "", first_step)
            if not _tag_matches(r.tag, first_tag):
                return None

            curr = r
            for step in steps[1:]:
                step_tag = re.sub(r"\[[^\]]+\]", "", step)
                preds = re.findall(r'\[([a-zA-Z0-9_\-\.\:]+)\s*=\s*[\'"]([^\'"]+)[\'"]\]', step)
                matched_child = None
                for child in curr:
                    if _tag_matches(child.tag, step_tag):
                        if preds:
                            match_all = True
                            for pk, pv in preds:
                                p_child = None
                                for c in child:
                                    if _tag_matches(c.tag, pk):
                                        p_child = c
                                        break
                                if p_child is None or (p_child.text or "").strip() != pv:
                                    match_all = False
                                    break
                            if match_all:
                                matched_child = child
                                break
                        else:
                            matched_child = child
                            break
                if matched_child is None:
                    return None
                curr = matched_child
            return curr

        applied_count = 0
        for ch in changes:
            ch_op = change_op_map.get(ch.operation, default_operation)
            if ch_op != default_operation:
                elem = _find_element_by_xpath(root, ch.path)
                if elem is not None:
                    elem.set(f"{{{NETCONF_BASE_NS}}}operation", ch_op)
                    applied_count += 1

        # If a single change has non-default operation but inner path wasn't tagged, attach to root
        if applied_count == 0 and len(changes) == 1:
            first_op = change_op_map.get(changes[0].operation, default_operation)
            if first_op != default_operation:
                root.set(f"{{{NETCONF_BASE_NS}}}operation", first_op)

        return ET.tostring(root, encoding="unicode")

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