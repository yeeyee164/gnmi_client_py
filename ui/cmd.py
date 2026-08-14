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
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from abc import ABC, abstractmethod

from modules.security import SecurityProfile

@dataclass
class SessionConfig:
    """
    Represents a specific subscription payload paired with a specific target.
    """
    target: str           # IP:PORT
    paths: List[str]      # List of gNMI paths
    subscription_name: str # For logging/tracking

    operation: str = "subscribe" # subscribe, get, set, capability
    mode: str = ""         # STREAM, ONCE, POLL

    # 'Global' options

    prefix: str = ""
    encoding: str = "json_ietf"
    username: str = ""
    password: str = ""
    update_only: bool = False
    times: int = 1
    insecure: bool = False
    protocol: str = "gnmi"

    # STREAM specific attributes
    sub_mode: Optional[str] = None
    sample_interval: int = 0

    # Set specific attributes

    # list of ('path', 'value')
    updates: list = field(default_factory=list)
    replaces: list = field(default_factory=list)

    # list of ('path')
    deletes: list = field(default_factory=list)

    def __str__(self):
        return f"""\t\tSessionConfig(target={self.target}, path={self.paths}, operation={self.operation}, mode={self.mode}, 
            subscription_name={self.subscription_name}, prefix={self.prefix}, encoding={self.encoding}, 
            username={self.username}, update_only={self.update_only}, insecure={self.insecure},
            times={self.times}, sub_mode={self.sub_mode}, sample_interval={self.sample_interval})"""


@dataclass
class ParsedConfig:
    """
        For all classes defined in `cmd.py`, it eventually returns
        this class.

        And our management will use that for configure.
    """
    sessions: List[SessionConfig] # List of all individual sessions to spawn
    outputs: Dict                 # Output definitions
    targets: List[str] = field(default_factory=list) # List of "IP:PORT" strings
    protocol: str = "gnmi"        # Northbound Protocol - default is gNMI
    insecure: bool = False        # Insecure connection
    debug: bool = False           # Global debug flag

    # security options
    security: SecurityProfile = field(default_factory=SecurityProfile)

    def __str__(self):
        session_strs = "\n".join([str(s) for s in self.sessions])
        return f"""ParsedConfig(debug={self.debug}, insecure={self.insecure},
    outputs={self.outputs}, protocol={self.protocol},
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
    
    def _parse_kv(self, kv_list):
        """
        Parse Set payload argument safely (path=value or path:::type:::value)
        """

        res = []
        if not kv_list: return res
        for item in kv_list:
            # extract the last element
            
            if ':::' in item:
                p, v = item.split(':::', 1)
            elif '=' in item:
                p, v = item.split('=', 1)
            else:
                #consider it as 'empty'
                p, v = item, ""
            
            # Attempt to parse values as JSON/bools/ints if applicable, else keep as string
            try:
                v = json.loads(v)
            except Exception:
                pass
                
            res.append((p, v))
        return res
    
    def build(self) -> ParsedConfig:
        # Check validation
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

        op_arg = self.args.operation
        global_op = 'subscribe' if op_arg in ['once', 'poll', 'stream'] else op_arg
        mode = self.args.mode if global_op == 'subscribe' else ""

        targets = self.args.target or []
        sessions = []

        # set default info
        prefix = ''
        if global_op in ('get', 'subscribe'):
            prefix = self.args.prefix

        updates, replaces, deletes = [], [], []
        if global_op == 'set':
            updates = self._parse_kv(getattr(self.args, 'update', []))
            replaces = self._parse_kv(getattr(self.args, 'replace', []))
            deletes = getattr(self.args, 'delete', [])
        
        if self.args.target:
            for target in targets:
                sessions.append(SessionConfig(
                    target=target,
                    paths=getattr(self.args, "path", []),
                    operation=global_op,
                    mode=mode,
                    subscription_name="cli_default",
                    prefix=prefix,
                    encoding=self.args.encoding,
                    username=self.args.username,
                    password=self.args.password,
                    insecure=self.args.insecure,
                    protocol=self.args.protocol,
                    update_only=getattr(self.args, "update_only", False),
                    times=times,
                    sub_mode=getattr(self.args, "sub_mode", None),
                    sample_interval=getattr(self.args, "sample_interval", 0),
                    updates=updates,
                    replaces=replaces,
                    deletes=deletes
                ))

        return ParsedConfig(
            sessions=sessions,
            outputs=outputs,
            targets=targets,
            debug=self.args.debug,
            insecure=self.args.insecure,
            protocol=self.args.protocol,
            security=SecurityProfile(
                tls_ca=getattr(self.args, "tls_ca", ""),
                tls_cert=getattr(self.args, "tls_cert", ""),
                tls_key=getattr(self.args, "tls_key", ""),
                skip_verify=getattr(self.args, "skip_verify", ""),
            ),
        )

class FileConfigBuilder(ConfigBuilder):
    def __init__(self, path):
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
        global_operation = d.get('operation', 'subscribe')
        global_username = d.get('username', '')
        global_password = d.get('password', '')
        global_encoding = d.get('encoding', 'json_ietf')
        global_protocol = d.get('protocol', 'gnmi').lower()
        global_times = d.get('times', 1)
        global_prefix = d.get('prefix', '')
        global_insecure = d.get('insecure', False)
        global_security = SecurityProfile(
            tls_ca=d.get('tls_ca', ''),
            tls_cert=d.get('tls_cert', ''),
            tls_key=d.get('tls_key', ''),
            skip_verify=d.get('skip_verify', False),
        )
        debug = d.get('debug', False)
        
        # Output parsing
        outputs = d.get('outputs', {
            'default_output': {
                'type': 'file',
                'file-type': 'stdout',
                'format': 'json'
            }
        })

        targets = []
        targets_list = []

        # --- PARSE NEW FORMAT (request_exp_named_sub.yaml) ---
        if global_operation == 'subscribe':
            if 'subscriptions' in d:
                targets_dict = d.get('targets', {})
                subs_dict = d.get('subscriptions', {})

                for target_ip_port, tgt_info in targets_dict.items():
                    targets.append(target_ip_port)
                    tgt_info = tgt_info or {} # Handle empty target blocks
                    
                    t_username = tgt_info.get('username', global_username)
                    t_password = tgt_info.get('password', global_password)
                    t_times = tgt_info.get('times', global_times)
                    t_update_only = tgt_info.get('update_only', False)

                    if t_times <= 0:
                        print(f"[Config] times option should be positive integer. Ignore given value")
                        t_times = 1

                    for sub_name in tgt_info.get('subscriptions', []):
                        if sub_name not in subs_dict:
                            print(f"[Config] Warning: Subscription '{sub_name}' not found. Skipping.")
                            continue
                        
                        sub_cfg = subs_dict[sub_name]
                        sub_details = sub_cfg.get('subscription', {})
                        
                        # Ensure paths is a list
                        paths = sub_details.get('path', [])
                        if isinstance(paths, str):
                            paths = [paths]

                        sessions.append(SessionConfig(
                            target=str(target_ip_port), # Convert in case YAML parses IP as float/int
                            paths=paths,
                            mode=sub_cfg.get('mode', 'stream'),
                            subscription_name=sub_name,
                            prefix=global_prefix,
                            encoding=sub_cfg.get('encoding', global_encoding),
                            protocol=sub_cfg.get('protocol', global_protocol),
                            insecure=sub_cfg.get('insecure', global_insecure),
                            username=t_username,
                            password=t_password,
                            update_only=t_update_only,
                            times=t_times,
                            sub_mode=sub_details.get('mode', 'target_defined'),
                            sample_interval=sub_details.get('sample_interval', 0)
                        ))

            # --- PARSE OLD FORMAT (request_exp.yaml) ---
            elif 'subscribe' in d:
                targets_list = d.get('targets', [])
                targets = targets_list
                sub_cfg = d.get('subscribe', {})
                sub_details = sub_cfg.get('subscription', {})
                
                t_times = global_times
                if t_times <= 0:
                    print(f"[Config] times option should be positive integer. Ignore given value")
                    t_times = 1

                for target_ip_port in targets_list:
                    sessions.append(SessionConfig(
                        target=str(target_ip_port),
                        paths=sub_details.get('path', []),
                        mode=sub_cfg.get('mode', 'stream'),
                        subscription_name="default_sub",
                        prefix=global_prefix,
                        encoding=global_encoding,
                        username=global_username,
                        password=global_password,
                        update_only=sub_cfg.get('update_only', False),
                        times=t_times,
                        sub_mode=sub_details.get('mode', 'target_defined'),
                        sample_interval=sub_details.get('sample_interval', 0)
                    ))

        elif global_operation in ['get', 'capability']:
            # Unary Operation for Get and Capabilities
            targets_list = d.get('targets', [])
            paths = d.get('path', [])

            for target_ip_port in targets_list:
                targets.append(str(target_ip_port))
                sessions.append(SessionConfig(
                    target=str(target_ip_port),
                    paths=paths,
                    operation=global_operation,
                    subscription_name=f"default_{global_operation}",
                    prefix=global_prefix,
                    encoding=global_encoding,
                    username=global_username,
                    password=global_password,
                    times=max(global_times, 1)
                ))

        elif global_operation == 'set':
            # Unary Operation for Set
            targets_list = d.get('targets', [])
            set_cfg = d.get('set', {})

            # list of ('path', 'value')
            updates = [(str(k), v) for k, v in set_cfg.get('update', {}).items()]
            replaces = [(str(k), v) for k, v in set_cfg.get('replace', {}).items()]

            # list of 'path'
            deletes = set_cfg.get('delete', [])

            for target_ip_port in targets_list:
                targets.append(str(target_ip_port))
                sessions.append(SessionConfig(
                    target=str(target_ip_port),
                    paths=paths,
                    operation=global_operation,
                    subscription_name=f"default_{global_operation}",
                    protocol=sub_cfg.get('protocol', global_protocol),
                    insecure=sub_cfg.get('insecure', global_insecure),
                    prefix=global_prefix,
                    encoding=global_encoding,
                    username=global_username,
                    password=global_password,
                    times=max(global_times, 1),
                    updates=updates,
                    replaces=replaces,
                    deletes=deletes
                ))

        return ParsedConfig(sessions=sessions, targets=targets,
                            outputs=outputs, debug=debug, insecure=global_insecure,
                            protocol=global_protocol, security=global_security)

def build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="gNMI Subscription Client")

    parser.add_argument('-c', '--config', default='', help='Path to YAML configuration file')
    parser.add_argument('-t', '--target', action='append', help="List of targets in IP:PORT format")
    parser.add_argument('-d', '--debug', help="Debugging this script", action='store_true')
    parser.add_argument('--times', default=1, type=int, help="Generate duplicated requests - only use for testing")
    parser.add_argument('--username', default='', help="Username")
    parser.add_argument('--password', default='', help="Password")
    parser.add_argument('-e', '--encoding', default='json_ietf',
                        help="encoding formats defined at gNMI", 
                        choices=['json', 'json_ietf', 'bytes', 'proto', 'ascii'])
    parser.add_argument('-i', '--insecure', action='store_true',
                        help="use insecure connection if set True")

    # output specifiers
    parser.add_argument('--output-type', default='file', help="Type of output data.")
    parser.add_argument('--output-file-type', default='stdout', help="direction of output data.")
    parser.add_argument('--output-format', default='json', help="Specify output format.")

    # security options
    parser.add_argument('--tls-ca', default='', help="Path to CA certificate")
    parser.add_argument('--tls-cert', default='', help="Path to client certificate")
    parser.add_argument('--tls-key', default='', help="Path to client private key")
    parser.add_argument('--skip-verify', action='store_true', help="Path to CA certificate")
    parser.add_argument('--tls-server-name', default='', help="sets the server name to be used when verifying the hostname on the returned certificates. If 'skip-verify' was set, this options is meaningless.")
    parser.add_argument('--tls-version', default='1.3', choices=['1.0','1.1','1.2','1.3'],
                         help="set TLS version. Default version is 1.3")

    # TODO: it SHOULD be subparser; because each protocol may have 
    # different arguments/methods
    parser.add_argument('-p', '--protocol', default='gnmi', choices=['gnmi', 'netconf', 'restconf'],
                        help="set Northbound Protocol client. Default is gNMI")

    # add gNMI parser
    gnmi_args(parser)

    return parser.parse_args()

def gnmi_args(parser: argparse.ArgumentParser):
    # Top-Level Operation Parser
    subparsers = parser.add_subparsers(dest='operation', help="specify gNMI RPC operation")

    # UNARY: Capabilities
    parser_cap = subparsers.add_parser('capability', help='execute CAPABILITIES RPC')
    
    # UNARY: Get
    parser_get = subparsers.add_parser('get', help='execute GET RPC')
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
        return FileConfigBuilder(args.config).build()
    else:
        return CLIConfigBuilder(args).build()