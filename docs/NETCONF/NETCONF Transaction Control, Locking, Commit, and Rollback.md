# NETCONF Transaction Control, Locking, Commit, and Rollback

## Objective

Extend the NETCONF implementation from basic `<edit-config>` support into a complete candidate-datastore transaction workflow.

This phase must support:

- `<lock>` / `<unlock>` from RFC 6241 §7.5 / §7.6
- `<commit>` from RFC 6241 §8.3 / §8.4
- confirmed commit
- `<cancel-commit>`
- `<discard-changes>`
- optional `<validate>` before commit
- automatic rollback of an unsuccessful candidate transaction
- guaranteed lock release

The implementation must preserve the current architecture:

```text
CLI / YAML
    ↓
SessionConfig
    ↓
OperationConfig / NetconfOptions
    ↓
Manager
    ↓
Worker
    ↓
NetconfClient
    ↓
ncclient
    ↓
NETCONF RPC
```

Protocol-specific transaction behavior must remain inside `NetconfClient`, not in managers.

---

## 1. Supported NETCONF transaction operations

Step 3 must support the following NETCONF operations.

| Operation           | RFC 6241 | Purpose                                        |
| ------------------- | -------- | ---------------------------------------------- |
| `<lock>`            | §7.5     | Obtain exclusive access to a datastore         |
| `<unlock>`          | §7.6     | Release a datastore lock                       |
| `<commit>`          | §8.3     | Apply candidate configuration to running       |
| `<cancel-commit>`   | §8.3     | Cancel an active confirmed commit              |
| `<discard-changes>` | §8.3     | Revert candidate changes                       |
| `<validate>`        | §8.6     | Validate candidate configuration before commit |

`<validate>` is included because it is required for the `--validate` transaction workflow already defined by Step 3.

---

# 2. Extend NETCONF options

Update:

```text
config/protocol_options/netconf.py
```

`NetconfOptions` should contain the transaction-related options required by Step 3.

Recommended fields:

```python
target_datastore: str = "candidate"

commit: bool = True

lock_target: bool = False

validate_candidate: bool = False

confirmed: bool = False

confirm_timeout: Optional[int] = None
```

The existing fields such as:

```python
default_operation
error_option
test_option
config
source
```

must remain supported.

> [!NOTE]
> `validate_candidate` is named to avoid shadowing `NetconfOptions.validate(self)` and breaking polymorphic validation invocations (`OperationConfig.validate()` -> `protocol_options.validate()`). CLI flag `--validate` maps directly to this option field.

### Validation

Add validation for:

- `confirm_timeout > 0` when supplied
- `confirmed=True` requires candidate transaction semantics
- `lock_target` is boolean
- `validate_candidate` is boolean

Do not silently invent unsupported combinations.

---

# 3. CLI options

Update the NETCONF `edit-config` command in:

```text
ui/cmd.py
```

The existing options remain:

```text
--target / --target-datastore
--config
--default-operation
--error-option
--test-option
--no-commit
```

Add:

```text
--lock
--validate
--confirmed
--confirm-timeout
```

Example:

```bash
client netconf edit-config \
    --target candidate \
    --config router.xml \
    --lock \
    --validate
```

Confirmed commit:

```bash
client netconf edit-config \
    --target candidate \
    --config router.xml \
    --lock \
    --confirmed \
    --confirm-timeout 300
```

The CLI parser must pass these values into `NetconfOptions`.

Do not implement transaction behavior directly in `ui/cmd.py`.

---

# 4. Add explicit transaction operations

In addition to transaction flags attached to `edit-config`, expose the individual NETCONF transaction operations.

The implementation should support commands conceptually equivalent to:

```text
netconf commit
netconf cancel-commit
netconf discard-changes
```

Each command should accept the datastore where applicable.

For example:

```bash
client netconf commit
client netconf cancel-commit
client netconf discard-changes
```

> [!NOTE]
> Either `netconf lock` or `netconf unlock` will not support in CLI. See IMPORTANT below.

It can also configure via YAML like:

```yaml
targets:
  172.20.20.2:830:
    username: "admin"
    password: "NokiaSrl1!"
    protocol: "netconf"
    operations:
      # <lock>
      - lock:
          target: "candidate"

      # <validate>
      - validate:
          source: "candidate"

      # <commit>
      - commit:
          # requires ":confirmed-commit:1.1" capability
          confirmed: false
          confirm_timeout: 30 # seconds
          persist: "token_id"
          persist_id: "token_id"

      # <cancel-commit>
      - cancel-commit:
          persist_id: "token_id"

      # <unlock>
      - unlock:
          target: "candidate"

      # <discard-changes>
      - discard-changes:
```


These operations should eventually map to explicit operation objects rather than being represented as arbitrary strings.

> [!IMPORTANT]
> **RFC 6241 Session-Scoped Locks vs CLI Execution Lifecycle:**
> In NETCONF (RFC 6241 §7.5), datastore locks are bound to the specific SSH transport session. When a session terminates, the server automatically releases the lock.
> In this client engine, standalone CLI commands establish a connection, execute the RPC, and close the session upon exit. Therefore, running a standalone CLI command such as `client netconf lock` will release the lock immediately upon process exit!
> - **Multi-operation YAML sequences** executed via `SequentialWorker` share a single long-lived session, making granular `- lock`, `- edit-config`, `- commit`, and `- unlock` operations fully viable.
> - **CLI commands** should primarily rely on the **compound transaction flags** on `edit-config` (`--lock`, `--validate`, `--confirmed`), which encapsulate the entire lifecycle inside a single session.
> - Standalone CLI commands for `commit` and `cancel-commit` are most useful across sessions when combined with `persist-id` (RFC 6241 §8.3.4.1).

Recommended semantic model:

```python
class TransactionType(str, Enum):
    LOCK = "lock"
    UNLOCK = "unlock"
    COMMIT = "commit"
    CANCEL_COMMIT = "cancel-commit"
    DISCARD_CHANGES = "discard-changes"
    VALIDATE = "validate"
```

and a corresponding operation configuration:

```python
@dataclass(frozen=True, kw_only=True)
class TransactionOperation(OperationConfig):
    operation: TransactionType
    confirmed: bool = False
    confirm_timeout: Optional[int] = None

@dataclass(frozen=True, kw_only=True)
class NetconfTransactionOperation(TransactionOperation):
    target_datastore: str = "candidate"
    source_datastore: str = "candidate"
    persist: str = ""
    persist_id: str = ""
```

Even through these operations are NETCONF-specific, there has a northbound protocol that supports similar kinds of transactions.
* gNMI extension supports commit operations.

---

# 5. Implement transaction methods in `NetconfClient`

Update:

```text
specs/netconf_client.py
```

Add small, direct wrappers around ncclient.

### `<lock>`

```python
def lock(self, target: str = "candidate"):
    return self.session.lock(target=target)
```

### `<unlock>`

```python
def unlock(self, target: str = "candidate"):
    return self.session.unlock(target=target)
```

### `<commit>`

Support both normal and confirmed commits:

```python
def commit(
    self,
    confirmed: bool = False,
    confirm_timeout: Optional[int] = None,
    persist: Optional[str] = None,
    persist_id: Optional[str] = None,
):

    self._check_capability(":candidate")
    kwargs = {}
    if confirmed:
        self._check_capability(":confirmed-commit")
        kwargs["confirmed"] = True
        if confirm_timeout is not None:
            kwargs["timeout"] = str(confirm_timeout)
        if persist is not None:
            kwargs["persist"] = persist
    if persist_id is not None:
        kwargs["persist_id"] = persist_id

    return self.session.commit(**kwargs)
```

The implementation must not emulate confirmed commit locally. The NETCONF server must receive the appropriate `<commit>` parameters.

### `<cancel-commit>`

```python
def cancel_commit(self, persist_id: Optional[str] = None):
    self._check_capability(":candidate")
    kwargs = {"persist_id": persist_id} if persist_id else {}
    return self.session.cancel_commit(**kwargs)
```

### `<discard-changes>`

```python
def discard_changes(self):
    self._check_capability(":candidate")
    return self.session.discard_changes()
```

### `<validate>`

```python
def validate(self, source: str = "candidate"):
    return self.session.validate(source=source)
```

All RPC errors must propagate consistently with the existing `NetconfClient` error-handling model.

---

# 6. Refactor the current automatic commit behavior

This is an important part of Step 3.

The current `NetconfClient.set()` automatically performs:

```python
self.session.edit_config(...)
self.session.commit()
```

when the target is `candidate`.

Do not leave this behavior unchanged while adding explicit transaction handling.

Otherwise this sequence could accidentally occur:

```text
edit-config
    ↓
automatic commit
    ↓
explicit validate
    ↓
explicit commit
```

which defeats the transaction model.

Refactor `set()` so that it performs:

```text
edit-config
```

and transaction handling is explicitly controlled by the Step 3 options.

For example:

```text
edit-config
    ↓
optional validate
    ↓
commit
```

The exact API boundary may remain:

```python
execute_set(SetOperation)
```

but `NetconfClient` must own the NETCONF transaction sequence.

---

# 7. Candidate transaction workflow

For:

```text
target == candidate
```

the normal workflow must be:

```text
                  ┌─────────────┐
                  │   lock()    │
                  └──────┬──────┘
                         ↓
                  ┌─────────────┐
                  │ edit-config  │
                  └──────┬──────┘
                         ↓
                 --validate?
                    /       \
                  yes        no
                   ↓          ↓
               validate       │
                   \          /
                    ↓        ↓
                  ┌─────────────┐
                  │   commit()  │
                  └──────┬──────┘
                         ↓
                  ┌─────────────┐
                  │  unlock()   │
                  └─────────────┘
```

The lock must be released regardless of the result.

Therefore the implementation must use `try/finally`.

Conceptually:

```python
locked = False

try:
    if lock_target:
        self.lock(target)
        locked = True

    res = self.session.edit_config(...)

    if target == "candidate":
        if validate_candidate:
            self.validate(source="candidate")

        if commit:
            self.commit(
                confirmed=confirmed,
                confirm_timeout=confirm_timeout,
                persist=persist,
                persist_id=persist_id,
            )

    return res

except Exception:
    # Only candidate datastore supports discard-changes; running cannot be discarded via RFC 6241
    if target == "candidate":
        try:
            self.discard_changes()
        except Exception as discard_err:
            logger.warning(f"[NetconfClient] Failed to discard candidate changes during error cleanup: {discard_err}")
    raise

finally:
    if locked:
        self.unlock(target)
```

Do not duplicate this logic in `SetWorker`.

---

# 8. Failure handling

If any transaction stage fails:

```text
lock
edit-config
validate
commit
```

the implementation must attempt:

```text
discard-changes
```

when the transaction is using the candidate datastore.

Example:

```text
lock
  ↓
edit-config
  ↓
validate
  ↓
FAIL
  ↓
discard-changes
  ↓
unlock
```

The original exception must not be hidden by a secondary `discard-changes` or `unlock` failure.

Therefore:

1. Preserve the original exception.
2. Attempt `discard-changes()`.
3. Log a failure if discard itself fails.
4. Always attempt `unlock()`.
5. Return/raise the original transaction error.

Do not convert every error into a generic string.

---

# 9. Confirmed commit

Support:

```text
--confirmed
--confirm-timeout <seconds>
```

Normal commit:

```text
<commit/>
```

Confirmed commit:

```text
<commit>
    <confirmed/>
    <confirm-timeout>...</confirm-timeout>
</commit>
```

The client must delegate this to ncclient rather than constructing XML manually.

Example:

```python
self.commit(
    confirmed=True,
    confirm_timeout=300,
)
```

Capability handling must be added.

Before using confirmed commit, verify that the server advertises the NETCONF confirmed-commit capability.

If the capability is absent, fail clearly rather than silently ignoring `--confirmed`.

---

# 10. Cancel confirmed commit

Expose `<cancel-commit>` as a standalone transaction operation.

Example:

```bash
client netconf cancel-commit
```

The client must call:

```python
session.cancel_commit()
```

Do not implement cancellation by calling normal `<commit>`.

Capability support should be checked before attempting the operation.

---

# 11. Discard candidate changes

Expose:

```bash
client netconf discard-changes
```

which maps directly to:

```python
session.discard_changes()
```

This is different from automatic error recovery.

It has two use cases:

### Explicit user action

```text
edit-config
    ↓
user decides not to commit
    ↓
discard-changes
```

### Automatic failure recovery

```text
edit-config
    ↓
validate/commit fails
    ↓
discard-changes
```

Both should use the same `NetconfClient.discard_changes()` implementation.

---

# 12. Lock/unlock behavior

For `--lock`:

```text
lock(target)
```

must happen before `<edit-config>`.

For example:

```text
lock(candidate)
edit-config(candidate)
validate(candidate)
commit()
unlock(candidate)
```

`unlock()` must be executed from a `finally` block.

This requirement applies even when:

- `<edit-config>` fails
- `<validate>` fails
- `<commit>` fails
- `discard-changes` fails
- an unexpected Python exception occurs

Do not unlock only on the successful path.

---

# 13. Capability checks

Before performing optional operations, inspect:

```python
self.session.server_capabilities
```

Relevant capabilities include:

```text
:candidate
:validate
:confirmed-commit
```

At minimum:

| Feature             | Capability          |
| ------------------- | ------------------- |
| candidate datastore | `:candidate`        |
| validate            | `:validate`         |
| confirmed commit    | `:confirmed-commit` |

Do not silently fall back from an explicitly requested transaction feature.

For example:

```text
--confirmed
```

must not become an ordinary commit when `:confirmed-commit` is unavailable.

Likewise:

```text
--validate
```

must fail clearly when validation is requested but unsupported.

---

# 14. Manager / Worker integration

The manager layer must remain protocol-agnostic.

Do not add code such as:

```python
if protocol == "netconf":
    client.commit()
```

to `managers/manager.py`.

Instead, the worker should receive the semantic operation and invoke the protocol adapter.

For standalone transaction operations:

```text
NetconfTransactionOperation
        ↓
ManagerFactory
        ↓
TransactionWorker
        ↓
NetconfClient
        ↓
ncclient
```

A dedicated worker is preferable to adding more NETCONF-specific branches to `SetWorker`.

For example:

```python
class TransactionWorker(BaseUnaryWorker):
    def start(self):
        with self._get_client() as client:
            return client.execute_transaction(self.operation)
```

The NETCONF-specific dispatch remains inside the protocol adapter.

### Polymorphic Dispatch in `BaseClient`

To maintain protocol-agnostic architecture across managers:
1. `BaseClient` defines:
   ```python
   def execute_transaction(self, operation: NetconfTransactionOperation) -> Any:
       raise UnsupportedOperationError(f"{self.__class__.__name__} does not support transaction operations.")
   ```
2. In `BaseClient.execute(self, operation: Any)`:
   ```python
   elif isinstance(operation, NetconfTransactionOperation):
       return self.execute_transaction(operation)
   ```
3. In `UnaryManager._resolve_worker(self, sc: Any)`:
   - If `len(operations) > 1`: routes to `SequentialWorker(config=sc)`.
   - If `len(operations) == 1` and `isinstance(op, NetconfTransactionOperation)`: routes to `TransactionWorker(config=sc)`.

### Sequential Multi-Operation Pipelines (`SequentialWorker`)

When users define chained operations in YAML (`operations: [lock, edit-config, validate, commit, unlock]`), all operations execute within a single sustained connection session via `SequentialWorker`.
> [!IMPORTANT]
> **Short-Circuit on Failure:** `SequentialWorker` must not blindly proceed to commit if an earlier `edit-config` or `validate` step fails. Upon any step returning an error or raising an exception, `SequentialWorker` should:
> 1. Halt execution of remaining steps.
> 2. If the candidate datastore was targeted, attempt `session.discard_changes()`.
> 3. Ensure any held datastore lock is released (`session.unlock()`).

---

# 15. Keep `SetOperation` semantic

`SetOperation` should continue to represent configuration mutation:

```python
SetOperation(
    changes=...
)
```

It should not acquire methods such as:

```python
set.commit()
set.lock()
set.unlock()
```

Transaction behavior belongs in NETCONF options / transaction operations.

This keeps the existing architecture:

```text
SetOperation
    = configuration intent

NetconfOptions
    = NETCONF-specific execution behavior

NetconfTransactionOperation
    = explicit NETCONF transaction control
```

---

# 16. Error handling contract

NETCONF RPC errors must remain distinguishable from normal Python failures.

The implementation should not unnecessarily convert:

```python
operations.RPCError
```

into a string.

Recommended flow:

```python
try:
    ...
except operations.RPCError:
    ...
    raise
except Exception:
    ...
    raise
```

The worker can continue to perform the project's existing output formatting, but transaction cleanup must happen before the error reaches the worker.

---

# 17. Tests

Add tests covering every transaction operation.

Recommended test groups:

### Lock

```text
lock(candidate)
unlock(candidate)
```

Verify:

- correct target
- correct ncclient method
- RPC errors propagate

### Commit

Test:

```text
commit()
commit(confirmed=True)
commit(confirmed=True, confirm_timeout=300)
```

Verify generated ncclient arguments.

### Cancel commit

Verify:

```python
session.cancel_commit()
```

### Discard changes

Verify:

```python
session.discard_changes()
```

### Validate

Verify:

```python
session.validate(source="candidate")
```

### Successful transaction

Expected order:

```text
lock
edit-config
validate
commit
unlock
```

### Failed edit-config

Expected order:

```text
lock
edit-config
discard-changes
unlock
```

### Failed validation

Expected order:

```text
lock
edit-config
validate
discard-changes
unlock
```

### Failed commit

Expected order:

```text
lock
edit-config
validate
commit
discard-changes
unlock
```

### Cleanup failure

Verify that:

```text
discard-changes failure
```

does not prevent:

```text
unlock
```

from being attempted.

Also verify that the original transaction error remains the primary error.

### No lock requested

Expected:

```text
edit-config
validate
commit
```

There must be no calls to:

```text
lock
unlock
```

### No commit requested

For:

```text
--no-commit
```

expected:

```text
edit-config
```

with no commit.

For a candidate datastore, the caller must be able to subsequently execute:

```text
commit
```

or:

```text
discard-changes
```

explicitly.

---

# 18. Acceptance criteria

Step 3 is complete when all of the following are true.

### Basic transaction operations

- [ ] `<lock>` is supported.
- [ ] `<unlock>` is supported.
- [ ] `<commit>` is supported.
- [ ] `<cancel-commit>` is supported.
- [ ] `<discard-changes>` is supported.
- [ ] `<validate>` is supported for candidate transactions.

### Candidate workflow

- [ ] `--lock` locks before `<edit-config>`.
- [ ] `unlock()` always executes in `finally`.
- [ ] `--validate` validates the candidate before commit.
- [ ] successful candidate transactions commit.
- [ ] failed candidate transactions attempt `discard-changes`.

### Confirmed commit

- [ ] `--confirmed` is supported.
- [ ] `--confirm-timeout` is supported.
- [ ] confirmed-commit capability is checked.
- [ ] `<cancel-commit>` is independently executable.

### Architecture

- [ ] No NETCONF transaction logic is added to `ManagerFactory`.
- [ ] No NETCONF XML transaction construction is added to the manager layer.
- [ ] `NetconfClient` owns NETCONF RPC translation.
- [ ] `SetWorker` does not contain lock/commit/rollback sequencing.
- [ ] Existing gNMI behavior is unaffected.
- [ ] Existing `SetOperation` remains protocol-agnostic.

### Regression

- [ ] Existing `<get>`, `<get-config>`, `<get-schema>`, and `<edit-config>` tests continue to pass.
- [ ] Existing gNMI tests continue to pass.
- [ ] New transaction tests verify both successful and failure paths.
- [ ] The current automatic candidate commit behavior is removed/refactored so that Step 3 does not produce duplicate commits.

---

## Final transaction model

The intended NETCONF transaction model after Step 3 is:

```text
                    User
                     │
                     ▼
              edit-config
                     │
             ┌───────┴───────┐
             │               │
          --lock          no --lock
             │               │
             └───────┬───────┘
                     ▼
                 <lock>
                     │
                     ▼
              <edit-config>
                     │
                     ▼
              --validate?
                /       \
              yes        no
               │          │
               ▼          │
            <validate>    │
               │          │
               └────┬─────┘
                    ▼
               --commit?
                /       \
              yes        no
               │          │
               ▼          ▼
           <commit>   leave candidate
               │
               ▼
           <unlock>
```

Failure path:

```text
             transaction failure
                     │
                     ▼
             <discard-changes>
                     │
                     ▼
                <unlock>
```

Explicit transaction control:

```text
<lock>
<unlock>
<commit>
<cancel-commit>
<discard-changes>
```

This makes Step 3 a complete NETCONF transaction-control layer rather than merely adding an automatic `commit()` after `<edit-config>`.
