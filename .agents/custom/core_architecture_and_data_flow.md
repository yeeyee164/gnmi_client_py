Data flow
====

```text
[ CLI Input / YAML Config ] (ParsedConfig)
            │
            ▼
       [ ui/cmd.py ]  ──────────> Creates [ SessionConfig ] (SessionConfig in {ConnectionConfig, ExecutionConfig, OperationConfig})[for each operation and defined RPCs]
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

Workers (BaseUnaryWorker, SubscribeSession) are protocol-agnostic. They use defined classes in `config` directory.

Modules
-------

Security credentials and options are encapsulated inside `SecurityProfile` / `SecurityModule` in `modules/security.py`.
* But it's not yet fully implemented - Need to test

Clients
-------


#### gNMI Client

Fully functional across `capability`, `get`, `set`, and `subscribe` (stream, once, poll).

#### NETCONF Client

Phase 1:
* Implemented in `specs/client.py`.
* Supports `<capabilities>` (client.capabilities()).
* Supports `<get>`, `<get-config>`, and RFC 6022 `<get-schema>`.
* Added `RPCError` handling to capture router `<rpc-error>` replies and parse the resulting `lxml` nodes cleanly into JSON dictionaries using `NETCONFFormatter` in `modules/formatter.py`.
* `ManagerFactory` routes `get`, `get-config`, and `get-schema` to `GetWorker`.

Phase 2 In-Progress:
* Refactor protocol configuration.
* Supports NETCONF `<edit-config>` RPC.
* Supports NETCONF `<edit-config>` RPC with operations.