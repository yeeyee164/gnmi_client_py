# Decoupled Streaming & Polymorphic Options

## 0. Raised issues

Below is recently feedbacks for git commit from [0e82f3b](https://github.com/yeeyee164/gnmi_client_py/commit/0e82f3b977acda877d6d57b6b753b8157e992258) to [6daa639](https://github.com/yeeyee164/gnmi_client_py/commit/6daa6397c96b967e3c2301f91f7a02febd4c483c)

1.  SubscribeSession still uses old-fashioned code(not using 'execute\_' things)

2. \`subscribe_session.py\` still tilted for gNMI Subscribe, especially at \`request_generator()\` and \`trigger_poll()\`.

3. \`protocol_options: Any\` is still the loose screw, use polymorphism instead.

4. It's a good choice to make each \`execute\_\` methods defined at \`specs/base_client.py\` abstractmethod.

## 1. Executive Summary & Design Scope

This specification provides the architectural blueprint and step-by-step instructions for an autonomous agent or developer to resolve three key structural issues in the repository:

1. **Protocol-Agnostic Streaming Delegation (Issue 1 & 2)**:

   * Eliminate wire-protocol dependencies (such as `gnmi_pb2`, gRPC stubs, direct message queues, and `request_generator()`) from `managers/subscribe_session.py`.

   * Shift streaming execution to a standardized `execute_subscribe()` delegation pattern that mirrors `UnaryWorker`.

   * Abstract stream control (such as polling triggers and cancellation) so that the worker does not require protocol-specific branching.

2. **Stream Context & Event Data Classes**:

   * Define dedicated, strongly-typed data classes to encapsulate bi-directional stream communication (commands sent to the generator, session cancellation, and incoming telemetry events).

   * Ensure the streaming architecture accommodates future protocols, such as NETCONF Event Notifications (RFC 5277 / RFC 8639), without requiring modifications to `SubscribeSession`.

3. **Polymorphic `ProtocolOptions` (Issue 3)**:

   * Eliminate `protocol_options: Any` from configuration models.

   * Introduce an extensible abstract base class (`BaseProtocolOptions`) with self-validation and serialization.

4. **Disposition on Review Item #4 (Discarded)**:

   * We **do not** make every `execute_*` method an `@abstractmethod` on `BaseClient`. Enforcing `@abstractmethod` across all operations violates the Interface Segregation Principle (ISP) and forces protocol handlers to implement dummy boilerplate for operations they do not support (e.g., NETCONF locking vs. gNMI subscriptions).

   * Instead, `BaseClient` provides a default implementation that raises `UnsupportedOperationError(f"{self.__class__.__name__} does not support <operation>")`.

## 2. Target Architecture & Component Models

### 2.1 Polymorphic `ProtocolOptions`

Replace unstructured dictionaries and `Any` references with a typed hierarchy under `config/protocol_options/`.

#### Class Hierarchy Layout

```
BaseProtocolOptions (ABC)
│   ├── validate() -> None (abstractmethod)
│   └── to_dict() -> Dict[str, Any]
│
├── GnmiOptions (config/protocol_options/gnmi.py)
│   ├── encoding: GnmiEncoding
│   ├── sub_mode: GnmiSubscriptionMode
│   ├── sample_interval_ns: int
│   ├── heartbeat_interval_ns: int
│   └── suppress_redundant: bool
│
└── NetconfOptions (config/protocol_options/netconf.py)
    ├── target_datastore: str
    ├── source_datastore: str
    ├── default_operation: str
    ├── error_option: str
    └── lock_target: bool

```

#### Base Definition (`config/protocol_options/base.py`)

```
from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseProtocolOptions(ABC):
    """Abstract base class for all protocol-specific configuration options."""

    @abstractmethod
    def validate(self) -> None:
        """Validate options consistency.

        Raises:
            ValueError: If options violate protocol constraints or ranges.
        """
        pass

    def to_dict(self) -> Dict[str, Any]:
        """Convert options to a serializable dictionary."""
        return {
            k: v for k, v in self.__dict__.items() if not k.startswith("_")
        }

```

#### Integration into `config/model.py`

```
from typing import Optional, Union
from config.protocol_options.base import BaseProtocolOptions
from config.protocol_options.gnmi import GnmiOptions
from config.protocol_options.netconf import NetconfOptions

ProtocolOptionsType = Union[GnmiOptions, NetconfOptions, BaseProtocolOptions]


@dataclass
class RootConfig:
    delivery: DeliveryConfig
    operation: OperationConfig
    selectors: List[SelectorConfig] = field(default_factory=list)
    protocol_options: Optional[ProtocolOptionsType] = None

    def validate(self) -> None:
        self.delivery.validate()
        self.operation.validate()
        for sel in self.selectors:
            sel.validate()
        if self.protocol_options is not None:
            self.protocol_options.validate()

```

### 2.2 Streaming Abstraction & Generator Data Classes

Streaming interactions are bi-directional: the worker yields commands into the stream (e.g., poll requests, subscription updates, or stop signals), and the wire handler yields structured events back to the worker.

Encapsulating this boundary into dedicated data classes prevents transport primitives (such as gRPC iterator queues or NETCONF SSH channel locks) from leaking into the manager tier.

#### Stream Models (`specs/stream_types.py`)

```
from dataclasses import dataclass, field
from enum import Enum, auto
import queue
import threading
import time
from typing import Any, Dict, Optional


class StreamCommandType(Enum):
    """Commands dispatched from worker to the stream generator."""
    POLL = auto()
    CANCEL = auto()
    HEARTBEAT = auto()
    CUSTOM = auto()


@dataclass(frozen=True)
class StreamCommand:
    """Upstream command sent into an active stream channel."""
    command_type: StreamCommandType
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class StreamContext:
    """Bi-directional control context managing stream lifecycle and signal dispatch."""
    command_queue: queue.Queue = field(default_factory=queue.Queue)
    stop_event: threading.Event = field(default_factory=threading.Event)

    def request_poll(self) -> None:
        """Signal the stream generator to execute a poll cycle."""
        self.command_queue.put(
            StreamCommand(command_type=StreamCommandType.POLL)
        )

    def cancel(self) -> None:
        """Signal the stream generator to stop and release underlying connections."""
        self.stop_event.set()
        self.command_queue.put(
            StreamCommand(command_type=StreamCommandType.CANCEL)
        )

    @property
    def is_cancelled(self) -> bool:
        return self.stop_event.is_set()


@dataclass
class StreamEvent:
    """Protocol-agnostic representation of an incoming telemetry notification or event."""
    protocol: str
    timestamp: float
    raw_payload: Any
    data: Optional[Dict[str, Any]] = None
    is_sync_marker: bool = False
    error: Optional[Exception] = None

```

### 2.3 Layer Separation: Manager, Worker, and Client Handlers

To restore architectural symmetry across workers:

1. `UnaryWorker` delegates execution to `client.execute_<operation>()`.

2. `SubscribeSession` delegates execution to `client.execute_subscribe()`, receiving an iterator of `StreamEvent` objects.

#### Text Flow Diagram

```
[ Manager / Factory ]
         │
         ▼
[ SubscribeSession (Worker) ]
   - Owns background thread & lifecycle
   - Instantiates StreamContext
   - Iterates over StreamEvent stream
   - Formats output via modules/formatter.py
         │
         │ (1) execute_subscribe(selectors, options, context)
         ▼
[ GnmiClient (specs/gnmi_client.py) ]
   - Translates selectors to gnmi_pb2.Path
   - Runs internal _request_generator(context) listening on context.command_queue
   - Invokes stub.Subscribe(generator)
   - Converts gnmi_pb2.SubscribeResponse -> StreamEvent
   - Yields StreamEvent back to SubscribeSession
         │
         │ (2) context.request_poll() / context.cancel()
         ▼
[ gRPC Wire Transport ]

```

#### Protocol-Agnostic Extensibility (Future NETCONF Subscriptions)

When NETCONF subscription support (RFC 5277 / RFC 8639) is added, `NetconfClient.execute_subscribe()` can be implemented as follows without changing a single line of `SubscribeSession`:

1. `NetconfClient.execute_subscribe(selectors, options, context)` is invoked.

2. The client transmits the `<create-subscription>` RPC over the NETCONF session.

3. The client loops over incoming XML notification elements on the SSH channel until `context.is_cancelled` is flagged.

4. Each notification XML is wrapped into `StreamEvent(protocol="netconf", raw_payload=xml_root, data=parsed_dict)` and yielded.

5. If `context.request_poll()` is called, `NetconfClient` can either ignore it or raise an informational warning, since NETCONF notifications are event-driven rather than polled.

## 3. Agent Instruction Plan (Step-by-Step)

An autonomous agent implementing this refactor must execute the following chronological phases:

### Phase 1: Implement Polymorphic Protocol Options

1. **Create Base Class**:

   * File: `config/protocol_options/base.py`

   * Define `BaseProtocolOptions` with abstract `validate()` and concrete `to_dict()`.

2. **Update Concrete Options**:

   * Files: `config/protocol_options/gnmi.py` and `config/protocol_options/netconf.py`

   * Inherit from `BaseProtocolOptions`.

   * Implement `validate()` for each:

     * `GnmiOptions.validate()`: Validate ranges for `sample_interval_ns` ($\ge 0$), `heartbeat_interval_ns` ($\ge 0$), and valid enum values for `encoding` and `sub_mode`.

     * `NetconfOptions.validate()`: Ensure valid datastores (e.g., `running`, `candidate`, `startup`) and valid `default_operation` options (`merge`, `replace`, `none`).

3. **Integrate into Configuration Models**:

   * File: `config/model.py`

   * Change `protocol_options: Any` to `Optional[BaseProtocolOptions]`.

   * In `RootConfig.validate()`, ensure `self.protocol_options.validate()` is called when defined.

   * In `config/protocol_options/__init__.py`, cleanly expose `BaseProtocolOptions`, `GnmiOptions`, and `NetconfOptions`.

4. **Verify Model Validation**:

   * Execute existing model tests:

     ```
     pytest tests/test_config_models.py
     
     ```

### Phase 2: Create Stream Models & Abstract Interfaces

1. **Implement Stream Types**:

   * File: `specs/stream_types.py`

   * Implement `StreamCommandType`, `StreamCommand`, `StreamContext`, and `StreamEvent` as specified in Section 2.2.

   * Export these types in `specs/__init__.py`.

2. **Update Base Client**:

   * File: `specs/base_client.py`

   * Import `StreamContext` and `StreamEvent` from `specs.stream_types`.

   * Define the default `execute_subscribe` method:

     ```
     def execute_subscribe(
         self,
         selectors: List[SelectorConfig],
         options: Optional[BaseProtocolOptions] = None,
         context: Optional[StreamContext] = None,
     ) -> Iterator[StreamEvent]:
         """Execute a telemetry streaming session.
     
         Raises:
             UnsupportedOperationError: If the protocol handler does not support streaming.
         """
         raise UnsupportedOperationError(
             f"{self.__class__.__name__} does not support subscribe operations."
         )
     
     ```

   * *Ensure no abstract methods are introduced that force dummy implementations for other operations.*

### Phase 3: Move gNMI Generator Logic into `GnmiClient`

1. **Move gRPC Generator to `GnmiClient`**:

   * File: `specs/gnmi_client.py`

   * Remove any requirement for external modules to craft `gnmi_pb2.SubscribeRequest`.

   * Implement private helper `_build_subscribe_generator(self, selectors, options, context)`:

     * Yields initial `gnmi_pb2.SubscribeRequest(subscribe=...)` built from `selectors` and `options`.

     * Listens on `context.command_queue` with a short timeout (e.g., 0.1s to 0.5s) while checking `context.is_cancelled`.

     * If `StreamCommandType.POLL` is received, yields `gnmi_pb2.SubscribeRequest(poll=gnmi_pb2.Poll())`.

     * If `StreamCommandType.CANCEL` is received or `context.is_cancelled` is True, exits the generator cleanly.

2. **Implement `GnmiClient.execute_subscribe`**:

   * Invokes `stub.Subscribe(self._build_subscribe_generator(selectors, options, context))`.

   * Iterates through the yielded `gnmi_pb2.SubscribeResponse` messages.

   * Converts each response into a `StreamEvent`:

     ```
     yield StreamEvent(
         protocol="gnmi",
         timestamp=time.time(),
         raw_payload=response,
         is_sync_marker=response.sync_response,
     )
     
     ```

   * Catches `grpc.RpcError`, wraps it into a `StreamEvent(error=e)`, or raises appropriate domain exceptions.

### Phase 4: Refactor `SubscribeSession`

1. **Decouple `managers/subscribe_session.py`**:

   * Remove imports of `gnmi_pb2`, `gnmi_pb2_grpc`, and direct queue allocations for gRPC.

   * Maintain an instance of `StreamContext`:

     ```
     self.stream_context = StreamContext()
     
     ```

   * Update `trigger_poll()`:

     ```
     def trigger_poll(self) -> None:
         """Trigger a poll cycle on the active subscription stream."""
         if self.stream_context:
             self.stream_context.request_poll()
     
     ```

   * Update `stop()` / `close()`:

     ```
     def stop(self) -> None:
         """Stop the streaming session and terminate background threads."""
         if self.stream_context:
             self.stream_context.cancel()
         if self._thread and self._thread.is_alive():
             self._thread.join(timeout=self.timeout)
     
     ```

   * In the background worker execution loop (`_run`):

     ```
     stream = self.client.execute_subscribe(
         selectors=self.selectors,
         options=self.protocol_options,
         context=self.stream_context,
     )
     for event in stream:
         if self.stream_context.is_cancelled:
             break
         self._handle_stream_event(event)
     
     ```

   * In `_handle_stream_event(event: StreamEvent)`:

     * Handle `is_sync_marker`.

     * Route `event.raw_payload` or normalized `event.data` to `self.formatter` and `self.output_handler`.

### Phase 5: Verification & Regression Testing

1. **Unit & Manager Verification**:

   * Run existing manager tests:

     ```
     pytest tests/test_managers.py tests/test_config_models.py
     
     ```

2. **Streaming Execution Verification**:

   * Run all gNMI subscribe tests:

     ```
     pytest tests/test_gnmi_set.py
     # Execute subscribe test configs
     python client_main.py --config tests/gnmi_subscribe_once_test.yaml
     python client_main.py --config tests/gnmi_subscribe_poll_test.yaml
     
     ```

   * Validate poll trigger functionality: Ensure invoking `trigger_poll()` dispatches `StreamCommandType.POLL` through the context without deadlock or unhandled queue exceptions.

3. **Protocol Isolation Verification**:

   * Confirm that calling `NetconfClient.execute_subscribe()` cleanly raises `UnsupportedOperationError` without crashing the application process.