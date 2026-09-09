Step 1: Phase1 — Verify & Harden Phase 1 (`<get>`, `<get-config>`, `<get-schema>`)
----

### Objective
Ensure all read-only RPCs handle both successful payloads and `<rpc-error>` responses without crashing worker threads or losing diagnostic information.

### Tasks

* Inspect `specs/client.py`: Verify that `--filter` safely accepts raw XML strings, file paths (reading contents automatically), and raw XPath strings.

* Test RFC 6022 `<get-schema>` with various identifiers (e.g., ietf-interfaces, openconfig-interfaces).

* Validate that `modules/formatter.py` cleanly outputs JSON/ASCII for schema definitions and datastores.


Step 2: Phase 2 — Payload Generation & `<edit-config>` (Set Operations)
----

### Objective
Implement the `NetconfClient.set()` method to support configuration modification.

### Tasks

Update `specs/client.py`

* Implement `set(updates: list = None, replaces: list = None, deletes: list = None, **kwargs)`.
    * Do not consider three arguments: updates, replaces, deletes. They're old code segments when I developing gNMI client.

* Extract target datastore (candidate if supported, otherwise running).

* Extract default-operation (merge, replace, none).

* Support passing configuration payloads via XML string or XML file path (kwargs.get('config')).

* Assemble granular `<edit-config>` XML subtrees matching operation tags (operation="merge", operation="replace", operation="delete", operation="remove").

* Update `managers/manager.py`:

* Ensure `ManagerFactory.execute()` routes edit-config to `SetWorker`.

Update `ui/cmd.py`:

* Expose `--target` (candidate/running), `--default-operation`, and `--config` in the netconf edit-config subparser.


Step 3: Phase 3 — Candidate Transactions, Locking, and Atomic Rollback
---- 

### Objective
Implement safe network transactions with exclusive datastore locks, verification, and commits.

### Tasks

#### 1. Add datastore locking

* Support `--lock`: Execute `session.lock(target=target)` before editing and `session.unlock(target=target)` in a finally: block.

#### 2. Add candidate verification and atomic commit
* If the target supports the :candidate capability and `target == 'candidate'`
    * Execute `session.validate(source='candidate')` if `--validate` is passed.
    * Execute `session.commit()` on success.
    * On failure or exception, catch `RPCError` and execute session.`discard_changes()` before releasing locks.

#### 3. Support confirmed commits

* Add flags for `--confirmed` and `--confirm-timeout`.


Step 4: Phase 4 — libyang & Dynamic Schema Discovery
----

### Objective

Replace manual XPath/XML formatting with schema-aware validation and automated namespace resolution.


### Tasks

#### 1. Create `core/schema_manager.py` implementing a thread-safe Singleton SchemaManager.

#### 2. Integrate libyang.Context

* Support loading local YANG repositories (`--yang-dir`).
    * Since this must be used in gNMI as well as NETCONF, it must be handle as a singleton.

* Dynamic Discovery: Connect to `NetconfClient.get(schema=...)` to download models on-the-fly and load them directly into memory via RFC 6022.

#### 3. Implement `NetconfValidator` in `specs/validator.py` and register it in ValidatorFactory (`modules/validate.py`).

* Adopt this validator to gNMI too (`GNMIValidator`)

#### 4. Use `libyang` data trees to serialize high-level Python key-value dictionaries into properly namespaced XML `<edit-config>` subtrees.


Step 5: Phase 5 — NETCONF Event Notifications / Subscriptions (RFC 5277)
----

### Objective

Enable long-lived streaming telemetry and asynchronous event notifications over NETCONF.

### Tasks

#### 1. Implement `NetconfClient.subscribe(request_iterator)`:

* Call `session.create_subscription(stream_name=..., filter=...)`.

* Build a generator loop using `session.take_notification(block=True)` to yield incoming notification XML elements.

#### 2. Wire `NetconfClient.subscribe()` into `managers/subscribe_session.py` to route notifications to `OutputHandler` in real time.