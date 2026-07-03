from abc import ABC, abstractmethod

from modules.output import OutputHandler
from ui.cmd import ParsedConfig
from .gnmi_manager import UnaryManager, SubscriptionManager

class ManagerFactory:
    __unary_list = ['get', 'set', 'capabilities']
    _managers = {
        "unary" : UnaryManager,
        "subscribe" :  SubscriptionManager
    }

    @staticmethod
    def create_manager(operation: str, cfg: ParsedConfig):
        operation = operation.lower()
        if operation in ManagerFactory.__unary_list:
            mode = 'unary'
        else: mode = operation

        manager_class = ManagerFactory._managers.get(mode.lower())
        if not manager_class:
            raise ValueError(f'Unknown manager type: {mode}')
        
        # instantiating class
        if manager_class == UnaryManager:
            # Import unary workers lazily to avoid importing heavy deps at module import time
            try:
                from . import gnmi_unary_worker as guw
            except Exception as e:
                raise RuntimeError("Unary workers could not be imported. Ensure dependencies (pygnmi) are installed.") from e

            if operation == 'get':
                return manager_class(cfg, guw.GetWorker)
            elif operation == 'set':
                return manager_class(cfg, guw.SetWorker)
            elif operation == 'capabilities':
                return manager_class(cfg, guw.CapabilitiesWorker)
            else:
                raise ValueError(f'failed to pick a manager for operation: {operation}')
        elif manager_class == SubscriptionManager:
            return manager_class(cfg)
        else:
            raise ValueError(f'failed to pick a manager for operation: {operation}')


class BaseRPCManager(ABC):
    """
    Base class holding common utilities for all RPC Managers.

    For all managers which inherits this class, they should implement methods below:
    - run_all()
    - build_sessions()
    """

    def __init__(self, cfg: ParsedConfig):
        self.session_configs = cfg.sessions
        self.debug = cfg.debug
        self.outputs = cfg.outputs

        self.sessions = []           # Holds the GNMISubscribeSession objects
        self.output_handlers = []

        # Build output handlers once for all managers
        for out_name, out_cfg in self.outputs.items():
            self.output_handlers.append(OutputHandler(out_name, out_cfg))
    
    def shutdown(self):
        """Safely closes all output file handles"""
        for handler in self.output_handlers:
            handler.close()
        print("[Manager] Outputs cleanly closed. Goodbye!")

    @abstractmethod
    def build_sessions(self):
        """
            build_sessions builds up incoming sessions in injected `ParsedConfig` object. 
        """
        pass
    
    @abstractmethod
    def run_all(self):
        """
            run_all sets up RPC sessions which previously created by `build_sessions`.
        """
        pass