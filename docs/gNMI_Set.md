# **Antigravity Task Brief: gNMI Set Operation Implementation**

## **1\. System Role & Project Context**

You are acting as a **Senior Network Automation Software Architect and Principal Core Maintainer** working on the gnmi\_client\_py repository.

### **Architectural Invariants & Recent State (managing\_session\_2)**

1. **Decoupled Session Configurations (docs/session\_config\_RPC\_separation.md):**  
   * The codebase has completely eliminated monolithic SessionConfig / ParsedConfig anti-patterns.  
   * Session configs are segregated per RPC and protocol using @dataclass(kw\_only=True):  
     * BaseSetSessionConfig(BaseSessionConfig): Common set fields (updates, replaces, deletes, prefix).  
     * GNMISetSessionConfig(BaseSetSessionConfig): Protocol-specific fields (e.g., encoding \= "json\_ietf").  
   * Every worker thread operates in complete isolation on its own dedicated session config. **Do NOT reintroduce global mutable state or cross-RPC parameter pollution.**  
2. **Worker Purity & Universal Pass-Through:**  
   * Workers (SetWorker in managers/unary\_worker.py) remain 100% protocol-agnostic.  
   * SetWorker performs offline path validation and immediately dispatches execution via client.set(\*\*self.kwargs).  
   * Protobuf construction (gnmi\_pb2.SetRequest, gnmi\_pb2.TypedValue, gnmi\_pb2.Path) and gRPC channel communications belong **exclusively** inside specs/client.py.

## **2\. Specification Standards: OpenConfig gNMI Section 3.4 Reference**

All implementation work must strictly conform to [OpenConfig gNMI Specification Section 3.4 (Modifying State)](https://github.com/openconfig/reference/blob/master/rpc/gnmi/gnmi-specification.md#34-modifying-state).

*(Note: Per design requirement, union\_replace is intentionally out of scope and must NOT be considered.)*

### **Key Semantic Rules from Section 3.4**

1. **Section 3.4.1 (SetRequest):**  
   * Fields: prefix (Path), delete (repeated Path), replace (repeated Update), update (repeated Update).  
   * An Update message contains path (Path) and val (TypedValue).  
   * A single request MUST NOT specify origin in both prefix and path fields (Section 2.7).  
2. **Section 3.4.2 (SetResponse):**  
   * Returns prefix (Path), response (repeated UpdateResult), and timestamp (nanoseconds since Unix epoch).  
   * Each UpdateResult contains:  
     * timestamp: time at which the change was accepted by the target.  
     * path: the affected path.  
     * op: enum representing the operation executed (DELETE \= 1, REPLACE \= 2, UPDATE \= 3).  
     * message: status / error details if applicable.  
3. **Section 3.4.3 (Transactions & Execution Ordering):**  
   * All modifications in a SetRequest message MUST be treated as a single atomic transaction.  
   * Logical execution order defined by the specification:  
     1. **delete** operations are processed first.  
     2. **replace** operations are applied second.  
     3. **update** operations are applied third.  
   * If any operation within the transaction fails, the entire transaction MUST be rolled back, and an error returned.  
4. **Section 3.4.4 (Update vs. Replace Semantics):**  
   * **replace:** Overwrites the node at path with val. Any existing child elements of the node at path that are **not** present in val are **implicitly deleted**.  
   * **update:** Merges elements within the node at path. Only the specific attributes defined in val are updated or created; unreferenced child or sibling elements remain intact.  
5. **Section 3.4.5 (Paths Identified by Attributes):**  
   * List elements must be uniquely addressed using all schema-defined key attributes (e.g., /interfaces/interface\[name=\"eth0\"\]).  
   * **Strict Prohibition:** In accordance with Section 2.2.2.1 and Section 3.4, wildcard elements (\*, ...) and wildcard key values (\[name=\*\]) are **strictly forbidden** in all SetRequest paths.  
6. **Section 3.4.6 (Deleting Configuration):**  
   * Deleting a non-existent path MUST be treated as successful (idempotent / no-op) by the target.  
   * Deleting a parent node recursively removes all child nodes.  
7. **Section 3.4.7 (Error Handling):**  
   * Errors MUST be represented using canonical gRPC status codes (grpc.StatusCode).  
   * The client must trap grpc.RpcError and extract code, details, and message information to return structured failure diagnostics to the user without crashing the runtime.

## **3\. Step-by-Step Implementation Directives**

Execute the following implementation phases in sequential order. Provide planned unified diffs for review prior to writing or modifying files.

### **Step 1: Configuration Ingestion & Dataclass Alignment (ui/cmd.py)**

**Objective:** Ingest CLI arguments and YAML configuration blocks into GNMISetSessionConfig.

**Tasks:**

1. **Verify GNMISetSessionConfig:**  
   * Confirm that GNMISetSessionConfig inherits from BaseSetSessionConfig and cleanly exposes:  
     updates: list \= field(default\_factory=list)  
     replaces: list \= field(default\_factory=list)  
     deletes: list \= field(default\_factory=list)  
     prefix: str \= ""  
     encoding: str \= "json\_ietf"

2. **CLI Parsing (gnmi set subparser in ui/cmd.py):**  
   * \--update / \--replace: Support syntax PATH:::VALUE:  
     * Support scalar values: /system/config/hostname:::switch-01  
     * Support inline JSON strings. (e.g., `/interfaces/interface[name="eth4"]/config:::{"description": "Uplink", "enabled": true}`)
       * NOTE: I wrapped list of key `name` to double quotation because this leaf has a type `string` in YANG. But do not consider YANG type validation.
     * Support disk payload references using @ syntax: `/system/aaa:::path/to/payload.json` or `/system/aaa:::@path/to/payload.json`
   * \--update-path + \--update-value / \--replace-path + \--replace-value: Support paired string request.
     * Each path should point to leaf and also have following value
     * e.g., --update-path `/interfaces/interface[name="lo123"]/config/description` --update-value "Loopback123123"
   * \--update-path + \--update-file / \--replace-path + \--replace-file: Support paired string request.
     * Each path should point to writable container/list
     * File has same meaning as given by `@` syntax.
     * e.g., --update-path `/interfaces/interface[name="lo123"]/config` --update-file `path/to/json-file`
   * \--delete: Accept repeated path strings (e.g., `--delete "/interfaces/interface[name=\"Loopback0\"]"`).
   * \--prefix: Accept a string representing the gNMI base path prefix.  
   * Normalize input into lists of (path, value) tuples for updates/replaces, and path strings for deletes.  

3. **YAML Parsing (FileConfigBuilder for gNMI):**  
   * In target operation blocks with operation: set (or type: set), parse the set: structure:  
     ```yaml
     operation: set  
     set:  
       prefix: "/openconfig-interfaces:interfaces"  
       update:  
          "interface[name=\"eth3\"]/config":  
            description: "Transit-Link"
            enabled: true
        replace:
          "interface[name=\"Loopback0\"]/config":
            description: "Primary Loopback"  
        delete:  
          - "interface[name=\"eth3\"]/config/description"
          - "interface[name=\"eth3\"]/config"
     ```

   * Convert YAML mappings into structured (path, value) lists inside `GNMISetSessionConfig`.

### **Step 2: Offline Semantic & Path Validation (specs/gnmi\_validator.py & managers/unary\_worker.py)**

**Objective:** Enforce gNMI Section 3.4.5 rules offline before dispatching network calls.

**Tasks:**

1. **In specs/gnmi\_validator.py:**  
   * Enforce Section 3.4.5: If operation \== 'set', reject any path containing wildcards (\* or ...) in element names or key values (\[key=\*\]). Raise PathValidationError.  
   * Ensure origin prefixes (e.g., openconfig:) are stripped or validated consistently with Section 2.7.  
2. **In managers/unary\_worker.py (SetWorker):**  
   * Ensure \_validate\_paths() extracts path strings properly from prefix, deletes, replaces, and updates (handling tuples (path, val) and dictionary mappings).  
   * Reject invalid requests immediately, preventing wasted gRPC connection handshakes.

### **Step 3: Protobuf Construction & Error Handling (specs/client.py)**

**Objective:** Complete GNMIClient.set() to construct a compliant gnmi\_pb2.SetRequest and execute the RPC.

**Tasks:**

1. **Signature Alignment:**  
   def set(self, updates: list \= None, replaces: list \= None, deletes: list \= None, prefix: str \= "", \*\*kwargs) \-\> Any:

2. **Prefix & Delete Construction:**  
   * If prefix is provided, parse via parse\_path(prefix) and assign to request.prefix.  
   * For each path in deletes: parse via parse\_path(path) and append to request.delete.  
3. **Robust TypedValue Serialization (\_build\_typed\_val):**  
   * Build a robust converter translating Python inputs into gnmi\_pb2.TypedValue:  
     * **File References (@filename):** If value is a string pointing to an existing file, read the file bytes.  
     * **Dictionaries & Lists:** Serialize via json.dumps(val).encode('utf-8') and assign to tv.json\_ietf\_val (or tv.json\_val if specified by encoding).  
     * **JSON Strings:** If a string can be decoded as JSON (object or list), store raw bytes in tv.json\_ietf\_val.  
     * **Booleans:** tv.bool\_val \= bool(val) (ensure strict boolean check before integers, as isinstance(True, int) is True in Python).  
     * **Integers:** tv.int\_val \= int(val) (or tv.uint\_val if unsigned range).  
     * **Floats:** tv.float\_val \= float(val).  
     * **Fallback:** tv.string\_val \= str(val).  
4. **Update & Replace Assembly:**  
   * For each (path, val) in updates: create an Update entry with path and val.  
   * For each (path, val) in replaces: create an Update entry under request.replace.  
5. **Execution & RPC Error Handling (Section 3.4.7):**  
   * Execute self.stub.Set(request, metadata=self.metadata).  
   * Catch grpc.RpcError:  
     * Extract code \= e.code() and details \= e.details().  
     * Return structured diagnostic payload or a typed exception so SetWorker can return error context rather than crashing unhandled.

### **Step 4: Structured Output Formatting (modules/formatter.py)**

**Objective:** Parse gnmi\_pb2.SetResponse into standardized JSON/ASCII representations adhering to gNMI Section 3.4.2.

**Tasks:**

1. In modules/formatter.py (GNMIFormatter.\_format\_set):  
   * Extract timestamp (nanoseconds) and format ISO 8601 UTC string:  
     datetime.datetime.fromtimestamp(resp.timestamp / 1e9, tz=datetime.timezone.utc).isoformat()

   * Extract prefix if present.  
   * Parse resp.response (UpdateResult list):  
     * Map operation enum: 0: "INVALID", 1: "DELETE", 2: "REPLACE", 3: "UPDATE".  
     * Capture stringified path and any message / status details.  
2. Maintain standard outer envelope structure (source, timestamp, rpc: "set", data).

## **4\. Architectural Guardrails & Development Constraints**

1. **Protocol Strictness:**  
   * grpc and gnmi\_pb2 imports MUST NOT exist outside of specs/client.py and modules/security.py.  
2. **Worker Agnosticism:**  
   * SetWorker must never construct protobufs or inspect gnmi\_pb2. It merely validates paths and passes \*\*self.kwargs directly to client.set(\*\*self.kwargs).  
3. **No Dataclass Ordering Regressions:**  
   * Always use @dataclass(kw\_only=True) when modifying any \*SessionConfig to maintain inheritance integrity.  
4. **Two-Stage Review Gate:**  
   * Present proposed unified diffs of specs/client.py, ui/cmd.py, and modules/formatter.py for review before applying changes to disk.