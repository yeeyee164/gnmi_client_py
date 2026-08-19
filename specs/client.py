import grpc
from typing import Iterator, Any, Optional
from abc import ABC, abstractmethod

# Assuming you generated these using grpc_tools.protoc
from specs.gnmi import gnmi_pb2, gnmi_pb2_grpc
from modules.path import parse_path
from modules.security import SecurityModule

#define some global variables
NANOSECOND = 1000000000

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
            target: str,
            username: str = "",
            password: str = "",
            **kwargs,
        ):
        self.target = target
        self.metadata = [("username", username), ("password", password)]
        # gNMI typically expects credentials passed as 'username' and 'password' metadata
        if username and password:
            self.metadata = [
                ('username', username),
                ('password', password)
            ]

        # Configure from keyward arguments
        self.insecure = kwargs.get('insecure', False)
        self.security = kwargs.get('security', None)
        self.encoding = kwargs.get('encoding', "json_ietf")
        self.debug = kwargs.get('debug', False)

        self.encoding_map = {
            'json': gnmi_pb2.JSON,
            'json_ietf': gnmi_pb2.JSON_IETF,
            'bytes': gnmi_pb2.BYTES,
            'proto': gnmi_pb2.PROTO,
            'ascii': gnmi_pb2.ASCII,
        }

        self.channel = None # a channel between this class and gRPC handler
        self.stub = None # gRPC client stub object. Stub will use channel above

    def __enter__(self):
        """Initializes the gRPC channel and Stub when entering a 'with' block."""
        # For a production client, you would use grpc.secure_channel and pass TLS credentials here.

        if self.insecure:
            self.channel = grpc.insecure_channel(self.target)
        elif self.security is not None:
            # create a TLS-based secure communication
            # tls_profile = TLSProfile(profile=self.security)
            creds = self.security.get_grpc_credentials()
            options = self.security.get_grpc_options()

            # set additional options
            self.channel = grpc.secure_channel(self.target, creds, options=options)
        else:
            raise NotImplementedError("present security information or run insecure mode")

        self.stub = gnmi_pb2_grpc.gNMIStub(self.channel)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Safely tears down the HTTP/2 connection."""
        if self.channel:
            self.channel.close()

    def capability(self) -> gnmi_pb2.CapabilityResponse:
        """ Executes an Unary Capabilities RPC """
        request = gnmi_pb2.CapabilityRequest()
        
        # Call the stub directly. We pass the metadata for authentication.
        response = self.stub.Capabilities(request, metadata=self.metadata)
        return response

    def get(self, paths: list, prefix=None, **kwargs) -> gnmi_pb2.GetResponse:
        """ Executes an Unary Get RPC """
        request = gnmi_pb2.GetRequest(
            encoding=self.encoding_map[self.encoding]
        )
        
        if prefix:
            request.prefix.CopyFrom(parse_path(prefix))
            
        # 'paths' is list of strings
        for p in paths:
            # (which your modules.path.parse_path already creates!)
            path_elem = request.path.add()
            path_elem.CopyFrom(parse_path(p))

        response = self.stub.Get(request, metadata=self.metadata)
        return response

    def set(self, prefix: str, updates: list, replaces: list, deletes: list) -> gnmi_pb2.SetResponse:
        """ Executes an Unary Set RPC """
        request = gnmi_pb2.SetRequest()

        if prefix:
            request.prefix.CopyFrom(parse_path(prefix))

        # build three paths - update, replace and delete
        for path in (deletes or []):
            request.delete.append(parse_path(path))

        # cosider each value as "(path, data)"
        for path, typed_val in (updates or []):
            update_obj = request.update.add()
            update_obj.path.CopyFrom(parse_path(path))
            update_obj.val.CopyFrom(typed_val)

        # cosider each value as "(path, data)"
        for path, typed_val in (replaces or []):
            replace_obj = request.update.add()
            replace_obj.path.CopyFrom(parse_path(path))
            replace_obj.val.CopyFrom(typed_val)

        response = self.stub.Set(request, metadata=self.metadata)
        return response

    def _build_subscribe_request(self, config: dict) -> gnmi_pb2.SubscribeRequest:
        """ Constructs the SubscribeRequest object """
        sub_list = gnmi_pb2.SubscriptionList()
        mode = config.get('mode', 'stream').lower()

        # determine mode
        if mode == 'once':
            sub_list.mode = gnmi_pb2.SubscriptionList.ONCE
        elif mode == 'poll':
            sub_list.mode = gnmi_pb2.SubscriptionList.POLL
        else:
            sub_list.mode = gnmi_pb2.SubscriptionList.STREAM

        # determine encoding        
        sub_list.encoding = self.encoding_map[self.encoding]
        sub_list.updates_only = config.get('updates_only', False)

        prefix = config.get('prefix', '')
        if prefix: sub_list.prefix.CopyFrom(parse_path(prefix))

        # build individual subscriptions
        for path_obj in config.get('paths', []):
            sub = sub_list.subscription.add()
            sub.path.CopyFrom(parse_path(path_obj))

            if mode == 'stream':
                smode = config.get('sub_mode', 'sample').lower()
                if smode == 'sample':
                    sub.mode = gnmi_pb2.SubscriptionMode.SAMPLE
                    sub.sample_interval = config.get('sample_interval', 0) * NANOSECOND
                elif smode == 'on_change':
                    sub.mode = gnmi_pb2.SubscriptionMode.ON_CHANGE
                else:
                    sub.mode = gnmi_pb2.SubscriptionMode.TARGET_DEFINED

        request = gnmi_pb2.SubscribeRequest(subscribe=sub_list)
        return request

    def subscribe(self, request_iterator) -> Iterator[gnmi_pb2.SubscribeResponse]:
        """
        Executes a Bidirectional Streaming Subscribe RPC.
        Instead of a single request, it takes an Iterator (or Generator) of SubscribeRequests.
        """

        def pb_generator():
            try:
                for req in request_iterator:
                    if req.get('action') == 'subscribe':
                        yield self._build_subscribe_request(req)
                    elif req.get('action') == 'poll':
                        poll_req = gnmi_pb2.SubscribeRequest()
                        poll_req.poll.SetInParent()
                        yield poll_req
            except Exception as e:
                print(f"[Client error] Exception in pb_generator: {e}")
                if self.debug:
                    import traceback
                    traceback.print_exc()
                raise

        # The stub returns an iterator that continuously yields SubscribeResponses as they arrive
        return self.stub.Subscribe(pb_generator(), metadata=self.metadata)

from ncclient import manager
class NetconfClient(BaseClient):
    """
    A "Lite" NETCONF Client utilizing ncclient.
    Currently accepts raw XPath strings for its paths.
    Future versions will utilize libyang to translate standard paths to XML Subtrees.
    """
    def __init__(self, target: str, username: str = "", password: str = "", **kwargs):
        self.target = target
        self.username = username
        self.password = password
        self.session = None

        # unwind kwargs
        self.security = kwargs.get('security', None)

    def __enter__(self):
        host, port = self.target.split(':')
        
        # Default SSH connection kwargs
        netconf_info = {
            'host': host,
            'port': int(port),
            'username': self.username,
            'password': self.password,
            'hostkey_verify': False  # Allow unknown SSH host keys for testing
        }

        # Inject SSH Keys from the Security Module if provided
        if self.security:
            ssh_kwargs = self.security.get_ssh_kwargs()
            if ssh_kwargs:
                netconf_info.update(ssh_kwargs)

        self.session = manager.connect(**netconf_info)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            self.session.close_session()

    def capabilities(self) -> Any:
        return list(self.session.server_capabilities)

    def get(self, paths: list, prefix: str = "", **kwargs) -> Any:
        """
        Executes a NETCONF <get>.
        In this 'lite' version, we assume `paths` is a list of raw XPath strings.
        We combine them into an XPath union filter.
        """
        if not paths:
            return self.session.get()
            
        # Combine multiple XPath requests using the union '|' operator
        xpath_filter = " | ".join(paths)
        filter_xml = f"""<filter type="xpath" select="{xpath_filter}"/>"""
        
        return self.session.get(filter=filter_xml)

    def set(self, updates: list = None, replaces: list = None, deletes: list = None, **kwargs) -> Any:
        """
        Executes a NETCONF <edit-config>.
        A 'lite' implementation requires raw XML strings from the user.
        (Will be replaced by libyang automated payload generation later).
        """
        # Placeholder for lite implementation. 
        # Advanced edit-config requires strict XML namespacing.
        raise NotImplementedError("NETCONF Set/Edit-Config is awaiting libyang integration.")

    def subscribe(self, request_iterator: Any) -> Iterator[Any]:
        """
        Executes NETCONF Event Notifications (RFC 5277).
        """
        self.session.create_subscription()
        
        # Generator pattern yielding notifications as they arrive
        while True:
            notif = self.session.take_notification(block=True)
            if notif:
                yield notif