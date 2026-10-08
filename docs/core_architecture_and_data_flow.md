Data and Data flow
====

Data
----

In `config` module, each protocl data defined.
* `config` defines two kinds of classes: Semantic operations and actual protocol operations.

### Semantic Operations

Semantic operations defines 'common' operations for each supported northbound protocols.

### Protocol Operations

Protocol operations defines 'specific' operations per RPCs.


### Relation table

Semantic operation | gNMI | NETCONF 
-------------------|------|--------
`CapabilitesOperation` | `Capabilities` | `<hello>`/capabilities
`GetOperation` | `Get` | `<get>`/`<get-config>`
`SetOperration` | `Set` | `<edit-config>` + optional commit
`GetSchemaOperration` | requires Extensions | `<get-schema>`
`SubscribeOperation` | `Subscribe` | NETCONF notification/subscription(RFC 5277)


Data flow
---------

```text
[ CLI Input / YAML Config ] (ParsedConfig)
            │
            ▼
       [ ui/cmd.py ]  ──────────> Creates [ SessionConfig ] (SessionConfig in {ConnectionConfig, ExecutionConfig, OperationConfig})[for each operation and defined RPCs]
            │
            ▼
   [ ManagerFactory ]
        ├── UnaryManager            ───> Spawns Worker Threads [ GetWorker / SetWorker / CapabilitiesWorker / SequentialWorker ]
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

### SequentialWorker

A worker may hold one or more RPCs which represented by `SessionConfig`. To serve such operation, `SequentialWorker` handles operations via one-shot instruction(YAML).
* NOTE: It only cares Unary RPCs.

Modules
-------

Security credentials and options are encapsulated inside `SecurityProfile` / `SecurityModule` in `modules/security.py`.
* But it's not yet fully implemented - Need to test

Outputs
-------

`OutputHandler` will be created for each information decribed in `OutputType`, and `OutputFormat`.
* They are created ONLY ONCE and for all reply will send a message to handler.


`OutputHandler` creates `Formatter` classes for each given protocols.

```text

                [ SessionConfig ] * (no of requests)
                                │
                  message(Dict)={protocol:, ...}
                                │
                                ▼
                        [ OutputHandler ]
                                │
                     OutputFormat, OutputType
                                │
                                ▼
                 (GNMIFormatter, NETCONFFormatter)
                                │
        ┌─────────────────────────────────────────────────┐
        │                       │                         │
  OutputType(STD)         OutputType(File)         OutputType(SYSLOG)
        │                       │                         │
        ▼                       ▼                         ▼
   prints to terminal     prints to file           creates SYSLOG Client(IP, PORT)
                                                          │
                                                          ▼
                                                    pust data into server

```

Clients
-------


#### gNMI Client

Fully functional across `capability`, `get`, `set`, and `subscribe` (stream, once, poll).
- Extensions are not yet supported.

**plans to be supported extensions**

1. CLI execution(SetRequest)
2. commit(SetRequest)


#### NETCONF Client

Phase 1:
* Implemented in `specs/client.py`.
* Supports `<capabilities>` (client.capabilities()).
* Supports `<get>`, `<get-config>`, and RFC 6022 `<get-schema>`.
* Added `RPCError` handling to capture router `<rpc-error>` replies and parse the resulting `lxml` nodes cleanly into JSON dictionaries using `NETCONFFormatter` in `modules/formatter.py`.
* `ManagerFactory` routes `get`, `get-config`, and `get-schema` to `GetWorker`.

Phase 2:
* Refactor protocol configuration.
* Supports NETCONF `<edit-config>` RPC.
* Supports NETCONF `<edit-config>` RPC with operations.