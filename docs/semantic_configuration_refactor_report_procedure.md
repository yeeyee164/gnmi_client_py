# Architectural Evaluation Report & Refactoring Procedures: Semantic Intent Configuration Model

**Project:** `gnmi_client_py`  
**Target Branch:** `managing_session_3`  
**Topic:** Transition from Protocol-Coupled Session Configurations to a Semantic Intent Configuration Architecture

---

## 1. Executive Opinion & Architectural Assessment

### 1.1 Comparison: Current vs. Proposed Architecture

| Architectural Dimension | Current Approach (Per-RPC Protocol Classes) | Proposed Approach (Semantic Intent + Adapters) |
| :--- | :--- | :--- |
| **Primary Organizing Principle** | Protocol first, then RPC (`GNMISetConfig`, `NetconfEditConfig`). | Semantic intent first (`SetOperation`), protocol as transport adapter. |
| **Scalability ($M \text{ Protocols} \times N \text{ RPCs}$)** | Combinatorial explosion. Adding RESTCONF adds up to $N$ new config classes and registry entries. | Linear ($O(M + N)$). Adding RESTCONF adds one `RestconfClient` adapter; config classes remain unchanged. |
| **Dispatch Mechanism** | String matching on `operation` (e.g., `['get', 'get-config', 'get-schema']`) and tuple lookups in `SESSION_CONFIG_REGISTRY`. | Type-safe dispatch (`isinstance(op, GetOperation)`), leveraging Python polymorphism and static typing. |
| **Payload Representation** | gNMI-biased (`updates`, `replaces`, `deletes`) vs. NETCONF-biased (`config`, `target_datastore`). | Unified semantic mutations (`List[Change]`), translated to wire format inside the client adapter. |
| **Worker Decoupling** | Workers unpack `self.kwargs` and leak protocol field names across operational boundaries. | Workers are clean execution runners that pass typed `OperationConfig` directly to `client.execute()`. |

---

### 1.2 Key Architectural Strengths

1. **Adherence to Clean Architecture (Separation of Concerns):**
   The configuration layer models *what* the user wants to accomplish (read state, mutate data, stream telemetry). The protocol adapters (`GNMIClient`, `NetconfClient`) encapsulate *how* that intent is translated into Protobufs or XML.
2. **Elimination of Protocol Leakage in Managers:**
   Currently, `UnaryManager` and `ManagerFactory` have to know protocol-specific strings:
   ```python
   # Current smell in manager.py
   if op in ['get', 'get-config', 'get-schema']:
       worker_cls = GetWorker
   elif op in ['set', 'edit-config']:
       worker_cls = SetWorker
   ```
   With semantic operations, the manager evaluates `isinstance(sc.operation, GetOperation)`. It doesn't care whether the wire protocol calls it `<get-config>` or `GetRequest`.
3. **True Unified Mutation Semantics (`Change` Dataclass):**
   Instead of forcing NETCONF to fake gNMI's `updates`/`replaces`/`deletes` or vice versa, modeling mutations as:
   $$\text{Change}(\text{path}, \text{operation} \in \{\text{MERGE}, \text{REPLACE}, \text{DELETE}\}, \text{value})$$
   creates a mathematically clean, universal mutation model that maps 1:1 to gNMI, NETCONF `<edit-config>`, and RESTCONF `PATCH`/`PUT`/`DELETE`.

---

### 1.4 Risks & Architectural Nuances

1. **The "Lowest Common Denominator" Trap:**
   Protocols have genuine differences that cannot always be abstracted without losing features:
   * NETCONF has datastores (`running`, `candidate`, `startup`), test options (`test-then-set`), and rollback policies.
   * gNMI has streaming modes (`SAMPLE`, `ON_CHANGE`), encodings (`JSON_IETF`, `PROTO`, `ASCII`), and heartbeat intervals.
   * **Mitigation:** The feedback correctly identifies that protocol-specific options must exist as an **isolated extension layer** (e.g., `protocol_options: Optional[GNMIOptions | NetconfOptions] = None`) rather than polluting the core operation fields.
2. **CLI & YAML Backward Compatibility:**
   Users will still type `python client_main.py netconf edit-config ...` or supply existing YAML files. The parser layer must take responsibility for assembling the semantic `SessionConfig` from legacy flags so no breaking changes reach end users.
3. **Migration Cost:**
   Workers currently pass `**self.kwargs` straight into client methods. Rushing this refactor in a single commit could break existing tests for gNMI Set and NETCONF Edit-Config. A disciplined, phased transition is essential.

---

## 2. Target Architecture Blueprint

### 2.1 Domain Model Structure

```
config/
├── __init__.py
├── model.py              # SessionConfig, ConnectionConfig, Protocol enum
├── operations.py         # GetOperation, SetOperation, SubscribeOperation, CapabilitiesOperation
├── selectors.py          # Selector, PathSelector, FilterSelector
├── delivery.py           # DeliveryPolicy, DeliveryMode
└── protocol_options/     # Protocol-specific escape hatches
    ├── __init__.py
    ├── gnmi.py           # GNMIOptions
    └── netconf.py        # NetconfOptions
```

---

### 2.2 Core Dataclass Specifications

#### A. Connection & Top-Level Session (`config/model.py`)

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from modules.security import SecurityProfile
from config.operations import OperationConfig

class Protocol(str, Enum):
    GNMI = "gnmi"
    NETCONF = "netconf"
    RESTCONF = "restconf"

@dataclass(frozen=True, kw_only=True)
class ConnectionConfig:
    """Pure network transport and authentication parameters."""
    target: str
    username: str = ""
    password: str = ""
    security: SecurityProfile = field(default_factory=SecurityProfile)
    insecure: bool = False

@dataclass(frozen=True, kw_only=True)
class ExecutionConfig:
    """Execution policies common to all operations."""
    timeout: int = 30
    retry_count: int = 0
    times: int = 1

@dataclass(frozen=True, kw_only=True)
class SessionConfig:
    """Top-level session definition pairing connection, protocol, and intent."""
    connection: ConnectionConfig
    protocol: Protocol
    operation: OperationConfig
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
```

#### B. Semantic Selectors (`config/selectors.py`)

```python
from dataclasses import dataclass
from abc import ABC

class Selector(ABC):
    """Base selector for target data identification."""
    pass

@dataclass(frozen=True, kw_only=True)
class PathSelector(Selector):
    """Path-based targeting (native to gNMI and RESTCONF; translatable to XPath)."""
    paths: tuple[str, ...]
    prefix: str = ""

@dataclass(frozen=True, kw_only=True)
class FilterSelector(Selector):
    """Expression-based filtering (XPath or XML Subtree for NETCONF)."""
    expression: str
    filter_type: str = "xpath"  # xpath, subtree
```

#### C. Semantic Operations (`config/operations.py`)

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from config.selectors import Selector, PathSelector
from config.delivery import DeliveryPolicy

class OperationConfig:
    """Base marker for all semantic operational intents."""
    pass

@dataclass(frozen=True, kw_only=True)
class CapabilitiesOperation(OperationConfig):
    """Discovery of supported models, encodings, and extensions."""
    pass

@dataclass(frozen=True, kw_only=True)
class GetSchemaOperation(OperationConfig):
    """Retrieval of schema definitions (RFC 6022 / YANG files)."""
    identifier: str
    version: Optional[str] = None
    format: str = "yang"

@dataclass(frozen=True, kw_only=True)
class GetOperation(OperationConfig):
    """Retrieval of operational or configuration state."""
    selector: Selector
    read_scope: str = "all"  # all, config, state, operational
    protocol_options: Any = None

class ChangeType(str, Enum):
    MERGE = "merge"
    REPLACE = "replace"
    DELETE = "delete"

@dataclass(frozen=True, kw_only=True)
class Change:
    """Atomic mutation intent."""
    path: str
    operation: ChangeType = ChangeType.MERGE
    value: Any = None

@dataclass(frozen=True, kw_only=True)
class SetOperation(OperationConfig):
    """Mutation of configuration datastores."""
    changes: tuple[Change, ...] = ()
    protocol_options: Any = None

@dataclass(frozen=True, kw_only=True)
class SubscribeOperation(OperationConfig):
    """Continuous or snapshot data subscription."""
    selector: Selector
    delivery: DeliveryPolicy
    protocol_options: Any = None
```

#### D. Delivery Policy (`config/delivery.py`)

```python
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class DeliveryMode(str, Enum):
    PERIODIC = "periodic"     # gNMI SAMPLE
    ON_CHANGE = "on_change"   # gNMI ON_CHANGE
    SNAPSHOT = "snapshot"     # gNMI ONCE
    POLL = "poll"             # gNMI POLL

@dataclass(frozen=True, kw_only=True)
class DeliveryPolicy:
    mode: DeliveryMode = DeliveryMode.PERIODIC
    interval: int = 0         # Sample interval in seconds
    heartbeat: int = 0        # Heartbeat interval in seconds
    suppress_redundant: bool = False
```

---

### 2.3 Architecture Flow Diagram

```
                 +--------------------------------+
                 | CLI Flags / YAML Configuration |
                 +--------------------------------+
                                 |
                                 v
                 +--------------------------------+
                 |         Config Builders        |
                 | (CLIConfigBuilder/FileBuilder) |
                 +--------------------------------+
                                 |
               Produces Semantic SessionConfig:
                 SessionConfig
                   ├── ConnectionConfig (target, auth, security)
                   ├── Protocol (GNMI | NETCONF)
                   ├── OperationConfig (Get | Set | Subscribe)
                   └── ExecutionConfig
                                 |
                                 v
                 +--------------------------------+
                 |         Manager Layer          |
                 | (ManagerFactory/UnaryManager)  |
                 +--------------------------------+
                                 |
                     Dispatches by Operation Type:
                     isinstance(op, GetOperation)
                                 |
                                 v
                 +--------------------------------+
                 |          Worker Layer          |
                 |   (GetWorker, SetWorker, etc.) |
                 +--------------------------------+
                                 |
                 Universal execution:
                 client.execute(session.operation)
                                 |
                                 v
                 +--------------------------------+
                 |    Protocol Adapter Layer      |
                 |  (GNMIClient / NetconfClient)  |
                 +--------------------------------+
                                 |
              Translates Semantic Object to Wire RPC:
              ├── GNMIClient:
              │     GetOperation -> gnmi_pb2.GetRequest
              │     SetOperation -> gnmi_pb2.SetRequest(updates, replaces, deletes)
              │     SubscribeOperation -> gnmi_pb2.SubscribeRequest
              └── NetconfClient:
                    GetOperation -> session.get_config() / session.get()
                    SetOperation -> session.edit_config(xml_payload)
                    GetSchemaOperation -> session.get_schema()
```

---

## 3. Layer Responsibility Matrix

| Layer | Responsible Modules | Allowed Knowledge | Strictly Forbidden Knowledge |
| :--- | :--- | :--- | :--- |
| **Config UI** | `ui/cmd.py`, `config/` | CLI args, YAML dicts, constructing `SessionConfig`. | Wire formats, `grpc`, `ncclient`, sockets, worker threads. |
| **Orchestration** | `managers/manager.py`, `managers/factory.py` | `SessionConfig`, `OperationConfig` types, thread pools, queues. | Protocol wire formats, Protobuf classes, XML schemas, raw kwargs. |
| **Worker Layer** | `unary_worker.py`, `subscribe_session.py` | Lifecycle orchestration (`start`, `stop`, `run`), `BaseClient` methods. | Protocol differences, string operations like `'edit-config'`. |
| **Protocol Adapter** | `specs/client.py`, `specs/netconf_client.py` | Semantic operations, wire libraries (`grpc`, `ncclient`), Protobuf, XML. | CLI options, YAML file schemas, ThreadPool managers. |

---

## 4. Phased Refactoring Implementation Roadmap

To eliminate regression risk and allow non-disruptive testing, execute the refactor across **five distinct phases**:

```
[Phase 1: Foundation]
  └── Create config/ package with pure dataclasses (ConnectionConfig, OperationConfig, etc.)
  └── Zero breaking changes to existing codebase.

[Phase 2: Adapter Layer Upgrade]
  └── Update BaseClient, GNMIClient, and NetconfClient to accept typed OperationConfig.
  └── Provide backward-compatible overload for existing **kwargs callers.

[Phase 3: Worker & Manager Decoupling]
  └── Refactor GetWorker, SetWorker, and SubscribeSession to consume OperationConfig directly.
  └── Refactor ManagerFactory to use isinstance(operation, ...) checks.

[Phase 4: Parser Transition]
  └── Refactor CLIConfigBuilder and FileConfigBuilder to output new SessionConfig.
  └── Deprecate old monolithic/per-RPC classes in ui/cmd.py.

[Phase 5: Cleanup & Test Suite Modernization]
  └── Update unit tests (test_managers.py, test_gnmi_set.py, test_netconf_edit_config.py).
  └── Remove legacy registry and deprecated classes.
```

---

### Detailed Procedures by Phase

### Phase 1: Create the Semantic Configuration Package

1. Create directory `config/` and subpackages `config/protocol_options/`.
2. Implement:
   * `config/model.py` (`Protocol`, `ConnectionConfig`, `ExecutionConfig`, `SessionConfig`).
   * `config/selectors.py` (`Selector`, `PathSelector`, `FilterSelector`).
   * `config/delivery.py` (`DeliveryMode`, `DeliveryPolicy`).
   * `config/operations.py` (`CapabilitiesOperation`, `GetSchemaOperation`, `GetOperation`, `Change`, `ChangeType`, `SetOperation`, `SubscribeOperation`).
   * `config/protocol_options/gnmi.py` (`GNMIOptions`).
   * `config/protocol_options/netconf.py` (`NetconfOptions`).
3. Add unit test `tests/test_config_models.py` verifying instantiation and immutability (`frozen=True`).

---

### Phase 2: Implement Semantic Translation in Protocol Clients

1. **Update `specs/base_client.py`:**
   Add typed method signatures alongside existing methods:
   ```python
   class BaseClient(ABC):
       @abstractmethod
       def execute_get(self, operation: GetOperation) -> Any: ...
       @abstractmethod
       def execute_set(self, operation: SetOperation) -> Any: ...
       @abstractmethod
       def execute_subscribe(self, operation: SubscribeOperation) -> Generator: ...
       @abstractmethod
       def execute_capabilities(self, operation: CapabilitiesOperation) -> Any: ...
   ```
2. **Update `specs/client.py` (`GNMIClient`):**
   * Implement `execute_set(self, operation: SetOperation)`:
     Iterate through `operation.changes`. Group items where:
     * `change.operation == ChangeType.MERGE` $\rightarrow$ `updates.append((change.path, change.value))`
     * `change.operation == ChangeType.REPLACE` $\rightarrow$ `replaces.append((change.path, change.value))`
     * `change.operation == ChangeType.DELETE` $\rightarrow$ `deletes.append(change.path)`
     Then delegate to internal Protobuf `SetRequest` builder.
   * Implement `execute_get(self, operation: GetOperation)`:
     Extract paths from `operation.selector` (if `PathSelector`), extract encoding from `operation.protocol_options`, build `GetRequest`.
   * Implement `execute_subscribe(self, operation: SubscribeOperation)`:
     Map `operation.delivery.mode` (`PERIODIC` $\rightarrow$ `STREAM/SAMPLE`, `ON_CHANGE` $\rightarrow$ `STREAM/ON_CHANGE`, `SNAPSHOT` $\rightarrow$ `ONCE`, `POLL` $\rightarrow$ `POLL`).
3. **Update `specs/netconf_client.py` (`NetconfClient`):**
   * Implement `execute_set(self, operation: SetOperation)`:
     If `operation.changes` are provided, generate the `<edit-config>` XML elements with `nc:operation="merge|replace|delete"`.
     If `operation.protocol_options` specifies `config` (raw XML), pass it directly.
   * Implement `execute_get(self, operation: GetOperation)`:
     Map `operation.read_scope`:
     * `"config"` $\rightarrow$ call `session.get_config(source=...)`
     * `"all"` or `"operational"` $\rightarrow$ call `session.get(filter=...)`
   * Implement `execute_schema(self, operation: GetSchemaOperation)`:
     Call `session.get_schema(identifier=operation.identifier, version=operation.version, format=operation.format)`.

---

### Phase 3: Decouple Workers and Managers

1. **Refactor `BaseUnaryWorker` (`managers/unary_worker.py`):**
   * Worker constructor accepts `session: SessionConfig`.
   * Worker stores `self.session = session` and `self.operation = session.operation`.
   * Eliminate `self.kwargs = dataclasses.asdict(config)`.
2. **Refactor Concrete Workers:**
   * `CapabilityWorker.start()`: calls `self.client.execute_capabilities(self.operation)`.
   * `GetWorker.start()`: calls `self.client.execute_get(self.operation)`.
   * `SetWorker.start()`: calls `self.client.execute_set(self.operation)`.
3. **Refactor `SubscribeSession` (`managers/subscribe_session.py`):**
   * Constructor accepts `session: SessionConfig`.
   * Calls `self.client.execute_subscribe(self.session.operation)`.
   * Mode check becomes `if self.session.operation.delivery.mode == DeliveryMode.POLL:`.
4. **Refactor `ManagerFactory` (`managers/manager.py`):**
   ```python
   # Replace string operation checks with type checks:
   op = session.operation
   if isinstance(op, (CapabilitiesOperation, GetOperation, SetOperation, GetSchemaOperation)):
       return UnaryManager(...)
   elif isinstance(op, SubscribeOperation):
       return SubscriptionManager(...)
   ```

---

### Phase 4: Refactor CLI and File Builders

1. **Update `CLIConfigBuilder` (`ui/cmd.py`):**
   * Inspect subcommand structure:
     * `gnmi get` / `netconf get` / `netconf get-config` $\rightarrow$ construct `GetOperation`.
     * `gnmi set` $\rightarrow$ translate `--update`, `--replace`, `--delete` arguments into `Change` objects inside `SetOperation`.
     * `netconf edit-config` $\rightarrow$ construct `SetOperation` with `NetconfOptions(target_datastore=...)`.
     * `netconf get-schema` $\rightarrow$ construct `GetSchemaOperation(identifier=...)`.
     * `gnmi subscribe` $\rightarrow$ construct `SubscribeOperation(selector=..., delivery=...)`.
   * Build `ConnectionConfig` from connection flags (`--target`, `--username`, `--password`, `--tls-*`).
   * Wrap into `SessionConfig(connection=conn, protocol=proto, operation=op, execution=exec_cfg)`.
2. **Update `FileConfigBuilder` (`ui/cmd.py`):**
   * Parse multi-target YAML subscriptions into `SubscribeOperation` objects.
   * Provide defaults: `protocol = Protocol.GNMI`, `mode = DeliveryMode.PERIODIC`.
