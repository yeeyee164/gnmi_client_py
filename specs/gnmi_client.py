from __future__ import annotations
import os
import json
import logging
from typing import Iterator, Any, Optional

try:
    import grpc
    from specs.gnmi import gnmi_pb2, gnmi_pb2_grpc
except ImportError:
    grpc = None
    gnmi_pb2 = None
    gnmi_pb2_grpc = None

from specs.base_client import BaseClient
from modules.path import parse_path
from modules.security import SecurityModule
from config.operations import (
    CapabilitiesOperation,
    GetOperation,
    SetOperation,
    SubscribeOperation,
    ChangeType,
)
from config.selectors import PathSelector
from config.delivery import DeliveryMode
from config.protocol_options.gnmi import GNMIOptions

NANOSECOND = 1000000000

logger = logging.getLogger(__name__)

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
            security_module=None,
            **kwargs,
        ):
        self.target = target
        self.metadata = [("username", username), ("password", password)]
        if username and password:
            self.metadata = [
                ('username', username),
                ('password', password)
            ]

        # Configure from keyword arguments
        self.insecure = kwargs.get('insecure', False)
        self.security_module = security_module
        self.encoding = kwargs.get('encoding', "json_ietf")
        self.debug = kwargs.get('debug', False)

        self.encoding_map = {
            'json': gnmi_pb2.JSON if gnmi_pb2 else 0,
            'json_ietf': gnmi_pb2.JSON_IETF if gnmi_pb2 else 4,
            'bytes': gnmi_pb2.BYTES if gnmi_pb2 else 1,
            'proto': gnmi_pb2.PROTO if gnmi_pb2 else 2,
            'ascii': gnmi_pb2.ASCII if gnmi_pb2 else 3,
        }

        self.channel = None
        self.stub = None

    def __enter__(self):
        """Initializes the gRPC channel and Stub when entering a 'with' block."""
        if self.insecure:
            self.channel = grpc.insecure_channel(self.target)
        elif self.security_module is not None:
            creds = self.security_module.get_grpc_credentials()
            options = self.security_module.get_grpc_options()
            self.channel = grpc.secure_channel(self.target, creds, options=options)
        else:
            raise NotImplementedError("present security information or run insecure mode")

        self.stub = gnmi_pb2_grpc.gNMIStub(self.channel)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Safely tears down the HTTP/2 connection."""
        if self.channel:
            self.channel.close()

    # =========================================================================
    # Semantic Intent Operations
    # =========================================================================

    def execute_capabilities(self, operation: CapabilitiesOperation) -> gnmi_pb2.CapabilityResponse:
        """Executes Capabilities RPC adhering to CapabilitiesOperation."""
        return self.capability()

    def execute_get(self, operation: GetOperation) -> gnmi_pb2.GetResponse:
        """Executes Get RPC adhering to GetOperation."""
        paths = []
        prefix = ""
        if isinstance(operation.selector, PathSelector):
            paths = list(operation.selector.paths)
            prefix = operation.selector.prefix

        enc = self.encoding
        if isinstance(operation.protocol_options, GNMIOptions) and operation.protocol_options.encoding:
            enc = operation.protocol_options.encoding

        data_type = operation.read_scope or "all"
        return self.get(paths=paths, prefix=prefix, encoding=enc, data_type=data_type)

    def execute_set(self, operation: SetOperation) -> gnmi_pb2.SetResponse:
        """Executes Set RPC adhering to SetOperation and atomic Change models."""
        updates = []
        replaces = []
        deletes = []

        for change in operation.changes:
            if change.operation == ChangeType.MERGE:
                updates.append((change.path, change.value))
            elif change.operation == ChangeType.REPLACE:
                replaces.append((change.path, change.value))
            elif change.operation == ChangeType.DELETE:
                deletes.append(change.path)

        prefix = getattr(operation, 'prefix', '')
        enc = self.encoding
        if isinstance(operation.protocol_options, GNMIOptions):
            if operation.protocol_options.encoding:
                enc = operation.protocol_options.encoding

        return self.set(updates=updates, replaces=replaces, deletes=deletes, prefix=prefix, encoding=enc)

    def execute_subscribe(self, operation: SubscribeOperation) -> Iterator[gnmi_pb2.SubscribeResponse]:
        """Executes Subscribe RPC adhering to SubscribeOperation."""
        paths = []
        prefix = ""
        if isinstance(operation.selector, PathSelector):
            paths = list(operation.selector.paths)
            prefix = operation.selector.prefix

        mode_map = {
            DeliveryMode.PERIODIC: 'stream',
            DeliveryMode.ON_CHANGE: 'stream',
            DeliveryMode.SNAPSHOT: 'once',
            DeliveryMode.POLL: 'poll',
        }
        stream_mode_map = {
            DeliveryMode.PERIODIC: 'sample',
            DeliveryMode.ON_CHANGE: 'on_change',
            DeliveryMode.SNAPSHOT: 'sample',
            DeliveryMode.POLL: 'sample',
        }

        d_mode = operation.delivery.mode
        req_mode = mode_map.get(d_mode, 'stream')
        stream_mode = stream_mode_map.get(d_mode, 'sample')

        enc = self.encoding
        updates_only = False
        if isinstance(operation.protocol_options, GNMIOptions):
            if operation.protocol_options.encoding:
                enc = operation.protocol_options.encoding
            updates_only = operation.protocol_options.updates_only

        req_dict = {
            'action': 'subscribe',
            'operation': 'subscribe',
            'mode': req_mode,
            'stream_mode': stream_mode,
            'sub_mode': stream_mode,
            'paths': paths,
            'prefix': prefix,
            'sample_interval': operation.delivery.interval,
            'heartbeat_interval': operation.delivery.heartbeat,
            'suppress_redundant': operation.delivery.suppress_redundant,
            'encoding': enc,
            'updates_only': updates_only,
        }

        def single_req_gen():
            yield req_dict

        return self.subscribe(single_req_gen())

    # =========================================================================
    # Legacy Methods & Internal Helpers
    # =========================================================================

    def capability(self, **kwargs) -> gnmi_pb2.CapabilityResponse:
        """ Executes an Unary Capabilities RPC """
        request = gnmi_pb2.CapabilityRequest()
        response = self.stub.Capabilities(request, metadata=self.metadata)
        return response

    def get(self, **kwargs) -> gnmi_pb2.GetResponse:
        """ Executes an Unary Get RPC """
        prefix = kwargs.get('prefix', "")
        paths = kwargs.get('paths', [])
        type_arg = kwargs.get('type') or kwargs.get('data_type') or ''
        if isinstance(type_arg, str) and type_arg.lower() == 'all':
            type_arg = ''

        get_type = {
            'state': gnmi_pb2.GetRequest.STATE,
            'config': gnmi_pb2.GetRequest.CONFIG,
            'operational': gnmi_pb2.GetRequest.OPERATIONAL,
            '': gnmi_pb2.GetRequest.ALL,
        }

        enc = kwargs.get('encoding') or self.encoding
        request = gnmi_pb2.GetRequest(
            encoding=self.encoding_map[enc],
            type=get_type.get(type_arg.lower() if isinstance(type_arg, str) else '', gnmi_pb2.GetRequest.ALL)
        )
        
        if prefix:
            request.prefix.CopyFrom(parse_path(prefix))
            
        for p in paths:
            path_elem = request.path.add()
            path_elem.CopyFrom(parse_path(p))

        response = self.stub.Get(request, metadata=self.metadata)
        return response

    def _build_typed_val(self, val: Any, encoding: str = "json_ietf") -> gnmi_pb2.TypedValue:
        """Translates Python inputs into gnmi_pb2.TypedValue adhering to gNMI Section 3.4."""
        if gnmi_pb2 is None:
            raise RuntimeError("gnmi_pb2 is not loaded")

        if isinstance(val, gnmi_pb2.TypedValue):
            return val

        tv = gnmi_pb2.TypedValue()

        # 1. Check if string points to a file reference (@file or valid path)
        if isinstance(val, str):
            file_path = val[1:] if val.startswith('@') else val
            if os.path.isfile(file_path):
                try:
                    with open(file_path, 'rb') as f:
                        file_bytes = f.read()
                    try:
                        parsed_json = json.loads(file_bytes.decode('utf-8'))
                        if isinstance(parsed_json, (dict, list)):
                            if encoding == 'json':
                                tv.json_val = file_bytes
                            else:
                                tv.json_ietf_val = file_bytes
                            return tv
                    except Exception:
                        pass
                    tv.bytes_val = file_bytes
                    return tv
                except Exception as e:
                    logger.warning(f"[Client] Failed to read payload file {file_path}: {e}")

            # 2. Check if string is an inline JSON object or list
            try:
                parsed = json.loads(val)
                if isinstance(parsed, (dict, list)):
                    raw_bytes = val.encode('utf-8')
                    if encoding == 'json':
                        tv.json_val = raw_bytes
                    else:
                        tv.json_ietf_val = raw_bytes
                    return tv
            except (json.JSONDecodeError, ValueError):
                pass

            # 3. Check for boolean strings
            if val.lower() == 'true':
                tv.bool_val = True
                return tv
            elif val.lower() == 'false':
                tv.bool_val = False
                return tv

            # 4. Fallback for string
            tv.string_val = str(val)
            return tv

        # 5. Native Python booleans (MUST check before int)
        if isinstance(val, bool):
            tv.bool_val = val
            return tv

        # 6. Native Python integers
        if isinstance(val, int):
            if val >= 0:
                tv.uint_val = val
            else:
                tv.int_val = val
            return tv

        # 7. Native Python floats
        if isinstance(val, float):
            tv.float_val = val
            return tv

        # 8. Native Python dictionaries & lists
        if isinstance(val, (dict, list)):
            raw_bytes = json.dumps(val).encode('utf-8')
            if encoding == 'json':
                tv.json_val = raw_bytes
            else:
                tv.json_ietf_val = raw_bytes
            return tv

        # 9. Bytes
        if isinstance(val, bytes):
            tv.bytes_val = val
            return tv

        # 10. Fallback
        tv.string_val = str(val)
        return tv

    def set(self, updates: list = None, replaces: list = None, deletes: list = None, prefix: str = "", encoding: str = None, **kwargs) -> Any:
        """ Executes a Unary Set RPC adhering to gNMI Section 3.4 """
        if gnmi_pb2 is None:
            raise RuntimeError("gnmi_pb2 is not loaded")

        enc = encoding or self.encoding or "json_ietf"
        request = gnmi_pb2.SetRequest()

        if prefix:
            request.prefix.CopyFrom(parse_path(prefix))

        # Logical execution order per Section 3.4.3:
        # 1. delete
        for path in (deletes or []):
            del_elem = request.delete.add()
            del_elem.CopyFrom(parse_path(path))

        # 2. replace
        for item in (replaces or []):
            if isinstance(item, (tuple, list)) and len(item) == 2:
                p, v = item
            elif isinstance(item, dict):
                for p, v in item.items():
                    rep_obj = request.replace.add()
                    rep_obj.path.CopyFrom(parse_path(p))
                    rep_obj.val.CopyFrom(self._build_typed_val(v, encoding=enc))
                continue
            else:
                p, v = item, ""
            rep_obj = request.replace.add()
            rep_obj.path.CopyFrom(parse_path(p))
            rep_obj.val.CopyFrom(self._build_typed_val(v, encoding=enc))

        # 3. update
        for item in (updates or []):
            if isinstance(item, (tuple, list)) and len(item) == 2:
                p, v = item
            elif isinstance(item, dict):
                for p, v in item.items():
                    upd_obj = request.update.add()
                    upd_obj.path.CopyFrom(parse_path(p))
                    upd_obj.val.CopyFrom(self._build_typed_val(v, encoding=enc))
                continue
            else:
                p, v = item, ""
            upd_obj = request.update.add()
            upd_obj.path.CopyFrom(parse_path(p))
            upd_obj.val.CopyFrom(self._build_typed_val(v, encoding=enc))

        try:
            response = self.stub.Set(request, metadata=self.metadata)
            return response
        except grpc.RpcError as e:
            code = e.code() if hasattr(e, 'code') else 'UNKNOWN'
            details = e.details() if hasattr(e, 'details') else str(e)
            logger.error(f"[Client] gNMI Set RPC failed: code={code}, details={details}")
            raise

    def _build_subscribe_request(self, config: dict) -> gnmi_pb2.SubscribeRequest:
        """ Constructs the SubscribeRequest object """
        sub_list = gnmi_pb2.SubscriptionList()
        mode = config.get('mode', 'stream').lower()

        if mode == 'once':
            sub_list.mode = gnmi_pb2.SubscriptionList.ONCE
        elif mode == 'poll':
            sub_list.mode = gnmi_pb2.SubscriptionList.POLL
        else:
            sub_list.mode = gnmi_pb2.SubscriptionList.STREAM

        sub_list.encoding = self.encoding_map[self.encoding]
        sub_list.updates_only = config.get('updates_only', False)

        prefix = config.get('prefix', '')
        if prefix:
            sub_list.prefix.CopyFrom(parse_path(prefix))

        for path_obj in config.get('paths', []):
            sub = sub_list.subscription.add()
            sub.path.CopyFrom(parse_path(path_obj))

            if mode == 'stream':
                smode = str(config.get('sub_mode') or config.get('stream_mode') or 'sample').lower()
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
                logger.error(f"[Client] Exception in pb_generator: {e}")
                if self.debug:
                    import traceback
                    traceback.print_exc()
                raise

        return self.stub.Subscribe(pb_generator(), metadata=self.metadata)
