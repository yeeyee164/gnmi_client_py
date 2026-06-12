import time
import threading
import queue
import json

from gnmi_subscribe_session import GNMISession
from modules.output import OutputHandler
from ui.cmd import ParsedConfig

class SubscriptionManager:
    """
    Orchestrates multiple GNMISession workers using Python threading package.
    """

    def __init__(self, cfg: ParsedConfig):
        """
            cfg: object of `ParsedConfig` class
        """
        self.targets = cfg.targets       # List of "IP:PORT"
        self.username = cfg.username
        self.password = cfg.password
        self.paths = cfg.paths           # List of paths
        self.mode = cfg.mode
        self.prefix = cfg.prefix
        self.encoding = cfg.encoding
        self.times = cfg.times

        self.outputs = cfg.outputs

        self.args = {
            'sub_mode': cfg.sub_mode,
            'sample_interval': cfg.sample_interval,
        }
        
        self.sessions = []           # Holds the GNMISession objects
        self.threads = []            # Holds the active Thread objects

        #common channel for worker results
        # this queue supports Locking mechanism
        self.data_queue = queue.Queue()
        self.output_handlers = []

    def build_sessions(self):
        """Parses the targets and instantiates the Worker objects."""
        for target_str in self.targets:
            for _ in range(self.times):
                try:
                    ip, port = target_str.split(':')
                    session = GNMISession(ip, int(port), self.paths, self.mode, self.data_queue,
                                        encoding=self.encoding, username=self.username,
                                        password=self.password, **self.args)

                    self.sessions.append(session)
                except ValueError:
                    print(f"[Manager] Invalid target format '{target_str}'. Expected IP:PORT.")
        
        # build output handlers
        for out_name, out_cfg in self.outputs.items():
            self.output_handlers.append(OutputHandler(out_name, out_cfg))

    def run_all(self):
        """Spins up a background thread for each session and waits."""
        self.build_sessions()
        
        if not self.sessions:
            print("[Manager] No valid sessions to start. Exiting.")
            return

        print(f"[Manager] Starting {len(self.sessions)} concurrent sessions...")
        
        # Start a thread for every session
        for session in self.sessions:
            t = threading.Thread(target=session.start, daemon=True)
            self.threads.append(t)
            t.start()

        # The Main Thread blocks here, keeping the script alive and watching for Ctrl+C
        try:
            while any(t.is_alive() for t in self.threads):
                try:
                    message = self.data_queue.get(timeout=1.0)

                    # Process and print the message safely in the main thread
                    # print(f"\n--- [Telemetry from Session: {message['session_id']} | Target: {message['target']}] ---")
                    # print(json.dumps(message['data'], indent=2))

                    for handler in self.output_handlers:
                        handler.write(message)
                    
                    self.data_queue.task_done()
                except queue.Empty:
                    continue
        except KeyboardInterrupt:
            print("\n[Manager] Ctrl+C Detected! Initiating graceful shutdown...")
            self.shutdown()

    def shutdown(self):
        """Tells all workers to stop and waits for them to close."""
        for session in self.sessions:
            session.stop()
            
        # Give threads a moment to safely close their gRPC channels
        for t in self.threads:
            t.join(timeout=2) 
        
        for handler in self.output_handlers:
            handler.close()
            
        print("[Manager] All sessions cleanly terminated. Goodbye!")