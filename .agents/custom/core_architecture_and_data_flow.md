Data flow
====

```text
[ CLI Input / YAML Config ]
            │
            ▼
       [ ui/cmd.py ]  ──────────> Creates [ SessionConfig ] (GNMISessionConfig / NetconfSessionConfig)[for each operation]
            │
            ▼
   [ ManagerFactory ]
        ├── UnaryManager            ───> Spawns Worker Threads [ GetWorker / SetWorker / CapabilitiesWorker ]
        └── SubscriptionManager     ───> Spawns Worker Threads [ SubscribeSession ]
                                                │
                                                ▼
                                        [ ClientFactory ]
                                        ├── GNMIClient (BaseClient)    ──> HTTP/2 (gRPC)
                                        └── NetconfClient (BaseClient) ──> SSH / TLS (ncclient)
                                                │
                                                ▼
                                        [ OutputHandler ]
                                        └── Formatter (GNMIFormatter / NETCONFFormatter)
```

Architecture Decoupling
=======================


Workers
-------

Workers (BaseUnaryWorker, SubscribeSession) are protocol-agnostic. They use **kwargs pass-through to send options directly to client.get(**self.kwargs).

Modules
-------

Security credentials and options are encapsulated inside `SecurityProfile` / `SecurityModule` in `modules/security.py`.
* But it's not yet fully implemented 

Clients
-------


#### gNMI Client

Fully functional across `capability`, `get`, `set`, and `subscribe` (stream, once, poll).
* NOTE: `set` is not fully tested

#### NETCONF Client

Phase 1 In-Progress:
* Implemented in `specs/client.py`.
* Supports `<capabilities>` (client.capabilities()).
* Supports `<get>`, `<get-config>`, and RFC 6022 `<get-schema>`.
* Added `RPCError` handling to capture router `<rpc-error>` replies and parse the resulting `lxml` nodes cleanly into JSON dictionaries using `NETCONFFormatter` in `modules/formatter.py`.
* `ManagerFactory` routes `get`, `get-config`, and `get-schema` to `GetWorker`.