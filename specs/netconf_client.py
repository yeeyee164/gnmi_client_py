from __future__ import annotations
import os
import logging
from typing import Iterator, Any, Optional

try:
    from ncclient import manager, operations
except ImportError:
    manager = None
    operations = None

from specs.base_client import BaseClient
from modules.security import SecurityModule
from config.operations import (
    CapabilitiesOperation,
    GetOperation,
    SetOperation,
    SubscribeOperation,
    GetSchemaOperation,
    ChangeType,
)
from config.selectors import PathSelector, FilterSelector
from config.protocol_options.netconf import NetconfOptions

NETCONF_BASE_NS = "urn:ietf:params:xml:ns:netconf:base:1.0"
NETCONF_NS = {
    'nc': NETCONF_BASE_NS
}

logger = logging.getLogger(__name__)

class NetconfClient(BaseClient):
    """
    A "Lite" NETCONF Client utilizing ncclient.
    Currently accepts raw XPath strings or XML Subtree for its paths/filters.
    Future versions will utilize libyang to translate standard paths to XML Subtrees.
    """
    def __init__(self, target: str, username: str = "", password: str = "",
                 security_module=None, **kwargs):
        self.target = target
        self.username = username
        self.password = password
        self.security_module = security_module
        self.session = None
        self.device = kwargs.get('device', 'default')

    def __enter__(self):
        host, port = self.target.split(':')
        
        netconf_info = {
            'host': host,
            'port': int(port),
            'username': self.username,
            'password': self.password,
            'device_params': {"name": self.device},
            'hostkey_verify': False
        }

        if self.security_module:
            ssh_kwargs = self.security_module.get_ssh_kwargs()
            if ssh_kwargs:
                netconf_info.update(ssh_kwargs)

        self.session = manager.connect(**netconf_info)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            try:
                if self.session.connected:
                    self.session.close_session()
            except Exception:
                pass

    # =========================================================================
    # Semantic Intent Operations
    # =========================================================================

    def execute_capabilities(self, operation: CapabilitiesOperation) -> Any:
        """Executes Capabilities discovery based on CapabilitiesOperation."""
        return self.capability()

    def execute_schema(self, operation: GetSchemaOperation) -> Any:
        """Executes schema retrieval based on GetSchemaOperation."""
        fmt = operation.format
        if fmt and fmt.lower() == 'yang':
            fmt = None
        return self.session.get_schema(
            identifier=operation.identifier,
            version=operation.version or None,
            format=fmt
        )

    def execute_get(self, operation: GetOperation) -> Any:
        """Executes <get> or <get-config> based on GetOperation."""
        filter_arg = None
        paths = []
        if isinstance(operation.selector, FilterSelector):
            filter_arg = operation.selector.expression
        elif isinstance(operation.selector, PathSelector):
            paths = list(operation.selector.paths)

        source = "running"
        if isinstance(operation.protocol_options, NetconfOptions):
            source = operation.protocol_options.source or "running"

        op_name = "get-config" if operation.read_scope == "config" else "get"
        return self.get(
            operation=op_name,
            source=source,
            filter=filter_arg,
            paths=paths
        )

    def execute_set(self, operation: SetOperation) -> Any:
        """Executes <edit-config> based on SetOperation and Change objects."""
        target_ds = "candidate"
        default_op = "merge"
        error_opt = "stop-on-error"
        test_opt = None
        commit = True
        raw_config = None

        if isinstance(operation.protocol_options, NetconfOptions):
            target_ds = operation.protocol_options.target_datastore
            default_op = operation.protocol_options.default_operation
            error_opt = operation.protocol_options.error_option
            test_opt = operation.protocol_options.test_option
            commit = operation.protocol_options.commit
            raw_config = operation.protocol_options.config

        updates = []
        replaces = []
        deletes = []
        creates = []
        removes = []
        for change in operation.changes:
            val = change.value if change.value is not None else change.path
            if change.operation == ChangeType.MERGE:
                updates.append(val)
            elif change.operation == ChangeType.REPLACE:
                replaces.append(val)
            elif change.operation == ChangeType.DELETE:
                deletes.append(val)
            elif change.operation == ChangeType.CREATE:
                creates.append(val)
            elif change.operation == ChangeType.REMOVE:
                removes.append(val)

        return self.set(
            config=raw_config,
            target_datastore=target_ds,
            default_operation=default_op,
            error_option=error_opt,
            test_option=test_opt,
            commit=commit,
            updates=updates or None,
            replaces=replaces or None,
            deletes=deletes or None,
            creates=creates or None,
            removes=removes or None,
        )

    def execute_subscribe(self, operation: SubscribeOperation) -> Iterator[Any]:
        """Executes NETCONF Event Notifications (RFC 5277) based on SubscribeOperation."""
        return self.subscribe(None)

    # =========================================================================
    # Legacy Methods & Internal Helpers
    # =========================================================================

    def capability(self, **kwargs) -> Any:
        """NETCONF exchanges <hello> when the session has established"""
        return list(self.session.server_capabilities)

    def get(self, **kwargs) -> Any:
        """
        Executes a NETCONF <get>, <get-config>, <get-schema>.
        """
        try:
            paths = kwargs.get('nc_xpath') or kwargs.get('path') or kwargs.get('paths') or []
            if isinstance(paths, str):
                paths = [paths]

            op = kwargs.get('operation', 'get').lower()

            identifier = kwargs.get('identifier')
            if op == 'get-schema' or identifier:
                ident = identifier or (paths[0] if paths else None)
                if not ident:
                    raise ValueError("An Identifier (YANG module name) is required for <get-schema>")

                version = kwargs.get('version') or None
                fmt = kwargs.get('schema_format') or kwargs.get('format')
                if fmt and fmt.lower() == 'yang':
                    fmt = None

                return self.session.get_schema(identifier=ident, version=version, format=fmt)

            source = kwargs.get('source', '')
            raw_filter = kwargs.get('filter', '')
            filter_xml = ""

            if raw_filter and os.path.isfile(raw_filter):
                try:
                    with open(raw_filter, 'r', encoding='utf-8') as f:
                        raw_filter = f.read().strip()
                except Exception as e:
                    logger.warning(f"[NetconfClient] Failed to read filter file '{raw_filter}': {e}")

            if raw_filter:
                stripped = raw_filter.strip()
                if stripped.startswith('<'):
                    if stripped.startswith('<filter'):
                        filter_xml = stripped
                    else:
                        filter_xml = f'<filter xmlns="{NETCONF_BASE_NS}" type="subtree">{stripped}</filter>'
                else:
                    filter_xml = f'<filter type="xpath" select="{stripped}"/>'
            elif paths:
                xpath_filter = " | ".join(paths)
                filter_xml = f"""<filter type="xpath" select="{xpath_filter}"/>"""

            if 'type="xpath"' in filter_xml:
                if not any(':xpath' in cap for cap in self.session.server_capabilities):
                    logger.warning("[NetconfClient] Server does not advertise :xpath capability. Request may fail.")

            logger.debug(f"[NetconfClient] Operation: {op}, source: {source}")

            if op == 'get-config':
                src = source if source else 'running'
                if filter_xml:
                    return self.session.get_config(source=src, filter=filter_xml)
                else:
                    return self.session.get_config(source=src)
            else:
                if filter_xml:
                    return self.session.get(filter=filter_xml)
                else:
                    return self.session.get()
        except operations.RPCError as e:
            return e

    def set(self,
            updates: Optional[list] = None,
            replaces: Optional[list] = None,
            deletes: Optional[list] = None,
            creates: Optional[list] = None,
            removes: Optional[list] = None,
            **kwargs) -> Any:
        """
        Executes a NETCONF <edit-config>.
        Handles raw XML strings, file paths, and structured config elements.
        """
        try:
            raw_config = kwargs.get('config') or kwargs.get('nc_config', '')
            if raw_config and os.path.isfile(raw_config):
                try:
                    with open(raw_config, 'r', encoding='utf-8') as f:
                        raw_config = f.read().strip()
                except Exception as e:
                    logger.warning(f"[NetconfClient] Failed to read config file '{raw_config}': {e}")

            extracted_target = None
            extracted_default_op = None
            extracted_test_op = None
            extracted_error_op = None
            config_xml = ""

            if raw_config:
                stripped = raw_config.strip()
                if stripped.startswith('<'):
                    try:
                        from lxml import etree
                        root = etree.fromstring(stripped.encode('utf-8'))
                        if root.tag.endswith('rpc'):
                            edit_cfg = root.find('nc:edit-config', namespaces=NETCONF_NS)
                            if edit_cfg is None:
                                edit_cfg = root.find('edit-config')
                            if edit_cfg is not None:
                                root = edit_cfg
                        if root.tag.endswith('edit-config'):
                            target_el = root.find('nc:target', namespaces=NETCONF_NS)
                            if target_el is None:
                                target_el = root.find('target')
                            if target_el is not None and len(target_el) > 0:
                                extracted_target = etree.QName(target_el[0]).localname
                            def_op_el = root.find('nc:default-operation', namespaces=NETCONF_NS)
                            if def_op_el is None:
                                def_op_el = root.find('default-operation')
                            if def_op_el is not None:
                                extracted_default_op = def_op_el.text
                            test_op_el = root.find('nc:test-option', namespaces=NETCONF_NS)
                            if test_op_el is None:
                                test_op_el = root.find('test-option')
                            if test_op_el is not None and test_op_el.text:
                                extracted_test_op = test_op_el.text.strip()
                            err_op_el = root.find('nc:error-option', namespaces=NETCONF_NS)
                            if err_op_el is None:
                                err_op_el = root.find('error-option')
                            if err_op_el is not None and err_op_el.text:
                                extracted_error_op = err_op_el.text.strip()
                            config_elem = root.find('nc:config', namespaces=NETCONF_NS)
                            if config_elem is None:
                                config_elem = root.find('config')
                            if config_elem is not None:
                                config_xml = etree.tostring(config_elem, encoding='unicode')
                        elif root.tag.endswith('config'):
                            config_xml = etree.tostring(root, encoding='unicode')
                        else:
                            config_xml = f'<config xmlns="{NETCONF_BASE_NS}">\n{stripped}\n</config>'
                    except Exception:
                        if stripped.startswith('<config'):
                            config_xml = stripped
                        else:
                            config_xml = f'<config xmlns="{NETCONF_BASE_NS}">\n{stripped}\n</config>'
                else:
                    config_xml = f'<config xmlns="{NETCONF_BASE_NS}">\n{stripped}\n</config>'
            else:
                def _tag_snippet(snippet: Any, op_name: str) -> str:
                    snip_str = str(snippet).strip()
                    if not snip_str:
                        return ""
                    if snip_str.startswith('<'):
                        try:
                            from lxml import etree
                            node = etree.fromstring(snip_str.encode('utf-8'))
                            if op_name:
                                node.set('{urn:ietf:params:xml:ns:netconf:base:1.0}operation', op_name)
                            return etree.tostring(node, encoding='unicode')
                        except Exception:
                            return snip_str
                    return snip_str

                xml_snippets = []
                for c in (creates or []):
                    xml_snippets.append(_tag_snippet(c, 'create'))
                for rm in (removes or []):
                    xml_snippets.append(_tag_snippet(rm, 'remove'))
                for u in (updates or []):
                    xml_snippets.append(_tag_snippet(u, 'merge'))
                for r in (replaces or []):
                    xml_snippets.append(_tag_snippet(r, 'replace'))
                for d in (deletes or []):
                    xml_snippets.append(_tag_snippet(d, 'delete'))

                inner = "\n".join(s for s in xml_snippets if s)
                config_xml = f'<config xmlns="{NETCONF_BASE_NS}" xmlns:nc="{NETCONF_BASE_NS}">\n{inner}\n</config>'

            target_ds = kwargs.get('target_datastore') or kwargs.get('target') or extracted_target or 'candidate'

            if target_ds == 'candidate':
                if not any(':candidate' in cap for cap in self.session.server_capabilities):
                    logger.warning("[NetconfClient] Server does not advertise :candidate capability. Falling back to 'running'.")
                    target_ds = 'running'

            default_op = kwargs.get('default_operation') or kwargs.get('default_op') or extracted_default_op or 'merge'
            default_op = default_op.lower() if default_op else 'merge'
            if default_op not in ['merge', 'replace', 'none']:
                default_op = 'merge'

            error_option = kwargs.get('error_option') or extracted_error_op or 'stop-on-error'
            test_option = kwargs.get('test_option') or extracted_test_op

            logger.debug(f"[NetconfClient] edit-config target={target_ds}, default_op={default_op}, error_option={error_option}")
            edit_kwargs = {
                'target': target_ds,
                'config': config_xml,
                'default_operation': default_op,
                'error_option': error_option
            }
            if test_option:
                edit_kwargs['test_option'] = test_option

            res = self.session.edit_config(**edit_kwargs)

            commit_requested = kwargs.get('commit', True)
            if commit_requested and target_ds == 'candidate' and hasattr(self.session, 'commit'):
                try:
                    self.session.commit()
                except operations.RPCError as e:
                    logger.error(f"[NetconfClient] Commit failed: {e}")
                    return e

            return res
        except operations.RPCError as e:
            return e

    def subscribe(self, request_iterator: Any) -> Iterator[Any]:
        """
        Executes NETCONF Event Notifications (RFC 5277).
        """
        self.session.create_subscription()
        
        while True:
            notif = self.session.take_notification(block=True)
            if notif:
                yield notif

