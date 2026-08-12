import time
import threading
import queue
import json
import concurrent.futures

from managers.gnmi_subscribe_session import GNMISession
from managers.gnmi_unary_worker import GetWorker, SetWorker, CapabilityWorker
from modules.output import OutputHandler
from ui.cmd import ParsedConfig


class BaseRPCManager:
    """
    Base class holding common utilities for all RPC Managers.
    """

    def __init__(self, cfg: ParsedConfig):
        self.session_configs = cfg.sessions
        self.debug = cfg.debug
        self.outputs = cfg.outputs

        self.sessions = [] # Holds the GNMISubscribeSession objects
        self.output_handlers = []

        # Build output handlers once for all managers
        for out_name, out_cfg in self.outputs.items():
            out_cfg['protocol'] = self.session_configs[0].protocol if self.session_configs else 'gnmi'
            out_cfg['debug'] = self.debug
            self.output_handlers.append(OutputHandler(out_name, out_cfg))
    
    def shutdown(self):
        """Safely closes all output file handles"""
        for handler in self.output_handlers:
            handler.close()
        print("[Manager] Outputs cleanly closed. Goodbye!")

class SubscriptionManager(BaseRPCManager):
    """
    Orchestrates multiple SubscribeSession workers using Python threading package.
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
                        'update_only' : sc.update_only,
                        'insecure': sc.insecure
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
                        debug=self.debug,
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

        if any(s.mode.lower() == 'poll' for s in self.sessions):
            controller_t = threading.Thread(target=self._interactive_poll_controller, daemon=True)
            controller_t.start()

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

    def _interactive_poll_controller(self):
        """A simple background CLI to allow users to trigger polls manually."""
        poll_sessions = [s for s in self.sessions if s.mode.lower() == 'poll']
        time.sleep(2) # Give streams a moment to connect
        
        while True:
            print("\n" + "="*40)
            print(" Interactive POLL Controller")
            print("="*40)
            for idx, s in enumerate(poll_sessions):
                print(f"  [{idx}] {s.session_id} - {s.target_ip} ({s.subscription_name})")
            
            try:
                choice = input("\nType a session index to trigger, 'all', or press Enter to refresh: ").strip().lower()
                if choice == 'all':
                    for s in poll_sessions:
                        s.trigger_poll()
                        print(f"-> Sent POLL to {s.session_id}")
                elif choice.isdigit():
                    idx = int(choice)
                    if 0 <= idx < len(poll_sessions):
                        poll_sessions[idx].trigger_poll()
                        print(f"-> Sent POLL to {poll_sessions[idx].session_id}")
                    else:
                        print("Invalid index.")
            except EOFError:
                break
            except KeyboardInterrupt:
                break       

class UnaryManager(BaseRPCManager):
    """
    Orchestrates RPCs except specific session-required using a ThreadPoolExecutor
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
                    target_ip=ip, target_port=int(port), paths=sc.paths, 
                    encoding=sc.encoding, username=sc.username, password=sc.password,
                    insecure=sc.insecure,
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
                    print(f"[Worker({str(self.worker_class)}) {session.target_ip}] generated an exception: {exc}")
        self.shutdown()

class ManagerFactory:
    """
    The main entry point for the execution engine.
    Routes the ParsedConfig to the appropriate protocol-agnostic manager based ont he
    requested RPC.
    """

    @staticmethod
    def execute(cfg: ParsedConfig):
        """
        By calling this class method, you can instantiate Northbound Protocol clients in place.
        
        Currently, only gNMI is supported.
        """
        for mgr in ManagerFactory.create_manager(cfg):
            mgr.run_all()


    @staticmethod
    def create_manager(cfg: ParsedConfig):
        managers = []
        # Let's create managers for each SessionConfig
        for sc in cfg.sessions:
            op = sc.operation

            if op in ['subscribe', 'stream', 'once', 'poll']:
                manager = SubscriptionManager(cfg=cfg)
            elif op == 'get':
                manager = UnaryManager(cfg, GetWorker)
            elif op == 'set':
                manager =  UnaryManager(cfg, SetWorker)
            elif op == 'capability':
                manager = UnaryManager(cfg, CapabilityWorker)
            else:
                raise ValueError(f'failed to pick a manager for operation: {op}')
            managers.append(manager)

        return managers

