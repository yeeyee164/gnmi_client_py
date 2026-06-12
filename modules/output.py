# -*- encoding: utf-8 -*-
import sys
import json

class OutputHandler:
    """
    Consumes telemetry data and writes it to the configured destination.
    It will be used by the central manager class.

    For now, it only supports standard output or file.
    """

    def __init__(self, name, config):
        self.name = name
        self.type = config.get('type', 'file')
        self.file_type = config.get('file-type', 'stdout')
        self.format = config.get('format', 'json')
        
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
        if self.format == 'json':
            output_str = json.dumps(message, indent=2)
        else:
            output_str = str(message)
        
        self.stream.write(output_str + '\n')
        self.stream.flush()
    
    def close(self):
        """Safely closes file handles if they aren't standard system streams"""
        if self.stream not in (sys.stdout, sys.stderr):
            self.stream.close()
