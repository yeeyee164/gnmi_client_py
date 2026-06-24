# -*- encoding: utf-8 -*-
"""
    cmd.py

    `cmd.py` defines a user interface for the system command lines.
    It has a DataClass named `ParsedConfig` which 'normalizes' information
    given by interfaces. 
"""
import argparse
import yaml
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from abc import ABC, abstractmethod

@dataclass
class SessionConfig:
    """
    Represents a specific subscription payload paired with a specific target.
    """
    target: str           # IP:PORT
    paths: List[str]      # List of gNMI paths
    mode: str             # STREAM, ONCE, POLL
    subscription_name: str # For logging/tracking
    
    prefix: str = ""
    encoding: str = "json_ietf"
    username: str = ""
    password: str = ""
    update_only: bool = False
    times: int = 1

    # STREAM specific attributes
    sub_mode: Optional[str] = None
    sample_interval: int = 90

    def __str__(self):
        return f"SessionConfig(target={self.target}, paths={self.paths}, mode={self.mode}, subscription_name={self.subscription_name}, prefix={self.prefix}, encoding={self.encoding}, username={self.username}, update_only={self.update_only}, times={self.times}, sub_mode={self.sub_mode}, sample_interval={self.sample_interval})"


@dataclass
class ParsedConfig:
    """
        For all classes defined in `cmd.py`, it eventually returns
        this class.

        And our management will use that for configure.
    """
    sessions: List[SessionConfig] # List of all individual sessions to spawn
    outputs: Dict                 # Output definitions
    targets: list[str] = field(default_factory=list) # List of "IP:PORT" strings
    debug: bool = False           # Global debug flag

    def __str__(self):
        session_strs = "\n".join([str(s) for s in self.sessions])
        return f"ParsedConfig(debug={self.debug}, outputs={self.outputs}, sessions=[\n{session_strs}\n])"

class ConfigBuilder(ABC):
    @abstractmethod
    def build(self) -> ParsedConfig:
        """Parse input and return `ParsedConfig` object"""
        pass

class CLIConfigBuilder(ConfigBuilder):
    def __init__(self, args):
        self.args = args
    
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

        targets = self.args.target or []

        sessions = []
        if self.args.target and self.args.path:
            for target in targets:
                sessions.append(SessionConfig(
                    target=target,
                    paths=self.args.path,
                    mode=self.args.mode,
                    subscription_name="cli_default",
                    prefix=self.args.prefix,
                    encoding=self.args.encoding,
                    username=self.args.username,
                    password=self.args.password,
                    update_only=getattr(self.args, "update_only", False),
                    times=times,
                    sub_mode=getattr(self.args, "sub_mode", None),
                    sample_interval=getattr(self.args, "sample_interval", 90)
                ))

        return ParsedConfig(
            sessions=sessions,
            outputs=outputs,
            targets=targets,
            debug=self.args.debug
        )

class FileConfigBuilder(ConfigBuilder):
    def __init__(self, path):
        self.path = path
        self.data = {}
        with open(path, 'r') as yfile:
            self.data = yaml.safe_load(yfile)
        
    def build(self) -> ParsedConfig:
        d = self.data
        sessions = []

        # Global fallbacks
        global_username = d.get('username', '')
        global_password = d.get('password', '')
        global_encoding = d.get('encoding', 'json_ietf')
        global_times = d.get('times', 1)
        global_prefix = d.get('prefix', '')
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
        # --- PARSE NEW FORMAT (request_exp_named_sub.yaml) ---
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
                        username=t_username,
                        password=t_password,
                        update_only=t_update_only,
                        times=t_times,
                        sub_mode=sub_details.get('mode', 'target_defined'),
                        sample_interval=sub_details.get('sample_interval', 90)
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
                    paths=sub_details.get('paths', []),
                    mode=sub_cfg.get('mode', 'stream'),
                    subscription_name="default_sub",
                    prefix=global_prefix,
                    encoding=global_encoding,
                    username=global_username,
                    password=global_password,
                    update_only=sub_cfg.get('update_only', False),
                    times=t_times,
                    sub_mode=sub_details.get('mode', 'target_defined'),
                    sample_interval=sub_details.get('sample_interval', 90)
                ))

        return ParsedConfig(sessions=sessions, targets=targets, outputs=outputs, debug=debug)

def build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="gNMI Subscription Client")

    parser.add_argument('-c', '--config', default='', help='Path to YAML configuration file')
    parser.add_argument('-t', '--target', action='append', help="List of targets in IP:PORT format")
    parser.add_argument('--path', action='append', help="List of gNMI Paths")
    parser.add_argument('-d', '--debug', help="Debugging this script", action='store_true')
    parser.add_argument('--times', default=1, type=int, help="Multiply targets")
    parser.add_argument('--username', default='', help="Username")
    parser.add_argument('--password', default='', help="Password")
    parser.add_argument('--prefix', default='', help="common prefix for all given paths")
    parser.add_argument('-e', '--encoding', default='json_ietf',
                        help="encoding formats defined at gNMI", 
                        choices=['json', 'json_ietf', 'bytes', 'proto'])

    parser.add_argument('--output-type', default='file', help="Type of output data.")
    parser.add_argument('--output-file-type', default='stdout', help="direction of output data.")
    parser.add_argument('--output-format', default='json', help="Specify output format.")

    subparsers = parser.add_subparsers(dest='mode', help="specify mode for STREAM mode of Subscribe RPC")

    # ONCE
    parser_once = subparsers.add_parser('once', help='subscribe ONCE mode')
    parser_once.add_argument('--update-only', help="skip initial responses from server", action='store_true')

    # POLL
    parser_poll = subparsers.add_parser('poll', help='subscribe POLL mode')
    parser_poll.add_argument('--update-only', help="skip initial responses from server", action='store_true')

    # STREAM
    parser_stream = subparsers.add_parser('stream', help='subscribe STREAM mode')
    parser_stream.add_argument('--update-only', help="skip initial responses from server", action='store_true')
    parser_stream.add_argument('--sub-mode', choices=['sample', 'on_change', 'target_defined'], default='sample')
    parser_stream.add_argument('--sample-interval', type=int, default=90, help='sample interval in seconds')

    return parser.parse_args()

def config_builder(args) -> ParsedConfig:
    """Build an appropriate `ParsedConfig` class by the contents of argument"""
    if args.config != '':
        return FileConfigBuilder(args.config).build()
    else:
        return CLIConfigBuilder(args).build()