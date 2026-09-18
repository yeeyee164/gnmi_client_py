# -*- encoding: utf-8 -*-
"""
    cmd.py

    `cmd.py` defines a user interface for the system command lines.
    It has a DataClass named `ParsedConfig` which 'normalizes' information
    given by interfaces. 

    `ParsedConfig` should contain at least one `SessionConfig` which denotes client session.
    `SessionConfig` will be created per each target.
"""
import argparse
import json
import time
from dataclasses import dataclass, field, fields
from typing import List, Optional, Dict, Tuple, Type, Any
from abc import ABC, abstractmethod

from modules.security import SecurityProfile
from util.utils import read_payload

class FileConfigError(Exception):
    """Custom exception raised when given config vlolates some criteria"""
    pass

@dataclass(kw_only=True)
class BaseSessionConfig:
    """
    Universal connection details shared across all protocols
    """

    target: str = ""
    protocol: str = ""
    username: str = ""
    password: str = ""
    security: SecurityProfile = field(default_factory=SecurityProfile)
    operation: str = ""
    insecure: bool = False
    times: int = 1

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


# =====================================================================
# Abstract Intermediate Dataclasses
# =====================================================================

@dataclass(kw_only=True)
class BaseCapabilitiesConfig(BaseSessionConfig):
    """Abstract base for capabilities / hello RPCs."""
    pass


@dataclass(kw_only=True)
class BaseGetConfig(BaseSessionConfig):
    """Abstract base for retrieving operational state or configuration."""
    pass


@dataclass(kw_only=True)
class BaseSetConfig(BaseSessionConfig):
    """Abstract base for mutating or editing configuration."""
    pass


@dataclass(kw_only=True)
class BaseSubscribeConfig(BaseSessionConfig):
    """Abstract base for streaming telemetry or event notifications."""
    subscription_name: str = "default"


# =====================================================================
# Concrete gNMI Dataclasses
# =====================================================================

@dataclass(kw_only=True)
class GNMICapabilitiesConfig(BaseCapabilitiesConfig):
    protocol: str = "gnmi"
    operation: str = "capability"


@dataclass(kw_only=True)
class GNMIGetConfig(BaseGetConfig):
    protocol: str = "gnmi"
    operation: str = "get"
    paths: List[str] = field(default_factory=list)
    prefix: str = ""
    encoding: str = "json_ietf"
    type: str = ""
    data_type: str = "all"

    def __post_init__(self):
        if self.type and not self.data_type:
            self.data_type = self.type
        elif self.data_type and not self.type:
            self.type = self.data_type


@dataclass(kw_only=True)
class GNMISetConfig(BaseSetConfig):
    protocol: str = "gnmi"
    operation: str = "set"
    updates: List[Tuple[str, Any]] = field(default_factory=list)
    replaces: List[Tuple[str, Any]] = field(default_factory=list)
    deletes: List[str] = field(default_factory=list)
    prefix: str = ""
    encoding: str = "json_ietf"



@dataclass(kw_only=True)
class GNMISubscribeConfig(BaseSubscribeConfig):
    protocol: str = "gnmi"
    operation: str = "subscribe"
    paths: List[str] = field(default_factory=list)
    prefix: str = ""
    mode: str = "stream"            # stream, once, poll
    stream_mode: str = "sample"     # sample, on_change, target_defined
    sub_mode: Optional[str] = None
    sample_interval: int = 0        # seconds
    heartbeat_interval: int = 0
    suppress_redundant: bool = False
    encoding: str = "json_ietf"
    updates_only: bool = False
    update_only: bool = False

    def __post_init__(self):
        if self.sub_mode and not self.stream_mode:
            self.stream_mode = self.sub_mode
        elif self.stream_mode and not self.sub_mode:
            self.sub_mode = self.stream_mode
        if self.update_only and not self.updates_only:
            self.updates_only = self.update_only
        elif self.updates_only and not self.update_only:
            self.update_only = self.updates_only


# =====================================================================
# Concrete NETCONF Dataclasses
# =====================================================================

@dataclass(kw_only=True)
class NetconfCapabilitiesConfig(BaseCapabilitiesConfig):
    protocol: str = "netconf"
    operation: str = "capability"
    device: str = "default"


@dataclass(kw_only=True)
class NetconfGetConfig(BaseGetConfig):
    protocol: str = "netconf"
    operation: str = "get"
    source: str = "running"
    filter: Optional[str] = None
    nc_xpath: List[str] = field(default_factory=list)
    identifier: Optional[str] = None
    version: Optional[str] = None
    schema_format: str = "yang"
    with_defaults: Optional[str] = None
    device: str = "default"


@dataclass(kw_only=True)
class NetconfEditConfig(BaseSetConfig):
    protocol: str = "netconf"
    operation: str = "edit-config"
    target_datastore: str = "candidate"
    config: Optional[str] = None
    default_operation: str = "merge"
    test_option: Optional[str] = None
    error_option: str = "stop-on-error"
    device: str = "default"


@dataclass(kw_only=True)
class NetconfSubscribeConfig(BaseSubscribeConfig):
    protocol: str = "netconf"
    operation: str = "subscribe"
    stream_name: str = "NETCONF"
    filter: Optional[str] = None
    start_time: Optional[str] = None
    stop_time: Optional[str] = None
    device: str = "default"


# Backward compatibility aliases
SessionConfig = BaseSessionConfig
GNMISessionConfig = BaseSessionConfig
NetconfSessionConfig = BaseSessionConfig
BaseSetSessionConfig = BaseSetConfig
GNMISetSessionConfig = GNMISetConfig



# =====================================================================
# Session Config Registry & Factory Helper
# =====================================================================

SESSION_CONFIG_REGISTRY: Dict[Tuple[str, str], Type[BaseSessionConfig]] = {
    # gNMI mappings
    ("gnmi", "capability"): GNMICapabilitiesConfig,
    ("gnmi", "capabilities"): GNMICapabilitiesConfig,
    ("gnmi", "get"): GNMIGetConfig,
    ("gnmi", "set"): GNMISetConfig,
    ("gnmi", "subscribe"): GNMISubscribeConfig,
    ("gnmi", "once"): GNMISubscribeConfig,
    ("gnmi", "poll"): GNMISubscribeConfig,
    ("gnmi", "stream"): GNMISubscribeConfig,

    # NETCONF mappings
    ("netconf", "capability"): NetconfCapabilitiesConfig,
    ("netconf", "capabilities"): NetconfCapabilitiesConfig,
    ("netconf", "get"): NetconfGetConfig,
    ("netconf", "get-config"): NetconfGetConfig,
    ("netconf", "get_config"): NetconfGetConfig,
    ("netconf", "get-schema"): NetconfGetConfig,
    ("netconf", "get_schema"): NetconfGetConfig,
    ("netconf", "edit-config"): NetconfEditConfig,
    ("netconf", "edit_config"): NetconfEditConfig,
    ("netconf", "set"): NetconfEditConfig,
    ("netconf", "subscribe"): NetconfSubscribeConfig,
}


def create_session_config(protocol: str = "", operation: str = "", /, **kwargs) -> BaseSessionConfig:
    """Factory helper to safely instantiate specialized session configs."""
    proto = kwargs.pop('protocol', None) or protocol or "gnmi"
    op = kwargs.pop('operation', None) or operation or ""
    norm_proto = proto.lower()
    norm_op = op.lower()
    key = (norm_proto, norm_op)
    cls = SESSION_CONFIG_REGISTRY.get(key)
    if not cls:
        norm_op_dashed = norm_op.replace('_', '-')
        cls = SESSION_CONFIG_REGISTRY.get((norm_proto, norm_op_dashed))
    if not cls:
        raise ValueError(f"No session config registered for protocol='{proto}' and operation='{op}'")

    # Filter kwargs to only fields accepted by the target dataclass
    valid_fields = {f.name for f in fields(cls)}
    filtered_kwargs = {k: v for k, v in kwargs.items() if k in valid_fields}
    if 'protocol' in valid_fields and 'protocol' not in filtered_kwargs:
        filtered_kwargs['protocol'] = proto
    if 'operation' in valid_fields and 'operation' not in filtered_kwargs:
        filtered_kwargs['operation'] = op
    return cls(**filtered_kwargs)


@dataclass
class ParsedConfig:
    """
        For all classes defined in `cmd.py`, it eventually returns
        this class.

        And our management will use that for configure.
    """
    sessions: List[BaseSessionConfig] # List of all individual sessions to spawn
    outputs: Dict                 # Output definitions
    targets: List[str] = field(default_factory=list) # List of "IP:PORT" strings
    debug: bool = False           # Global debug flag

    # for logging this script
    log_level: str = "ERROR"
    syslog_server: str = ""
    log_file: str = ""

    def __str__(self):
        session_strs = "\n".join([str(s) for s in self.sessions])
        return f"""ParsedConfig(debug={self.debug}, outputs={self.outputs},
sessions=[\n{session_strs}\n]
)
"""

class ConfigBuilder(ABC):
    @abstractmethod
    def build(self) -> ParsedConfig:
        """Parse input and return `ParsedConfig` object"""
        pass

class PairedAction(argparse.Action):
    def __init__(self, option_strings, dest, group_type=None, kind=None, **kwargs):
        self.group_type = group_type
        self.kind = kind
        super().__init__(option_strings, dest, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        items = getattr(namespace, self.dest, None)
        if items is None:
            items = []
            setattr(namespace, self.dest, items)
        items.append(values)

        order_attr = f"_{self.group_type}_order"
        order_list = getattr(namespace, order_attr, None)
        if order_list is None:
            order_list = []
            setattr(namespace, order_attr, order_list)
        order_list.append((self.kind, values))


def _parse_paired_options(args, group_type: str) -> List[Tuple[str, str]]:
    """
    Parses paired options (--\<group\>-path with --\<group\>-value or --\<group\>-file).
    - \<group\> is either `update` or `replace`

    Supports both interleaved order and batch lists, validating that every path
    is strictly paired with exactly one value or file.
    """
    order_attr = f"_{group_type}_order"
    order_list = getattr(args, order_attr, None)

    results: List[Tuple[str, str]] = []
    if order_list:
        current_path = None
        for kind, val in order_list:
            if kind == 'path':
                if current_path is not None:
                    raise ValueError(f"Each --{group_type}-path must be paired with either a --{group_type}-value or --{group_type}-file (unpaired path: '{current_path}')")
                val_clean = val.strip()
                if not val_clean:
                    raise ValueError(f"--{group_type}-path cannot be empty")
                current_path = val_clean
            elif kind == 'value':
                if current_path is None:
                    raise ValueError(f"--{group_type}-value must be preceded by --{group_type}-path")
                results.append((current_path, val.strip()))
                current_path = None
            elif kind == 'file':
                if current_path is None:
                    raise ValueError(f"--{group_type}-file must be preceded by --{group_type}-path")
                file_val = val.strip()
                if not file_val:
                    raise ValueError(f"--{group_type}-file cannot be empty")
                if not file_val.startswith('@'):
                    file_val = f"@{file_val}"
                results.append((current_path, file_val))
                current_path = None

        if current_path is not None:
            raise ValueError(f"Each --{group_type}-path must be paired with either a --{group_type}-value or --{group_type}-file (unpaired path: '{current_path}')")
    else:
        paths = getattr(args, f"{group_type}_path", []) or []
        values = getattr(args, f"{group_type}_value", []) or []
        files = getattr(args, f"{group_type}_file", []) or []
        if isinstance(paths, str): paths = [paths]
        if isinstance(values, str): values = [values]
        if isinstance(files, str): files = [files]

        if paths:
            total_val_files = len(values) + len(files)
            if len(paths) != total_val_files:
                raise ValueError(f"Mismatched paired options: {len(paths)} --{group_type}-path options provided, but {total_val_files} values/files given")

            if len(values) == len(paths) and not files:
                for p, v in zip(paths, values):
                    results.append((p.strip(), v.strip()))
            elif len(files) == len(paths) and not values:
                for p, f in zip(paths, files):
                    file_val = f.strip()
                    if not file_val.startswith('@'):
                        file_val = f"@{file_val}"
                    results.append((p.strip(), file_val))
            else:
                val_idx = 0
                file_idx = 0
                for p in paths:
                    if val_idx < len(values):
                        results.append((p.strip(), values[val_idx].strip()))
                        val_idx += 1
                    elif file_idx < len(files):
                        file_val = files[file_idx].strip()
                        if not file_val.startswith('@'):
                            file_val = f"@{file_val}"
                        results.append((p.strip(), file_val))
                        file_idx += 1
        elif values or files:
            raise ValueError(f"--{group_type}-value or --{group_type}-file provided without preceding --{group_type}-path")

    return results


class CLIConfigBuilder(ConfigBuilder):

    def __init__(self, args):
        self.args = args
    
    def build(self) -> ParsedConfig:
        sessions = []

        # check general configuration

        times = self.args.times
        if times <= 0:
            print(f"[Config] times option should be positive integer. Ignore given value")
            times = 1

        outputs = {
            'default_output':{
                'type': getattr(self.args, 'output_type', 'file'),
                'file-type': getattr(self.args, 'output_file_type', 'stdout'),
                'format': getattr(self.args, 'output_format', 'json'),
            }
        }

        if not getattr(self.args, 'protocol', None) or not getattr(self.args, 'operation', None):
            print("[CLI] Error: You must specify a protocol and an operation, or use a --config file.")
            return ParsedConfig(sessions=[], outputs=outputs, debug=self.args.debug)

        targets = self.args.target or []
        protocol = self.args.protocol.lower()
        operation = self.args.operation.lower()

        for target in targets:
            security_profile = SecurityProfile(
                tls_ca=self.args.tls_ca,
                tls_cert=self.args.tls_cert,
                tls_key=self.args.tls_key,
                skip_verify=self.args.skip_verify,
                tls_server_name=self.args.tls_server_name,
                tls_version=self.args.tls_version,
                ssh_key=self.args.ssh_key
            )

            paths = getattr(self.args, 'path', []) or []
            if isinstance(paths, str):
                paths = [paths]

            params = {
                'target': target,
                'protocol': protocol,
                'operation': operation,
                'username': self.args.username,
                'password': self.args.password,
                'security': security_profile,
                'insecure': getattr(self.args, 'insecure', False),
                'times': times,
                'subscription_name': "cli_execution",
            }

            if protocol == 'gnmi':
                gnmi_updates = []
                for item in (getattr(self.args, "updates", []) or getattr(self.args, "update", []) or []):
                    if isinstance(item, tuple):
                        gnmi_updates.append(item)
                    elif isinstance(item, str):
                        if ':::' in item:
                            p, v = item.split(':::', 1)
                            gnmi_updates.append((p.strip(), v.strip()))
                        elif '=' in item and not item.endswith(']'):
                            p, v = item.split('=', 1)
                            gnmi_updates.append((p.strip(), v.strip()))
                        else:
                            gnmi_updates.append((item.strip(), ""))

                gnmi_updates.extend(_parse_paired_options(self.args, 'update'))

                gnmi_replaces = []
                for item in (getattr(self.args, "replaces", []) or getattr(self.args, "replace", []) or []):
                    if isinstance(item, tuple):
                        gnmi_replaces.append(item)
                    elif isinstance(item, str):
                        if ':::' in item:
                            p, v = item.split(':::', 1)
                            gnmi_replaces.append((p.strip(), v.strip()))
                        elif '=' in item and not item.endswith(']'):
                            p, v = item.split('=', 1)
                            gnmi_replaces.append((p.strip(), v.strip()))
                        else:
                            gnmi_replaces.append((item.strip(), ""))
                gnmi_replaces.extend(_parse_paired_options(self.args, 'replace'))

                raw_deletes = getattr(self.args, "delete", []) or getattr(self.args, "deletes", []) or []
                if isinstance(raw_deletes, str):
                    raw_deletes = [raw_deletes]
                gnmi_deletes = [d.strip() for d in raw_deletes if d]

                params.update({
                    'paths': paths,
                    'prefix': getattr(self.args, "prefix", ""),
                    'encoding': getattr(self.args, "encoding", "json_ietf"),
                    'type': getattr(self.args, "type", ''),
                    'data_type': getattr(self.args, "type", '') or 'all',
                    'mode': getattr(self.args, "mode", "stream"),
                    'stream_mode': getattr(self.args, "sub_mode", "sample"),
                    'sub_mode': getattr(self.args, "sub_mode", "sample"),
                    'sample_interval': getattr(self.args, "sample_interval", getattr(self.args, "interval", 0)),
                    'update_only': getattr(self.args, "update_only", False),
                    'updates_only': getattr(self.args, "update_only", False),
                    'updates': gnmi_updates,
                    'replaces': gnmi_replaces,
                    'deletes': gnmi_deletes,
                })
            elif protocol == 'netconf':
                raw_cfg = getattr(self.args, "config", "") or getattr(self.args, "nc_config", "")
                params.update({
                    'filter': read_payload(getattr(self.args, "filter", "")),
                    'config': read_payload(raw_cfg),
                    'source': getattr(self.args, "source", "") or "running",
                    'target_datastore': getattr(self.args, "target_datastore", None) or getattr(self.args, "target", "candidate"),
                    'default_operation': getattr(self.args, "default_operation", "merge"),
                    'error_option': getattr(self.args, "error_option", "stop-on-error"),
                    'test_option': getattr(self.args, "test_option", None),
                    'device': getattr(self.args, "device", "default"),
                    'nc_xpath': getattr(self.args, "nc_xpath", []) or [],
                    'version': getattr(self.args, "version", ""),
                    'identifier': getattr(self.args, "identifier", ""),
                    'schema_format': getattr(self.args, "schema_format", "yang"),
                })
            else:
                raise ValueError(f"Unknown protocol: {protocol}")

            session = create_session_config(protocol, operation, **params)
            sessions.append(session)

        return ParsedConfig(
            sessions=sessions,
            outputs=outputs,
            targets=targets,
            debug=self.args.debug,
            log_level=self.args.log_level,
            syslog_server=self.args.syslog_server,
            log_file=self.args.log_file,
        )

class FileConfigBuilder(ConfigBuilder):
    def __init__(self, path, protocol: str = ""):
        self.protocol = protocol
        self.path = path
        self.data = {}
        try:
            import yaml as _yaml
        except Exception as e:
            raise RuntimeError("PyYAML is required to use --config file parsing. Install with `pip install pyyaml`") from e

        with open(path, 'r') as yfile:
            self.data = _yaml.safe_load(yfile)
        
    def build(self) -> ParsedConfig:
        d = self.data
        sessions = []

        # Global fallbacks
        global_cfg = d.get('global', {})

        # global_operation = global_cfg.get('operation', 'subscribe')
        global_username = global_cfg.get('username', '')
        global_password = global_cfg.get('password', '')
        global_times = global_cfg.get('times', 1)
        global_insecure = global_cfg.get('insecure', False)
        global_sec_cfg = global_cfg.get('security', {})
        global_security = SecurityProfile(
            tls_ca=global_sec_cfg.get('tls_ca', ''),
            tls_cert=global_sec_cfg.get('tls_cert', ''),
            tls_key=global_sec_cfg.get('tls_key', ''),
            skip_verify=global_sec_cfg.get('skip_verify', False),
            tls_server_name=global_sec_cfg.get('tls_server_name', ''),
            tls_version=global_sec_cfg.get('tls_version', '')
        )
        debug = global_cfg.get('debug', False)
        
        # Output parsing
        outputs = d.get('outputs', {
            'default_output': {
                'type': 'file',
                'file-type': 'stdout',
                'format': 'json'
            }
        })

        targets = d.get('targets', [])

        # targets in YAML
        for target_ip_port, tgt_info in targets.items():
            tgt_cnt = 0
            t_username = tgt_info.get('username', global_username)
            t_password = tgt_info.get('password', global_password)
            t_times = tgt_info.get('times', global_times)
            t_protocol = tgt_info.get('protocol', self.protocol) or 'gnmi'
            t_insecure = tgt_info.get('insecure', global_insecure)

            # possible Get, Set, Subscribe list
            t_sub_list = tgt_info.get('subscriptions', [])
            t_get_list = tgt_info.get('get-path', [])
            t_update_list = tgt_info.get('update-list', [])
            t_replace_list = tgt_info.get('replace-list', [])
            t_delete_list = tgt_info.get('delete-list', [])
            t_set_block = tgt_info.get('set', {})
            t_op = (tgt_info.get('operation', '') or tgt_info.get('type', '')).lower()

            # For simplicity, there's only one type of RPC is allowed
            if len(t_sub_list): tgt_cnt += 1
            if len(t_get_list): tgt_cnt += 1
            if len(t_update_list) or len(t_replace_list) or len(t_delete_list) or t_set_block or t_op == 'set': tgt_cnt += 1

            if tgt_cnt > 1:
                raise FileConfigError(f"target {target_ip_port} holds two or more RPC types - only one type of RPC is allowed")

            if len(t_sub_list): # Subscribe
                subs = d.get('subscriptions', {})
                for sub_name in t_sub_list:
                    if sub_name not in subs:
                        raise FileConfigError(f"subscription {sub_name} not found")
                    named_sub = subs[sub_name]

                    update_only = False
                    if 'update_only' in named_sub:
                        update_only = True

                    # subscription in named sub 
                    sub_details = named_sub.get('subscription', {})

                    paths = sub_details.get('path', [])
                    if isinstance(paths, str):
                        paths = [paths]
                    sub_mode = sub_details.get('mode', 'target_defined')
                    sample_interval = sub_details.get('sample_interval', 0)

                    session = create_session_config(
                        t_protocol,
                        'subscribe',
                        target=str(target_ip_port), # Convert in case YAML parses IP as float/int
                        paths=paths,
                        subscription_name=sub_name,
                        operation='subscribe',
                        prefix=named_sub.get('prefix', ''),
                        encoding=named_sub.get('encoding', 'json_ietf'),
                        protocol=t_protocol,
                        insecure=t_insecure,
                        username=t_username,
                        password=t_password,
                        times=t_times,
                        security=global_security,
                        mode=named_sub.get('mode', 'stream'),
                        update_only=update_only,
                        updates_only=update_only,
                        sub_mode=sub_mode,
                        stream_mode=sub_mode,
                        sample_interval=sample_interval
                    )
                    sessions.append(session)
            elif len(t_get_list): # Get
                paths = t_get_list
                if isinstance(paths, str):
                    paths = [paths]

                session = create_session_config(
                    t_protocol,
                    'get',
                    target=str(target_ip_port), # Convert in case YAML parses IP as float/int
                    paths=paths,
                    subscription_name=f'get-{time.time_ns()}',
                    operation='get',
                    prefix=tgt_info.get('prefix', ''),
                    encoding=tgt_info.get('encoding', 'json_ietf'),
                    protocol=t_protocol,
                    insecure=t_insecure,
                    username=t_username,
                    password=t_password,
                    times=t_times,
                    security=global_security,
                )
                sessions.append(session)
                
            else: # Set
                updates = []
                replaces = []
                deletes = []
                set_prefix = tgt_info.get('prefix', '')
                set_encoding = tgt_info.get('encoding', 'json_ietf')

                if t_set_block and isinstance(t_set_block, dict):
                    set_prefix = t_set_block.get('prefix', set_prefix)
                    set_encoding = t_set_block.get('encoding', set_encoding)

                    upd_val = t_set_block.get('update', {})
                    if isinstance(upd_val, dict):
                        updates.extend(list(upd_val.items()))
                    elif isinstance(upd_val, list):
                        for item in upd_val:
                            if isinstance(item, (tuple, list)) and len(item) == 2:
                                updates.append(tuple(item))
                            elif isinstance(item, dict):
                                updates.extend(list(item.items()))
                            elif isinstance(item, str) and ':::' in item:
                                p, v = item.split(':::', 1)
                                updates.append((p.strip(), v.strip()))
                            else:
                                updates.append((item, ""))

                    rep_val = t_set_block.get('replace', {})
                    if isinstance(rep_val, dict):
                        replaces.extend(list(rep_val.items()))
                    elif isinstance(rep_val, list):
                        for item in rep_val:
                            if isinstance(item, (tuple, list)) and len(item) == 2:
                                replaces.append(tuple(item))
                            elif isinstance(item, dict):
                                replaces.extend(list(item.items()))
                            elif isinstance(item, str) and ':::' in item:
                                p, v = item.split(':::', 1)
                                replaces.append((p.strip(), v.strip()))
                            else:
                                replaces.append((item, ""))

                    del_val = t_set_block.get('delete', [])
                    if isinstance(del_val, str):
                        deletes.append(del_val)
                    elif isinstance(del_val, list):
                        deletes.extend(del_val)

                if t_update_list:
                    items = t_update_list if isinstance(t_update_list, list) else [t_update_list]
                    for item in items:
                        if isinstance(item, (tuple, list)) and len(item) == 2:
                            updates.append(tuple(item))
                        elif isinstance(item, dict):
                            updates.extend(list(item.items()))
                        elif isinstance(item, str) and ':::' in item:
                            p, v = item.split(':::', 1)
                            updates.append((p.strip(), v.strip()))
                        else:
                            updates.append((item, ""))

                if t_replace_list:
                    items = t_replace_list if isinstance(t_replace_list, list) else [t_replace_list]
                    for item in items:
                        if isinstance(item, (tuple, list)) and len(item) == 2:
                            replaces.append(tuple(item))
                        elif isinstance(item, dict):
                            replaces.extend(list(item.items()))
                        elif isinstance(item, str) and ':::' in item:
                            p, v = item.split(':::', 1)
                            replaces.append((p.strip(), v.strip()))
                        else:
                            replaces.append((item, ""))

                if t_delete_list:
                    if isinstance(t_delete_list, str):
                        deletes.append(t_delete_list)
                    elif isinstance(t_delete_list, list):
                        deletes.extend(t_delete_list)

                session = create_session_config(
                    t_protocol,
                    'set',
                    target=str(target_ip_port), # Convert in case YAML parses IP as float/int
                    subscription_name=f'set-{time.time_ns()}',
                    prefix=set_prefix,
                    operation='set',
                    encoding=set_encoding,
                    protocol=t_protocol,
                    insecure=t_insecure,
                    username=t_username,
                    password=t_password,
                    times=t_times,
                    security=global_security,
                    updates=updates,
                    replaces=replaces,
                    deletes=deletes,
                )
                sessions.append(session)

        return ParsedConfig(
            sessions=sessions, targets=targets,
            outputs=outputs, debug=debug,
            log_level=d.get('log_level', 'ERROR'),
            syslog_server=d.get('syslog_server', ''),
            log_file=d.get('log_file', ''),
        )

def build_args(args=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="gNMI / NETCONF Client")

    parser.add_argument('-c', '--config', '-g', '--global-config', dest='config', default='', help='Path to YAML configuration file for this client')
    parser.add_argument('-t', '--target', action='append', help="List of targets in IP:PORT format")
    parser.add_argument('-d', '--debug', help="Debugging this script", action='store_true')
    parser.add_argument('--times', default=1, type=int, help="Generate duplicated requests - only use for testing")
    parser.add_argument('-u', '--username', default='', help="Username")
    parser.add_argument('-p', '--password', default='', help="Password")
    parser.add_argument('-i', '--insecure', action='store_true',
                        help="use insecure connection if set True")

    # output specifiers
    parser.add_argument('--output-type', default='file', help="Type of output data.")
    parser.add_argument('--output-file-type', default='stdout', help="direction of output data.")
    parser.add_argument('--output-format', default='json',
                        help="Specify output format.", choices=['json', 'text', 'xml'])

    # security options
    parser.add_argument('--tls-ca', default='', help="Path to CA certificate")
    parser.add_argument('--tls-cert', default='', help="Path to client certificate")
    parser.add_argument('--tls-key', default='', help="Path to client private key")
    parser.add_argument('--skip-verify', action='store_true', help="Path to CA certificate")
    parser.add_argument('--tls-server-name', default='', help="sets the server name to be used when verifying the hostname on the returned certificates. If 'skip-verify' was set, this options is meaningless.")
    parser.add_argument('--tls-version', default='1.3', choices=['1.0','1.1','1.2','1.3'],
                         help="set TLS version. Default version is 1.3")
    parser.add_argument('--ssh-key', help="Path to SSH key")
    
    # logger
    parser.add_argument('--log-level', default='ERROR',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        help="Set logging level")
    parser.add_argument('--syslog-server', default='', help="IP:PORT of Syslog server")
    parser.add_argument('--log-file', default='', help="Path to save local logs")

    proto_parser = parser.add_subparsers(dest='protocol', help="select NB protcol")

    # add NETCONF parser
    netconf_args(proto_parser)

    # add gNMI parser
    gnmi_args(proto_parser)

    return parser.parse_args(args)

def netconf_args(parser):
    parser_nc = parser.add_parser('netconf', help='NETwork CONFiguration') 

    parser_nc.add_argument('--device', default='default', help="Name of vendor-specific device")
    # config file for NETCONF
    parser_nc.add_argument('-c', '--config', default='', help='Path to YAML configuration file for NETCONF RPCs')

    subparsers = parser_nc.add_subparsers(dest='operation', help='specify supported NETCONF operation')

    # <hello>
    parser_cap = subparsers.add_parser('capability', help="Fetch NETCONF Server Capabilities")

    # <get>
    parser_get = subparsers.add_parser('get', help="NETCONF <get>")
    parser_get.add_argument('--filter', default='',
                            help="XML filter string or path to file. If given path not exists, consider it as a 'XML' formatted request")
    parser_get.add_argument('--nc-xpath', action='append', help="List of selected NETCONF XPaths")

    # <get-config>
    parser_get_config = subparsers.add_parser('get-config', help="NETCONF <get-config>")
    parser_get_config.add_argument('--source', default='', help="specify one of 'running', 'candidate', 'startup' if you want to request <get-config> or do not present for <get>")
    parser_get_config.add_argument('--filter', default='',
                            help="XML filter string or path to file. If given path not exists, consider it as a 'XML' formatted request")
    parser_get_config.add_argument('--nc-xpath', action='append', help="List of selected NETCONF XPaths")

    # <get-schema>
    parser_get_schema = subparsers.add_parser('get-schema', help="NETCONF <get-schema>")
    parser_get_schema.add_argument('--identifier', default='',
                                   help="Identifier for the schema list entry.", required=True)
    parser_get_schema.add_argument('--version', help="Version of the schema requested")
    parser_get_schema.add_argument('--schema-format', default='yang', help="The data modeling language of the schema")

    # <edit-config>
    parser_set = subparsers.add_parser('edit-config', aliases=['set'], help="NETCONF <edit-config>")
    parser_set.add_argument('--target-datastore', '--target', dest='target_datastore', default='candidate',
                            choices=['candidate', 'running', 'startup'], help="Target datastore (default: candidate)")
    parser_set.add_argument('-C', '--config', '--nc-config', dest='nc_config', required=True,
                            help="XML string or path to file containing configuration tree")
    parser_set.add_argument('--default-operation', choices=['merge', 'replace', 'none'], default='merge',
                            help="Default operation for <edit-config> (default: merge)")
    parser_set.add_argument('--error-option', choices=['stop-on-error', 'continue-on-error', 'rollback-on-error'],
                            default='stop-on-error', help="Error option behavior (default: stop-on-error)")
    parser_set.add_argument('--test-option', choices=['test-then-set', 'set', 'test-only'], default=None,
                            help="Test option if target supports :validate")


def gnmi_args(parser):
    parser_gnmi = parser.add_parser('gnmi', help='gRPC Network Management Interfaces') 

    # config file for gNMI
    parser_gnmi.add_argument('-c', '--config', default='', help='Path to YAML configuration file for gNMI RPCs')
    parser_gnmi.add_argument('-e', '--encoding', default='json_ietf',
                        help="encoding formats defined at gNMI", 
                        choices=['json', 'json_ietf', 'bytes', 'proto', 'ascii'])

    # Top-Level Operation Parser
    subparsers = parser_gnmi.add_subparsers(dest='operation', help="specify gNMI RPC operation")

    # UNARY: Capabilities
    parser_cap = subparsers.add_parser('capability', help='execute CAPABILITIES RPC')
    
    # UNARY: Get
    parser_get = subparsers.add_parser('get', help='execute GET RPC')
    parser_get.add_argument('--type', choices=['config', 'state', 'operational', ''], default='', help="The type of data that is requested from the target. An empty value will grab all kinds of data")
    parser_get.add_argument('--path', action='append', help="List of gNMI Paths")
    parser_get.add_argument('--prefix', default='', help="common prefix for all given paths")

    # UNARY: Set
    parser_set = subparsers.add_parser('set', help='execute SET RPC')
    parser_set.add_argument('--prefix', default='', help="common prefix for all given paths")
    parser_set.add_argument('--update', action='append', help='Update path and value (format: PATH:::VALUE or PATH:::@file)')
    parser_set.add_argument('--update-path', action=PairedAction, group_type='update', kind='path',
                            help='Target path for update operation (paired with --update-value or --update-file)')
    parser_set.add_argument('--update-value', action=PairedAction, group_type='update', kind='value',
                            help='Inline value for update operation (paired with --update-path)')
    parser_set.add_argument('--update-file', action=PairedAction, group_type='update', kind='file',
                            help='File path containing payload for update operation (paired with --update-path)')
    parser_set.add_argument('--replace', action='append', help='Replace path and value (format: PATH:::VALUE or PATH:::@file)')
    parser_set.add_argument('--replace-path', action=PairedAction, group_type='replace', kind='path',
                            help='Target path for replace operation (paired with --replace-value or --replace-file)')
    parser_set.add_argument('--replace-value', action=PairedAction, group_type='replace', kind='value',
                            help='Inline value for replace operation (paired with --replace-path)')
    parser_set.add_argument('--replace-file', action=PairedAction, group_type='replace', kind='file',
                            help='File path containing payload for replace operation (paired with --replace-path)')
    parser_set.add_argument('--delete', action='append', help='Delete path')
    parser_set.add_argument('--encoding', default='json_ietf',
                            choices=['json', 'json_ietf', 'bytes', 'proto', 'ascii'],
                            help="encoding format for SET RPC")

    # Subscribe operation
    parser_sub = subparsers.add_parser('subscribe', help="specify mode for STREAM mode of Subscribe RPC")

    parser_sub.add_argument('--path', action='append', help="List of gNMI Paths")
    parser_sub.add_argument('--prefix', default='', help="common prefix for all given paths")
    parser_sub.add_argument('--mode', choices=['once', 'poll', 'stream'], default='stream',
                            help='one of once, poll or stream(default is stream)')

    parser_sub.add_argument('--sub-mode', choices=['sample', 'on_change', 'target_defined'],
                            default='sample', help='choose Subscribe stream mode(default is sample)')
    parser_sub.add_argument('--update-only', help="skip initial responses from server", action='store_true')
    parser_sub.add_argument('--sample-interval', type=int, default=90, help='sample interval in seconds')

def config_builder(args) -> ParsedConfig:
    """Build an appropriate `ParsedConfig` class by the contents of argument"""
    config_file = getattr(args, 'config', '') or getattr(args, 'global_config', '')
    if config_file and (getattr(args, 'protocol', None) is None or getattr(args, 'operation', None) is None):
        protocol = getattr(args, 'protocol', 'unknown')
        return FileConfigBuilder(config_file, protocol=protocol).build()
    else:
        return CLIConfigBuilder(args).build()

def parse_args(args=None) -> ParsedConfig:
    """Helper to parse raw argument list and build ParsedConfig directly."""
    return config_builder(build_args(args))