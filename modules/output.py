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
    * 'format': output format

    NOTE: It's not the encoding rule defined at protocol.
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
        sub_name = message.get('subscription_name', '')

        if isinstance(raw_data, Exception):
            self.stream.write(f"[Error] RPC '{message.get('rpc')}' on {message.get('target')}: {raw_data}\n")
            self.stream.flush()
            return

        if self.format in ['json', 'xml']:
            meta = {
                'source': message.get('target'),
            }

            if sub_name != '':
                meta['subscription_name'] = sub_name

            rpc = message.get('rpc')
            meta = {k: v for k, v in meta.items() if v is not None}

            if self.format == 'json':
                formatted_data = self.formatter.format_json(raw_data, rpc=rpc, meta=meta)
                output_str = json.dumps(formatted_data, indent=2)
            elif self.format == 'xml':
                formatted_data = self.formatter.format_xml(raw_data, rpc=rpc, meta=meta)
                output_str = formatted_data
        elif self.format == 'text':
            formatted_data = self.formatter.format_text(raw_data)
            output_str = f"\n--- [target: {message.get('target')}] ---\n{formatted_data}"
        else:
            output_str = str(message)

        self.stream.write(output_str + '\n')
        self.stream.flush()
    
    def close(self):
        """Safely closes file handles if they aren't standard system streams"""
        if self.stream not in (sys.stdout, sys.stderr):
            self.stream.close()
