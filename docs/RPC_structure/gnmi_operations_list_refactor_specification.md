# Refactor gNMI Configuration Schema to Support Sequential Multi-Operation Pipelines

## 1. Context & Objective

Following the refactoring of NETCONF operations to an ordered `operations:` sequence, the gNMI unary RPC configuration in `gnmi_client_py` needs to be brought into architectural alignment.

Currently, gNMI configurations rely on fragmented, legacy top-level keys across test files and schemas:

```
# Deprecated fragmented schemas
# Capability:
targets:
  172.20.20.2:57401:
    operation: "capability"

# Get:
targets:
  172.20.20.2:57401:
    get-path:
      - "openconfig:/system/state/hostname"

# Set:
targets:
  172.20.20.2:57401:
    update-list:
      - "openconfig:/interfaces/interface[name=mgmt0]/config/description:::test-desc"
    delete-list:
      - "openconfig:/interfaces/interface[name=mgmt0]/config/description"

```

This legacy approach presents major issues:

1. **Schema Inconsistency**: Different RPCs use completely distinct notation styles (`operation: capability` vs `get-path` vs `update-list`/`delete-list`).

2. **Fragile String Delimitation**: Using `path:::value` within `update-list` prevents robust handling of native types (integers, booleans, arrays, JSON-IETF objects).

3. **No Pipeline Execution**: Chaining unary operations (e.g., querying `capabilities` $\rightarrow$ applying a `set` mutation $\rightarrow$ verifying state with a `get`) within a single persistent gRPC channel session is currently impossible.

To resolve this, refactor the gNMI configuration models, worker dispatching, and client execution to support an ordered sequence of operations under `operations:`. All unary gNMI operations for a target must execute sequentially over a single gRPC channel lifecycle.

## 2. Target YAML Schema Specification

### General Structure

Under each target, deprecate legacy flat keys (`operation`, `get-path`, `update-list`, `delete-list`) in favor of an ordered `operations` list:

```
targets:
  <host:port>:
    username: <string>
    password: <string>
    protocol: "gnmi"
    
    # Optional transport parameters
    insecure: false
    skip_verify: false
    timeout: 30

    # Ordered sequence of unary operations
    operations:
      - <operation_type>:
          <operation_parameter>: <value>

```

### Operation Mapping Specifications

Each item in `operations:` is a single-key dictionary matching the operation type.

#### A. `capability`

Requests server capabilities and supported YANG models.

```
- capability: {}

```

#### B. `get`

Executes a `GetRequest` against one or more paths.

```
- get:
    prefix: "openconfig:"           # optional path prefix
    type: "all"                     # optional: all | config | state | operational (default: all)
    encoding: "json_ietf"           # optional: json | bytes | proto | ascii | json_ietf (default: json_ietf)
    path:
      - "system/state/hostname"
      - "interfaces/interface[name=mgmt0]/state/oper-status"

```

#### C. `set`

Executes a single `SetRequest` containing atomic mutations across `delete`, `update`, and/or `replace`.

```
- set:
    prefix: "openconfig:"           # optional path prefix
    
    # delete accepts a list of path strings
    delete:
      - "interfaces/interface[name=mgmt0]/config/description"

    # update accepts a list of path + value mappings
    update:
      - path: "interfaces/interface[name=mgmt0]/config/description"
        val: "Configured via multi-op pipeline"
      - path: "system/config/hostname"
        val: "spine-01"

    # replace accepts a list of path + value mappings
    replace:
      - path: "interfaces/interface[name=mgmt0]/config/mtu"
        val: 1500

```

#### D. Multi-Operation Pipeline Example

```
targets:
  172.20.20.2:57401:
    username: "admin"
    password: "NokiaSrl1!"
    protocol: "gnmi"
    operations:
      # Step 1: Query capabilities
      - capability: {}

      # Step 2: Mutate interface description
      - set:
          prefix: "openconfig:"
          update:
            - path: "interfaces/interface[name=mgmt0]/config/description"
              val: "Pipeline-Managed-Interface"

      # Step 3: Validate applied configuration and state
      - get:
          prefix: "openconfig:"
          type: "all"
          encoding: "json_ietf"
          path:
            - "interfaces/interface[name=mgmt0]/state/description"

```

## 3. Scope of Workspace Changes

### A. Configuration Models (`config/operations.py`, `config/model.py`, `config/protocol_options/gnmi.py`)

1. **Operation Data Models (`config/operations.py`)**:

   * Append `type: Any = None` field to class `Change`

     * `type` represents YANG built-in types — it will be discussed later.

2. **Parser & Normalization Logic (`config/model.py`, `config/selectors.py`)**:

   * Extend the operation normalization logic introduced for NETCONF so that it parses gNMI operation mappings:

     * `{"capability": ...}` $\rightarrow$ `CapabilitiesOperation`

     * `{"get": ...}` $\rightarrow$ `GetOperation`

     * `{"set": ...}` $\rightarrow$ `SetOperation`

   * **Substituting all legacy fields**: Substitute all legacy fields (`get-path`, `update-list`, `delete-list`, or `operation: capability`) into a single-item `operations` list.
  
     * For `Update/Replace` in gNMI `SetRequest`, support `path:::value` expression too. It will use `path` key solely.

### B. Client Layer (`specs/gnmi_client.py`, `specs/base_client.py`)

1. **Structured Set Payload Translation**:

   * Refactor `GnmiClient.set()`:

     * Pack `gnmi_pb2.TypedValue` automatically if field `type` from `Change` has been set.

2. **Unified `execute()` Interface**:

   * Ensure `GnmiClient` can also use `execute(operation: Any)` defined at `base_client.py`

   * Dispatch:

     * `CapabilityOperation` $\rightarrow$ `self.capabilities()`

     * `GetOperation` $\rightarrow$ `self.get(...)`

     * `SetOperation` $\rightarrow$ `self.set(...)`

### C. Execution Engine & Worker (`managers/unary_worker.py`, `managers/manager.py`)

1. **Persistent Session / Channel Context**:

   * Ensure `SequentialWorker` handles gNMI targets identically to NETCONF targets:

     ```
     with self._get_client() as client:
         results = []
         for op in target.operations:
             result = client.execute(op)
             results.append(result)
         return results
     
     ```

   * Verify that `GnmiClient` preserves its underlying `grpc.Channel` across iterations inside the context manager instead of closing and reopening the gRPC channel per operation.

2. **Output Handling (`modules/formatter.py`, `modules/output.py`)**:

   * Ensure `Formatter` cleanly serializes and displays a sequence of gNMI responses (e.g., printing distinct sections for `CapabilityResponse`, `SetResponse`, and `GetResponse`).

### D. Test Fixtures Refactor (`tests/gnmi_*.yaml`)

Migrate all existing unary gNMI test YAML files to the new `operations:` structure:

* `tests/gnmi_capability_test.yaml`:

  ```yaml
  targets:
    172.20.20.2:57401:
      username: "admin"
      password: "NokiaSrl1!"
      operations:
        - capability: {}
  
  ```

* `tests/gnmi_get_test.yaml`:

  ```yaml
  targets:
    172.20.20.2:57401:
      username: "admin"
      password: "NokiaSrl1!"
      operations:
        - get:
            path:
              - "openconfig:/system/state/hostname"
  
  ```

* `tests/gnmi_set_test.yaml`:

  ```yaml
  targets:
    172.20.20.2:57401:
      username: "admin"
      password: "NokiaSrl1!"
      operations:
        - set:
            update:
              - path: "openconfig:/interfaces/interface[name=mgmt0]/config/description"
                val: "YAML-Set_update-Test"
            replace:
              - path: "openconfig:/interfaces/interface[name=mgmt0]/config/description"
                val: "YAML-Set_replace-Test"
  
  ```

* `tests/gnmi_delete_test.yaml`:

  ```yaml
  targets:
    172.20.20.2:57401:
      username: "admin"
      password: "NokiaSrl1!"
      operations:
        - set:
            delete:
              - "openconfig:/interfaces/interface[name=mgmt0]/config/description"
  
  ```

* `tests/gnmi_multiple_set_test.yaml`:
  Migrate to a single `set` block containing multiple updates/deletes, or multiple sequential `set` items.

* **New Fixture**: Add `tests/gnmi_multi_operation_pipeline_test.yaml` verifying `capability` $\rightarrow$ `get` $\rightarrow$ `set` $\rightarrow$ `get` in one configuration.

*(Note: Streaming subscription tests such as `gnmi_subscribe_*.yaml` remain on their dedicated subscription models and are outside the scope of this unary refactor.)*

### E. Unit Tests (`tests/test_config_models.py`, `tests/test_gnmi_set.py`, `tests/test_managers.py`)

1. Update `tests/test_config_models.py`:

   * Test parsing gNMI operations within the `operations` list.

   * Verify validation on missing required paths or invalid types.

   * Verify that DO NOT USE legacy YAML gNMI keys.

2. Update `tests/test_gnmi_set.py`:

   * Test the conversion of structured Python data types to `TypedValue`.

3. Update `tests/test_managers.py`:

   * Test sequential dispatch of multiple gNMI operations within `SequentialWorker`.

## 4. Implementation Steps

1. **Model Extension**:

   * Add `type: Any = None` field to `Change` in `config/operations.py`.

2. **Worker Verification**:

   * Verify that `managers/unary_worker.py` dispatches gNMI operations inside a persistent channel context identically to NETCONF.

3. **Fixture Migration**:

   * Refactor all `tests/gnmi_*.yaml` files to use `operations:`.

   * Add `tests/gnmi_multi_operation_pipeline_test.yaml`.

4. **Validation**:

   * Run test suites (`pytest tests/`) and verify green status across both gNMI and NETCONF.

## 5. Acceptance Criteria

* \[ \] All unary `tests/gnmi_*.yaml` files use the `operations:` list structure.

* \[ \] Operation parameters (`prefix`, `path`, `delete`, `update`, `replace`) are strictly scoped within their respective operation blocks.

* \[ \] `GnmiClient` natively handles typed values in `update` and `replace` without requiring `path:::val` string parsing.

* \[ \] Multiple sequential gNMI unary operations execute over a single persistent `grpc.Channel` lifecycle.

* \[ \] Streaming subscriptions (`SubscribeSession`) remain isolated from unary operations.

* \[ \] All existing repository tests pass (`pytest tests/`).