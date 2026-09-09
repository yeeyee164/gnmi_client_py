Protocol Decoupling
----

* Never import `ncclient` inside `managers/` or `ui/`.

* Never import `grpc` or Protobuf stubs inside `managers/` or `ui/`.

* Keep all protocol translation encapsulated inside `specs/client.py`.


Worker agnosticism
----

* Workers (`GetWorker`, `SetWorker`, `SubscribeSession`) must remain universal messengers. They take kwargs from `BaseSessionConfig` and forward them directly to `client.get(**self.kwargs)` or `client.set(**self.kwargs)`.


Graceful Teardown
----

* Always wrap `close_session()` in `try...except` within `BaseClient.__exit__` to prevent router-side socket kills from hiding successful RPC data.

Formatter Standardization
----

* Every protocol client must return raw responses or standard Python types that `formatter.py` translates into identical JSON structures (source, timestamp, data, error).

No Regressions on gNMI
----

* Any change made to `ui/cmd.py`, `managers/manager.py`, `modules/security.py`, or `modules/formatter.py` must retain 100% backward compatibility with gNMI streaming, ONCE, and interactive POLL modes.