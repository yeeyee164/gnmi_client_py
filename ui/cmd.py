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
from typing import List, Optional, Dict, Tuple, Type
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
    updates: List[Tuple[str, str]] = field(default_factory=list)
    replaces: List[Tuple[str, str]] = field(default_factory=list)
    deletes: List[str] = field(default_factory=list)
    prefix: str = ""


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
                    'updates': getattr(self.args, "updates", []) or getattr(self.args, "update", []),
                    'replaces': getattr(self.args, "replaces", []) or getattr(self.args, "replace", []),
                    'deletes': getattr(self.args, "delete", []) or getattr(self.args, "deletes", []),
                })
            elif protocol == 'netconf':
                params.update({
                    'filter': read_payload(getattr(self.args, "filter", "")),
                    'config': read_payload(getattr(self.args, "nc_config", "")),
                    'source': getattr(self.args, "source", "") or "running",
                    'target_datastore': getattr(self.args, "target_datastore", "candidate"),
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

            # For simplicity, there's only one type of RPC is allowed
            if len(t_sub_list): tgt_cnt += 1
            if len(t_get_list): tgt_cnt += 1
            if len(t_update_list) or len(t_replace_list) or len(t_delete_list): tgt_cnt += 1

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
                updates = t_update_list
                replaces = t_replace_list
                deletes = t_delete_list
                if isinstance(updates, str):
                    updates = [updates]
                if isinstance(replaces, str):
                    replaces = [replaces]
                if isinstance(deletes, str):
                    deletes = [deletes]

                session = create_session_config(
                    t_protocol,
                    'set',
                    target=str(target_ip_port), # Convert in case YAML parses IP as float/int
                    subscription_name=f'set-{time.time_ns()}',
                    prefix=tgt_info.get('prefix', ''),
                    operation='set',
                    encoding=tgt_info.get('encoding', 'json_ietf'),
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

def build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="gNMI Subscription Client")

    parser.add_argument('-g', '--global-config', default='', help='Path to YAML configuration file for this client')
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

    return parser.parse_args()

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
    parser_set = subparsers.add_parser('set', help="NETCONF <edit-config>")
    parser_set.add_argument('--target-datastore', default='candidate', help="Target datastore")
    parser_set.add_argument('--nc-config', required=True,
                            help="XML string or path to file. If given path not exists, consider it as a 'XML' formatted request")


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
    parser_set.add_argument('--update', action='append', help='Update path and value (format: path=value)')
    parser_set.add_argument('--replace', action='append', help='Replace path and value (format: path=value)')
    parser_set.add_argument('--delete', action='append', help='Delete path')

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
    if args.config != '':
        protocol = getattr(args, 'protocol', 'unknown')
        return FileConfigBuilder(args.config, protocol=protocol).build()
    else:
        return CLIConfigBuilder(args).build()