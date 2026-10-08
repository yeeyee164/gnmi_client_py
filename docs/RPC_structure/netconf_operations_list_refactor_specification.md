# Refactor NETCONF Configuration Schema to Support Sequential Multi-Operation Pipelines

## 1. Context & Objective

Currently, the configuration parser and test YAML files in `gnmi_client_py` assume a single, flat operation per target:

```yaml
# Deprecated flat schema
targets:
  172.20.20.2:830:
    username: "admin"
    password: "password"
    operation: "get-schema"
    identifier: "openconfig-interfaces"
    version: "2024-04-04"
```

This model presents two critical architectural limitations:
1. **Unscoped Parameters**: Operation-specific arguments (such as `identifier`, `version`, `filter`, or `config`) leak into the target connection specification alongside credentials.
2. **Session Termination**: Executing only a single operation per connection makes it impossible to run sequential, stateful workflows (such as `<lock>` $\rightarrow$ `<edit-config>` $\rightarrow$ `<validate>` $\rightarrow$ `<commit>` $\rightarrow$ `<unlock>`) within a single persistent SSH/NETCONF session.

To resolve this, refactor the configuration models and worker execution flow to support an ordered sequence of operations under an `operations` list. Each target can define one or more operations executed sequentially within a single client connection lifecycle.

---

## 2. Target YAML Schema Specification

### General Structure

Under each target, deprecate top-level operation parameters in favor of the `operations` list:

```yaml
targets:
  <host:port>:
    username: <string>
    password: <string>
    # Optional connection parameters
    hostkey_verify: false
    timeout: 30
    
    # Sequential list of operations
    operations:
      - <operation_type>:
          <operation_parameter>: <value>
```

### Operation Mapping Format

Each item in the `operations` list must be a single-key dictionary where the key is the operation name, or an object specifying the operation type explicitly.

#### A. `get-schema`
```yaml
- get-schema:
    identifier: "openconfig-interfaces"
    version: "2024-04-04"
    format: "yang" # optional
```

#### B. `get-config`
```yaml
- get-config:
    source: "running" # running, candidate, startup
    filter: "tests/netconf_get_filter_test.xml" # optional filter path or XML string
    filter_type: "subtree" # subtree or xpath
```

#### C. `get`
```yaml
- get:
    filter: "tests/netconf_get_filter_test.xml"
    filter_type: "subtree"
```

#### D. `edit-config`
```yaml
- edit-config:
    target: "candidate" # candidate or running
    config: "tests/router_desc.xml"
    default_operation: "merge" # merge, replace, none
    error_option: "stop-on-error"
```

#### E. Multi-Operation Pipeline Example
```yaml
targets:
  172.20.20.2:830:
    username: "admin"
    password: "NokiaSrl1!"
    hostkey_verify: false
    operations:
      - get-schema:
          identifier: "openconfig-interfaces"
      - get-config:
          source: "running"
          filter: "tests/netconf_get_filter_test.xml"
      - edit-config:
          target: "candidate"
          config: "tests/router_desc.xml"
```

---

## 3. Scope of Workspace Changes

### A. Configuration Models (`config/model.py`, `config/operations.py`, `config/protocol_options/netconf.py`)

1. **Operation Normalization**:
   * Implement a parser/validator for the `operations` list. It should parse items structured either as:
     * Mapping syntax: `{"get-schema": {"identifier": "openconfig-interfaces", ...}}`
     * Object syntax: `{"operation": "get-schema", "identifier": "openconfig-interfaces", ...}`
   * Normalize these into typed semantic operation objects (`GetSchemaOperation`, `GetOperation`, `EditConfigOperation`, `GetConfigOperation`).
2. **Target Configuration Model (`config/model.py`)**:
   * Update `SessionConfig` (or equivalent target configuration class) to include:
     ```python
     operations: List[OperationConfig] = Field(default_factory=list)
     ```
   * Add a migration helper or validator: If a legacy single `operation: "..."` is provided, automatically convert it into a single-element list in `operations` to preserve backward compatibility during development.
   * Ensure credentials and transport parameters (`username`, `password`, `key_filename`, `hostkey_verify`, `timeout`) remain strictly scoped to connection setup.

### B. Worker & Execution Engine (`managers/unary_worker.py`, `managers/factory.py`, `managers/manager.py`)

1. **Single Connection Session Lifecycle**:
   * Update the execution worker so that all operations defined in `target.operations` are executed sequentially across **one single client connection context**:
     ```python
     with self._get_client() as client:
         results = []
         for operation in target.operations:
             result = client.execute(operation)
             results.append(result)
         return results
     ```
2. **Output Handling & Formatting**:
   * Update `modules/formatter.py` and `modules/output.py` to format and display a list of operation results sequentially (e.g., printing section headers for each operation in the sequence).

### C. Test Fixtures Update (`tests/netconf_*.yaml`)

Refactor all existing NETCONF YAML test files in `tests/` to use the new `operations:` structure:
* `tests/netconf_capability_test.yaml`
* `tests/netconf_get_test.yaml`
* `tests/netconf_get_config_test.yaml`
* `tests/netconf_get_schema_test.yaml`
* `tests/netconf_edit_config_test.yaml`
* `tests/netconf_delete_test.yaml`

Example migration for `tests/netconf_get_schema_test.yaml`:
```yaml
# Before
targets:
  172.20.20.2:830:
    username: "admin"
    password: "NokiaSrl1!"
    operation: "get-schema"
    identifier: "openconfig-interfaces"
    version: "2024-04-04"

# After
targets:
  172.20.20.2:830:
    username: "admin"
    password: "NokiaSrl1!"
    operations:
      - get-schema:
          identifier: "openconfig-interfaces"
          version: "2024-04-04"
```

### D. Unit Tests (`tests/test_config_models.py`, `tests/test_managers.py`)

1. Update `tests/test_config_models.py` to verify:
   * Parsing a single operation inside the `operations` list.
   * Parsing multiple sequential operations within `operations`.
   * Error raising on invalid operation types or missing mandatory operation arguments.
2. Verify that mock manager tests in `tests/test_managers.py` correctly loop through and execute each operation in `target.operations`.

---

## 4. Implementation Steps

1. **Inspect Existing Parsing**: Review `config/model.py` and `config/operations.py` to see how target dictionaries are currently mapped to configuration models.
2. **Update Models**:
   * Introduce the `operations` field on target configuration.
   * Create parsing logic mapping dictionary keys (`get`, `get-config`, `edit-config`, `get-schema`) to their respective operation model classes.
3. **Update Worker Execution**:
   * Ensure `UnaryWorker` (or equivalent execution manager) receives the list of operations and iterates over them within the active client session.
4. **Update YAML Fixtures**:
   * Rewrite all `tests/netconf_*.yaml` files to the new `operations` syntax.
5. **Run Tests**:
   * Run `pytest tests/` to confirm that all test suites pass with the new YAML schema.

---

## 5. Acceptance Criteria

- [ ] All `tests/netconf_*.yaml` files use the `operations:` list format.
- [ ] The configuration parser accepts multiple sequential operations per target.
- [ ] Operation parameters (`identifier`, `filter`, `config`, etc.) are isolated inside their specific operation blocks.
- [ ] Multiple operations under a single target execute sequentially within one persistent connection lifecycle.
- [ ] All `tests/gnmi_*.yaml` files to check gNMI Client handler doesn't affect this change.
- [ ] All existing test suites pass (`pytest tests/`).