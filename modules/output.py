# -*- encoding: utf-8 -*-
import sys
import json

from modules.formatter import GNMIFormatter, NETCONFFormatter

class OutputHandler:
    """
    Consumes telemetry data and writes it to the configured destination.
    It will be used by the central manager class.

    Incoming data should be typed 'dictionary'. It should contain such fields:
    * 'data': base64 formatted response result
    * 'protocol': which protocol used for response
    * 'rpc': supported RPC for 'protocol'

    For now, it only supports standard output or file.

    Supported formats:
    ------------------
    
    **gNMI**
        * json, json_ietf, ascii
    """

    def __init__(self, name, config):
        self.name = name
        self.type = config.get('type', 'file')
        self.file_type = config.get('file-type', 'stdout')
        self.format = config.get('format', 'json').lower()

        # Select protocol
        self.protocol = config.get('protocol', 'gnmi').lower()

        # Instantiate protocol formatter
        if self.protocol == 'netconf':
            self.formatter = NETCONFFormatter()
        else: # default is gNMI
            self.formatter = GNMIFormatter()
        
        # Determine the output stream
        if self.file_type == 'stdout':
            self.stream = sys.stdout
        elif self.file_type == 'stderr':
            self.stream = sys.stderr
        else:
            # If it's not stdout/stderr, treat it as a file path
            self.stream = open(self.file_type, 'a')
            print(f"[Output] Created file sink: {self.file_type}")

    def write(self, message):
        """Formats and writes the message to the defined stream"""
        raw_data = message.get('data')

        if self.format in ['json', 'json_ietf']:
            meta = {
                'source': message.get('target'),
                'subscription-name': message.get('subscription_name', 'none'),
            }
            rpc = message.get('rpc')
            meta = {k: v for k, v in meta.items() if v is not None}

            formatted_data = self.formatter.format_json(raw_data, rpc=rpc, meta=meta)

            output_str = json.dumps(formatted_data, indent=2)
        elif self.format == 'ascii':
            formatted_data = self.formatter.format_ascii(raw_data)
            output_str = f"\n--- [{message.get('target')}] ---\n{formatted_data}"
        else:
            output_str = str(message)

        self.stream.write(output_str + '\n')
        self.stream.flush()
    
    def close(self):
        """Safely closes file handles if they aren't standard system streams"""
        if self.stream not in (sys.stdout, sys.stderr):
            self.stream.close()
