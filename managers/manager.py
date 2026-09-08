import time
import threading
import queue
import json
import concurrent.futures
import dataclasses
from typing import List, Optional, Tuple, Type

from managers.subscribe_session import SubscribeSession
from managers.unary_worker import BaseUnaryWorker, GetWorker, SetWorker, CapabilityWorker
from modules.output import OutputHandler
from ui.cmd import ParsedConfig, BaseSessionConfig

import logging

logger = logging.getLogger(__name__)

class BaseRPCManager:
    """
    Base class holding common utilities for all RPC Managers.
    """

    def __init__(
        self,
        sessions: Optional[List[BaseSessionConfig]] = None,
        output_handlers: Optional[List[OutputHandler]] = None,
        debug: bool = False,
        cfg: Optional[ParsedConfig] = None
    ):
        if cfg is not None:
            self.session_configs = sessions if sessions is not None else cfg.sessions
            self.debug = cfg.debug
            self.outputs = cfg.outputs
            if output_handlers is None:
                self.output_handlers = []
                proto = self.session_configs[0].protocol if self.session_configs else 'gnmi'
                for out_name, out_cfg in self.outputs.items():
                    out_cfg['protocol'] = proto
                    out_cfg['debug'] = self.debug
                    self.output_handlers.append(OutputHandler(out_name, out_cfg))
                self._owns_handlers = True
            else:
                self.output_handlers = output_handlers
                self._owns_handlers = False
        else:
            self.session_configs = sessions or []
            self.output_handlers = output_handlers or []
            self.debug = debug
            self.outputs = {}
            self._owns_handlers = False

        self.sessions = []  # Holds the worker/session objects

    def shutdown(self):
        """Safely closes output file handles only if manager created them itself"""
        if getattr(self, '_owns_handlers', False):
            for handler in self.output_handlers:
                handler.close()
            logger.info("[Manager] Outputs cleanly closed. Goodbye!")

class SubscriptionManager(BaseRPCManager):
    """
    Orchestrates multiple SubscribeSession workers using Python threading package.
    """

    def __init__(
        self,
        sessions: Optional[List[BaseSessionConfig]] = None,
        output_handlers: Optional[List[OutputHandler]] = None,
        debug: bool = False,
        cfg: Optional[ParsedConfig] = None
    ):
        super().__init__(sessions=sessions, output_handlers=output_handlers, debug=debug, cfg=cfg)
        self.threads = []            # Holds the active Thread objects

        # common channel for worker results
        # this queue supports Locking mechanism
        self.data_queue = queue.Queue()

    def build_sessions(self):
        """Parses the targets and instantiates the Worker objects."""
        for sc in self.session_configs:
            for _ in range(getattr(sc, 'times', 1)):
                session = SubscribeSession(
                    data_queue=self.data_queue,
                    config=sc
                )
                self.sessions.append(session)

    def run_all(self):
        """Spins up a background thread for each session and waits."""
        self.build_sessions()
        
        if not self.sessions:
            logger.error("[Manager] No valid sessions to start. Exiting.")
            return

        logger.info(f"[Manager] Starting {len(self.sessions)} concurrent sessions...")
        
        # Start a thread for every session
        for session in self.sessions:
            t = threading.Thread(target=session.start, daemon=True)
            self.threads.append(t)
            t.start()

        # run another thread to invoke Poll mechanism(gNMI)
        if any(s.kwargs.get('mode','').lower() == 'poll' for s in self.sessions):
            controller_t = threading.Thread(target=self._interactive_poll_controller, daemon=True)
            controller_t.start()

        # The Main Thread blocks here, keeping the script alive and watching for Ctrl+C
        try:
            while any(t.is_alive() for t in self.threads):
                try:
                    message = self.data_queue.get(timeout=1.0)

                    # Process and print the message safely in the main thread
                    logger.debug(f"\n--- [Telemetry from Session: {message['session_id']} | Target: {message['target']}] ---")

                    for handler in self.output_handlers:
                        handler.write(message)
                    
                    self.data_queue.task_done()
                except queue.Empty:
                    continue
        except KeyboardInterrupt:
            logger.info("\n[Manager] Ctrl+C Detected! Initiating graceful shutdown...")
        
        for session in self.sessions:
            session.stop()
        # Give threads a moment to safely close their gRPC channels
        for t in self.threads:
            t.join(timeout=2) 

        self.shutdown()
            
        logger.info("[Manager] All sessions cleanly terminated. Goodbye!")

    def _interactive_poll_controller(self):
        """A simple background CLI to allow users to trigger polls manually."""
        poll_sessions = [s for s in self.sessions if s.kwargs.get('mode','').lower() == 'poll']
        time.sleep(2) # Give streams a moment to connect
        
        # This is an interactive terminal session for POLL.
        # So no need to change to logger
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

    def __init__(
        self,
        sessions: Optional[List[BaseSessionConfig]] = None,
        output_handlers: Optional[List[OutputHandler]] = None,
        debug: bool = False,
        worker_class: Optional[Type[BaseUnaryWorker]] = None,
        cfg: Optional[ParsedConfig] = None
    ):
        # Support legacy UnaryManager(cfg, worker_class) signature
        if isinstance(sessions, ParsedConfig) and cfg is None:
            cfg = sessions
            sessions = None
        super().__init__(sessions=sessions, output_handlers=output_handlers, debug=debug, cfg=cfg)
        self.worker_class = worker_class

    def _resolve_worker(self, sc: BaseSessionConfig) -> BaseUnaryWorker:
        if self.worker_class is not None:
            return self.worker_class(config=sc)

        op = sc.operation.lower()
        if op in ['get', 'get-config', 'get-schema']:
            return GetWorker(config=sc)
        elif op in ['set', 'edit-config']:
            return SetWorker(config=sc)
        elif op == 'capability':
            return CapabilityWorker(config=sc)
        else:
            raise ValueError(f"Unsupported unary operation: {op}")

    def build_sessions(self):
        for sc in self.session_configs:
            for _ in range(getattr(sc, 'times', 1)):
                worker = self._resolve_worker(sc)
                self.sessions.append(worker)

    def run_all(self):
        self.build_sessions()
        if not self.sessions:
            logger.warning("[Manager] No valid sessions to start. Exiting.")
            return
        
        logger.info(f"[Manager] Starting {len(self.sessions)} concurrent unary tasks...")

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
                    worker_name = session.__class__.__name__
                    logger.error(f"[{worker_name} {session.target_ip}] generated an exception: {exc}")
        self.shutdown()

class ManagerFactory:
    """
    The main entry point for the execution engine.
    Routes the ParsedConfig to the appropriate protocol-agnostic manager based on the
    requested RPC.
    """

    UNARY_OPS = {'get', 'get-config', 'get-schema', 'set', 'edit-config', 'capability'}
    STREAM_OPS = {'subscribe', 'stream', 'once', 'poll'}

    @staticmethod
    def create_managers(cfg: ParsedConfig) -> Tuple[List[BaseRPCManager], List[OutputHandler]]:
        """
        Partitions sessions from ParsedConfig and instantiates the proper managers
        along with centralized OutputHandlers.
        """
        handlers = []
        default_proto = cfg.sessions[0].protocol if cfg.sessions else 'gnmi'
        for out_name, out_cfg in cfg.outputs.items():
            out_cfg['protocol'] = default_proto
            out_cfg['debug'] = cfg.debug
            handlers.append(OutputHandler(out_name, out_cfg))

        # Validate that all operations are supported
        all_known = ManagerFactory.UNARY_OPS | ManagerFactory.STREAM_OPS
        for s in cfg.sessions:
            if s.operation.lower() not in all_known:
                raise ValueError(f"failed to pick a manager for operation: {s.operation}")

        # Partition sessions strictly by operation type
        unary_sessions = [s for s in cfg.sessions if s.operation.lower() in ManagerFactory.UNARY_OPS]
        stream_sessions = [s for s in cfg.sessions if s.operation.lower() in ManagerFactory.STREAM_OPS]

        managers: List[BaseRPCManager] = []
        if unary_sessions:
            managers.append(UnaryManager(
                sessions=unary_sessions,
                output_handlers=handlers,
                debug=cfg.debug
            ))
        if stream_sessions:
            managers.append(SubscriptionManager(
                sessions=stream_sessions,
                output_handlers=handlers,
                debug=cfg.debug
            ))

        return managers, handlers

    @staticmethod
    def create_manager(cfg: ParsedConfig) -> List[BaseRPCManager]:
        """
        Backward-compatible method returning only the list of managers.
        """
        managers, _ = ManagerFactory.create_managers(cfg)
        return managers

    @staticmethod
    def execute(cfg: ParsedConfig):
        """
        Instantiates and executes managers for the given ParsedConfig with centralized output lifecycle.
        """
        managers, handlers = ManagerFactory.create_managers(cfg)
        try:
            for mgr in managers:
                mgr.run_all()
        finally:
            for handler in handlers:
                handler.close()

