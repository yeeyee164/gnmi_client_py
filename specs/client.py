import grpc
from typing import Iterator, Any, Optional
from abc import ABC, abstractmethod

# Assuming you generated these using grpc_tools.protoc
from specs.gnmi import gnmi_pb2, gnmi_pb2_grpc
from util.encoding import STR_TO_GNMI_ENCODING

class BaseClient(ABC):
    """
    Abstract Base Class for all Northbound Protocol Clients such as NETCONF, gNMI, RESTCONF...
    Establishes an unified interface so managers and workers can operate protocol-agnostically.

    NOTE: Since it can't fully define common methods, all participants may implement
         other RPCs using inheritance.
    """

    @staticmethod
    def __enter__(self):
        """Initializes connection of session context manager."""
        pass

    @abstractmethod
    def __exit__(self):
        """Safely tears down connection or session context manager"""
        pass

    @abstractmethod
    def capability(self) -> Any:
        pass

    @abstractmethod
    def get(self, paths: list, prefix: str = "", **kwargs) -> Any:
        """
        Executes a read/fetch operation
        Mapped to gNMI Get, NETCONF <get>/<get-config>, or RESTCONF GET
        """
        pass

    @abstractmethod
    def set(self, prefix: str="", updates: list=None, deletes: list=None, replaces: list=None, **kwargs) -> Any:
        """
        Executes a write/edit operation
        Mapped to gNMI Set, NETCONF <edit-config> or RESTCONF PUT/POST/DELETE
        """
        pass

    @abstractmethod
    def subscribe(self, request_iterator: Any) -> Iterator[Any]:
        """
        Executes a long-lived telemetry of event notification subscription stream.
        Mapped to gNMI Subscribe, NETCONF event notification, or RESTCONF SSE/Webhooks
        """
        pass

class GNMIClient(BaseClient):
    """
    A gNMI client that support gNMI Services.

    Designed to be used as a context manager (with ... as client:)
    * Part of requests were injected by Worker class
    * It don't need to check validation about path formats - they're already checked by worker.
    """
    def __init__(
            self,
            target: tuple,
            username: str = "",
            password: str = "",
            insecure: bool = False,
            encoding: str = "json_ietf",
            timeout: int = 5,
            grpc_option: list = None,
            credentials: dict = None,
            no_qos_marking: bool = False,
            **kwargs,
        ):
        self.target = f'{target[0]}:{target[1]}'
        self.metadata = [("username", username), ("password", password)]
        self.insecure = insecure
        self.encoding = encoding
        
        # gNMI typically expects credentials passed as 'username' and 'password' metadata
        if username and password:
            self.metadata = [
                ('username', username),
                ('password', password)
            ]
            
        self.channel = None
        self.stub = None

    def __enter__(self):
        """Initializes the gRPC channel and Stub when entering a 'with' block."""
        # For a production client, you would use grpc.secure_channel and pass TLS credentials here.

        if self.insecure:
            self.channel = grpc.insecure_channel(self.target)
        else:
            raise NotImplementedError("secure channel is TBD")
        self.stub = gnmi_pb2_grpc.gNMIStub(self.channel)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Safely tears down the HTTP/2 connection."""
        if self.channel:
            self.channel.close()

    def capabilities(self) -> gnmi_pb2.CapabilityResponse:
        """ Executes an Unary Capabilities RPC """
        request = gnmi_pb2.CapabilityRequest()
        
        # Call the stub directly. We pass the metadata for authentication.
        response = self.stub.Capabilities(request, metadata=self.metadata)
        return response

    def get(self, paths: list, prefix=None) -> gnmi_pb2.GetResponse:
        """ Executes an Unary Get RPC """
        request = gnmi_pb2.GetRequest(
            encoding=STR_TO_GNMI_ENCODING[self.encoding]
        )
        
        if prefix:
            request.prefix.CopyFrom(prefix)
            
        for p in paths:
            # We assume 'paths' here is a list of pre-parsed gnmi_pb2.Path objects
            # (which your modules.path.parse_path already creates!)
            path_elem = request.path.add()
            path_elem.CopyFrom(p)

        response = self.stub.Get(request, metadata=self.metadata)
        return response

    def set(self, prefix: str, updates: list, replaces: list, deletes: list) -> gnmi_pb2.SetResponse:
        """ Executes an Unary Set RPC """
        request = gnmi_pb2.SetRequest()

        if prefix:
            request.prefix.CopyFrom(prefix)

        # build three paths - update, replace and delete
        for path in (deletes or []):
            request.delete.append(path)

        # cosider each value as "(path, data)"
        for path, typed_val in (updates or []):
            update_obj = request.update.add()
            update_obj.path.CopyFrom(path)
            update_obj.val.CopyFrom(typed_val)

        # cosider each value as "(path, data)"
        for path, typed_val in (replaces or []):
            replace_obj = request.update.add()
            replace_obj.path.CopyFrom(path)
            replace_obj.val.CopyFrom(typed_val)

        response = self.stub.Set(request, metadata=self.metadata)
        return response

    def subscribe(self, request_iterator) -> Iterator[gnmi_pb2.SubscribeResponse]:
        """
        Executes a Bidirectional Streaming Subscribe RPC.
        Instead of a single request, it takes an Iterator (or Generator) of SubscribeRequests.
        """
        # The stub returns an iterator that continuously yields SubscribeResponses as they arrive
        response_stream = self.stub.Subscribe(request_iterator, metadata=self.metadata)
        return response_stream
