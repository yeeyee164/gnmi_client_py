import time
import threading
import queue
import json
import concurrent.futures

from .gnmi_subscribe_session import GNMISubscribeSession
from ui.cmd import ParsedConfig
from .manager import BaseRPCManager

class SubscriptionManager(BaseRPCManager):
    """
    Orchestrates multiple GNMISubscribeSession workers using Python threading package.
    """

    def __init__(self, cfg: ParsedConfig):
        super().__init__(cfg)
        self.threads = []            # Holds the active Thread objects

        #common channel for worker results
        # this queue supports Locking mechanism
        self.data_queue = queue.Queue()

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

                    session = GNMISubscribeSession(
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
        
        for session in self.sessions:
            session.stop()
        # Give threads a moment to safely close their gRPC channels
        for t in self.threads:
            t.join(timeout=2) 

        self.shutdown()
            
        print("[Manager] All sessions cleanly terminated. Goodbye!")

class UnaryManager(BaseRPCManager):
    """
    Orchestrates Unary RPCs (Get, Set, Capabilities) using a ThreadPoolExecutor
    These tasks execute only once. It returns their data and exit.
    """

    def __init__(self, cfg: ParsedConfig, worker_class):
        super().__init__(cfg)
        # Injects GetWorker, SetWorker, etc...
        self.worker_class = worker_class

    def build_sessions(self):
        for sc in self.session_configs:
            try:
                ip, port = sc.target.split(':')
                session = self.worker_class(
                    target_ip=ip,
                    target_port=int(port),
                    paths=sc.paths,
                    encoding=sc.encoding,
                    username=sc.username,
                    password=sc.password,
                    prefix=sc.prefix
                )
                self.sessions.append(session)
            except ValueError:
                print(f"[Manager] Invalid target format '{sc.target}'. Expected IP:PORT")

    def run_all(self):
        self.build_sessions()
        if not self.sessions:
            print("[Manager] No valid sessions to start. Exiting.")
            return
        
        print(f"[Manager] Starting {len(self.sessions)} concurrent unary tasks...")

        # By using ThreadPoolExecutor, we can handle unary RPCs concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(len(self.sessions), 1)) as executor:
            future_to_session = {executor.submit(session.start): session for session in self.sessions}

            for future in concurrent.futures.as_completed(future_to_session):
                session = future_to_session[future]
                try:
                    # Retrieve the returned dictionary from the worker's start() method
                    result = future.result()
                    if result:
                        for handler in self.output_handlers:
                            handler.write(result)
                except Exception as exc:
                    print(f"[Worker {session.target_ip}] generated an exception: {exc}")
        self.shutdown()