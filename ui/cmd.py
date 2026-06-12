# -*- encoding: utf-8 -*-
"""
    cmd.py

    `cmd.py` defines an user interface for the system command lines.
    It has a DataClass named `ParsedConfig` which 'normalized' information
    given by interfaces. 
"""
import argparse
import yaml
import json
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from abc import ABC, abstractmethod

@dataclass
class ParsedConfig:
    """
        For all classes defined in `cmd.py`, it eventually returns
        this class.

        And our management will use that for configure.
    """
    #global options
    targets: List[str]
    paths: List[str]

    # one of ONCE, POLL, STREAM
    mode: str

    # output methods - consists of {name: {type:, file-type:, format:}}
    outputs: Dict

    prefix: str = ""
    encoding: str = "json_ietf"
    username: str = ""
    password: str = ""
    update_only: bool = False
    debug: bool = False

    #spawn each target
    times: int = 1

    # one of SAMPLE, ON_CHANGE, TARGET_DEFINED
    sub_mode: Optional[str] = None

    # sample

    sample_interval: int = 90

    # on_change

    # target_defined

class ConfigBuilder(ABC):

    @abstractmethod
    def build(self):
        """Parse input and return `ParsedConfig` object"""
        pass

class CLIConfigBuilder(ConfigBuilder):
    def __init__(self, args):
        self.args = args
    
    def build(self):
        # check some arguments
        mode = self.args.mode
        update_only = getattr(self.args, "update_only", False)
        # manually creates a structure
        outputs = {
            'default_output':{
                'type': getattr(self.args, 'output_type', 'file'),
                'file-type': getattr(self.args, 'output_file_type', 'stdout'),
                'format': getattr(self.args, 'output_format', 'json'),
            }
        }
        times = self.args.times
        if times <= 0:
            print(f"[Config] times option should be positive integer. Ignore given value")
            times = 1

        return ParsedConfig(
            targets=self.args.targets,
            paths=self.args.paths,
            mode=mode,
            sub_mode=getattr(self.args, "sub_mode", None),
            times=times,
            prefix=self.args.prefix,
            encoding=self.args.encoding,
            username=self.args.username,
            password=self.args.password,
            sample_interval=getattr(self.args, "sample_interval", 90),
            update_only=update_only,
            debug=self.args.debug,
            outputs=outputs
        )

class FileConfigBuilder(ConfigBuilder):
    def __init__(self, path):
        self.path = path
    
        self.data = {}
        with open(path, 'r') as yfile:
            self.data = yaml.safe_load(yfile)
        
    def build(self):
        d = self.data

        # check validation
        times = d['times']
        if times <= 0:
            print(f"[Config] times option should be positive integer. Ignore given value")
            times = 1
        

        # manually creates a structure
        if 'outputs' not in d:
            outputs = {
                'default_output':{
                    'type': getattr(self.args, 'output_type', 'file'),
                    'file-type': getattr(self.args, 'output_file_type', 'stdout'),
                    'format': getattr(self.args, 'output_format', 'json'),
                }
            }
        else:
            outputs = d['outputs']

        return ParsedConfig(
            targets=d['targets'],
            paths=d['subscribe']['subscription']['paths'],
            mode=d['subscribe']['mode'],
            times=times,
            sub_mode=d['subscribe']['subscription'].get('mode', 'target_defined'),
            prefix=d.get('prefix', ''),
            encoding=d['encoding'],
            username=d.get('username', ''),
            password=d.get('password', ''),
            sample_interval=d['subscribe']['subscription'].get('sample_interval', 0),
            update_only=d['subscribe'].get('update_only', False),
            debug=d.get('debug', False),
            outputs=outputs
        )

def build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="gNMI Subscription Client")
    # global options

    parser.add_argument('-c', '--config', default='', help='Path to YAML configuration file')
    parser.add_argument('-t', '--targets', nargs='+',
                        help="List of targets in IP:PORT format (e.g. 10.0.0.1:12345 10.0.0.2:12324 ...)")
    parser.add_argument('--paths', nargs='+',
                        help="List of gNMI Paths (e.g. openconfig-interfaces:... openconfig-system:...)")
    parser.add_argument('-d', '--debug', help="Debugging this script", action='store_true')
    parser.add_argument('--times', default=1, type=int, help="Multiply targets")
    parser.add_argument('--username', default='', help="Username")
    parser.add_argument('--password', default='', help="Password")
    parser.add_argument('--prefix', default='', help="common prefix for all given paths")
    parser.add_argument('-e', '--encoding', default='json_ietf', help="encoding formats defined at gNMI")

    parser.add_argument('--output-type', default='file', help="Type of output data. Default is 'file'.")
    parser.add_argument('--output-file-type', default='stdout',
                        help="direction of output data. Default is 'stdout'.")
    parser.add_argument('--output-format', default='json', help="Specify output format. Default is 'json'")

    # Subscribe/custom mode

    subparsers = parser.add_subparsers(dest='mode', help="specify mode for STREAM mode of Subscribe RPC")

    # ONCE
    parser_once = subparsers.add_parser('once', help='subscribe ONCE mode')
    parser_once.add_argument('--update-only', help="if set true, it skips initial responses from server", action='store_true')

    # POLL
    parser_poll = subparsers.add_parser('poll', help='subscribe POLL mode')
    parser_poll.add_argument('--update-only', help="if set true, it skips initial responses from server", action='store_true')

    # Subscribe STREAM mode
    parser_stream = subparsers.add_parser('stream', help='subscribe STREAM mode')
    parser_stream.add_argument('--update-only', help="if set true, it skips initial responses from server", action='store_true')

    parser_stream.add_argument('--sub-mode', choices=['sample', 'on_change', 'target_defined'], default='sample', help='submode for STREAM mode')
    parser_stream.add_argument('--sample-interval', type=int, default=90, help='sample interval in seconds')

    return parser.parse_args()

def config_builder(args) -> ParsedConfig:
    """Build an appropriate `ParsedConfig` class by the contents of argument"""
    if args.config != '':
        return FileConfigBuilder(args.config).build()
    else:
        return CLIConfigBuilder(args).build()