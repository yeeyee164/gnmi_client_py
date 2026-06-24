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
        self.session_configs = cfg.sessions # list of SessionConfig
        self.debug = cfg.debug # debug flag
        self.outputs = cfg.outputs # output methods
        
        self.sessions = []           # Holds the GNMISession objects
        self.threads = []            # Holds the active Thread objects

        #common channel for worker results
        # this queue supports Locking mechanism
        self.data_queue = queue.Queue()
        self.output_handlers = []

    def build_sessions(self):
        """Parses the targets and instantiates the Worker objects."""
        for sc in self.session_configs:
            for _ in range(sc.times):
                try:
                    #TODO: support list-based config
                    ip, port = sc.target.split(':')

                    # Package STREAM-specific args and update-only flag
                    args = {
                        'sub_mode' : sc.sub_mode,
                        'sample_interval' : sc.sample_interval,
                        'update_only' : sc.update_only
                    }

                    session = GNMISession(
                        target_ip=ip,
                        target_port=int(port),
                        paths=sc.paths,
                        data_queue=self.data_queue,
                        mode = sc.mode,
                        encoding=sc.encoding,
                        username=sc.username,
                        password=sc.password,
                        prefix=sc.prefix,
                        subscription_name=sc.subscription_name,
                        **args)

                    self.sessions.append(session)
                except ValueError:
                    print(f"[Manager] Invalid target format '{sc.target}'. Expected IP:PORT.")
        
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