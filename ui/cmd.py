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
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from abc import ABC, abstractmethod

from modules.security import SecurityProfile
from util.utils import read_payload

class FileConfigError(Exception):
    """Custom exception raised when given config vlolates some criteria"""
    pass

@dataclass
class BaseSessionConfig:
    """
    Universal connection details shared across all protocols
    """

    target: str = ""
    subscription_name: str = "default"
    username: str = ""
    password: str = ""
    times: int = 1
    operation: str = ""
    protocol: str = "gnmi"
    security: SecurityProfile = field(default_factory=SecurityProfile)


@dataclass
class GNMISessionConfig(BaseSessionConfig):
    """
    GNMI-specific payload parameters

    fields
    ------
    - `target`: a string value which formatted as "IP:PORT"
    - `subscription_name`: name of subscription. Only for subscribe-like RPCs.
    - `username`, `password`: account information
    - `times`: duplicates this session. Only for testing.
    - `operation`: 
    - `protocol`: 
    - `security`: security parameters for `protocol`

    """

    paths: List[str] = field(default_factory=list)
    mode: str = ""
    prefix: str = ""
    encoding: str = "json_ietf"
    insecure: bool = False
    update_only: bool = False

    # Get specific attributes
    get_type: str = ""

    # STREAM specific attributes
    sub_mode: Optional[str] = None
    sample_interval: int = 0

    # Set specific attributes

    # list of ('path', 'value')
    updates: list = field(default_factory=list)
    replaces: list = field(default_factory=list)
    # list of ('path')
    deletes: list = field(default_factory=list)

    #TODO: may be we need to separate them per type of RPC...

@dataclass
class NetconfSessionConfig(BaseSessionConfig):
    """
    NETCONF-specific payload parameters

    fields
    ------
    - `target`: a string value which formatted as "IP:PORT"
    - `subscription_name`: name of subscription. Only for subscribe-like RPCs.
    - `username`, `password`: account information
    - `times`: duplicates this session. Only for testing.
    - `operation`: 
    - `protocol`: 
    - `security`: security parameters for `protocol`
    - source: data source of NETCONF target. one of <running>, <candidate>, <startup>(get-config), or empty value(get)
    - target_datastore: datastore for NETCONF.
    - filter: request subfilter formatted XML
    - config: request <rpc> for <config>
    """

    device: str = "default"

    # <get>, <get-config>
    nc_xpath: List[str] = field(default_factory=list)
    source: str = "running"
    target_datastore: str = "candidate"
    filter: str = ""
    config: str = ""

    # <get-schema>
    identifier: str = ''
    version: str = ''
    schema_format: str = 'yang'

    #TODO: may be we need to separate them per type of RPC...

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

            if protocol == 'gnmi':

                paths = getattr(self.args, 'path', [])
                if isinstance(paths, str):
                    paths = [paths]

                session = GNMISessionConfig(
                    target=target, protocol=protocol, operation=operation,
                    username=self.args.username, password=self.args.password,
                    security=security_profile, subscription_name="cli_execution",
                    insecure=getattr(self.args, 'insecure', False),
                    paths=paths,
                    prefix=getattr(self.args, "prefix", ""),
                    encoding=getattr(self.args, "encoding", "json_ietf"),
                    get_type=getattr(self.args, "type", ''),
                    mode=getattr(self.args, "mode", ""),
                    sub_mode=getattr(self.args, "sub_mode", ""),
                    sample_interval=getattr(self.args, "interval", 0),
                    update_only=getattr(self.args, "update_only", False),
                    updates=getattr(self.args, "updates", []),
                    replaces=getattr(self.args, "replaces", []),
                    deletes=getattr(self.args, "delete", []),
                )
            elif protocol == 'netconf':
                session = NetconfSessionConfig(
                    target=target, protocol=protocol, operation=operation,
                    username=self.args.username, password=self.args.password,
                    security=security_profile, subscription_name="cli_execution",
                    filter=read_payload(getattr(self.args, "filter", "")),
                    config=read_payload(getattr(self.args, "nc_config", "")),
                    source=getattr(self.args, "source", ""),
                    target_datastore=getattr(self.args, "target_datastore", "candidate"),
                    device=getattr(self.args, "device", "default"),
                    nc_xpath=getattr(self.args, "nc_xpath", []),
                    version=getattr(self.args, "version", ""),
                    identifier=getattr(self.args, "identifier", ""),
                    schema_format=getattr(self.args, "schema_format", "yang"),
                )
            else:
                raise ValueError(f"Unknown protocol: {protocol}")
            
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
            t_protocol = tgt_info.get('protocol', self.protocol)
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
                subs = d.get('subscriptions')
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

                    session = GNMISessionConfig(
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
                        # Subscribe options
                        mode=named_sub.get('mode', 'stream'),
                        update_only=update_only,
                        sub_mode=sub_mode,
                        sample_interval=sample_interval
                    )
            elif len(t_get_list): # Get
                paths = t_get_list
                if isinstance(paths, str):
                    paths = [paths]

                session = GNMISessionConfig(
                    target=str(target_ip_port), # Convert in case YAML parses IP as float/int
                    paths=paths,
                    subscription_name=f'get-{time.time_ns()}',
                    operation='get',
                    prefix=named_sub.get('prefix', ''),
                    encoding=named_sub.get('encoding', 'json_ietf'),
                    protocol=t_protocol,
                    insecure=t_insecure,
                    username=t_username,
                    password=t_password,
                    times=t_times,
                    security=global_security,
                    # Get options
                )
                
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

                session = GNMISessionConfig(
                    target=str(target_ip_port), # Convert in case YAML parses IP as float/int
                    subscription_name=f'set-{time.time_ns()}',
                    prefix=named_sub.get('prefix', ''),
                    operation='set',
                    encoding=named_sub.get('encoding', 'json_ietf'),
                    protocol=t_protocol,
                    insecure=t_insecure,
                    username=t_username,
                    password=t_password,
                    times=t_times,
                    security=global_security,
                    # Set options
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
    parser.add_argument('--username', default='', help="Username")
    parser.add_argument('--password', default='', help="Password")
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