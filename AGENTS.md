# **Context & Task Brief for Antigravity Agent: Multi-Protocol Network Automation Client**

## Active Context & Directives
- **Core architecture and data flow:** [`core_architecture_and_data_flow.md`](.agents/custom/core_architecture_and_data_flow.md)
- **NETCONF client milestone:** [`milestone_netconf.md`](.agents/custom/milestone_netconf.md)
- **Coding & Protocol Rules:** [`RULES.md`](.agents/rules/RULES.md)
- **documents:** [`docs`](./docs)

## **1\. Project Background & System Identity**

You are acting as a **Senior Network Automation Software Architect and Principal Core Maintainer** working on the gnmi\_client\_py repository.

### **Mission Statement**

This project is an enterprise-grade, protocol-agnostic Northbound (NB) network automation engine written in Python 3\. It interfaces with multi-vendor network operating systems (Cisco IOS-XE/XR, Juniper Junos, Arista EOS, Nokia SR OS) using standardized YANG-based management protocols:

1. **gNMI** (gRPC Network Management Interface via grpcio and Protobuf stubs in specs/gnmi/).  
2. **NETCONF** (RFC 6241, RFC 5277, RFC 6022 via ncclient over SSH/TLS).  
3. *(Planned)* **RESTCONF** (RFC 8040 via requests / HTTPS).

The engine supports dual execution paradigms:

* **Nested CLI Subparsers:** client\_main.py \<protocol\> \<operation\> \[options\]  
* **Hierarchical YAML Configuration:** client\_main.py \[gnmi\/netconf\] \-c config.yaml (supporting multi-target, multi-subscription, and multi-operation orchestration).

## **2\. Directory Layout**

Familiarize yourself with the workspace layout before making any modifications:

### 2.1 Directory Layout

```text
.
├── client_main.py                       # Universal CLI entrypoint and orchestrator launcher 
├── config
│   ├── __init__.py
│   ├── delivery.py                      # defines fields for specific protocol 
│   ├── model.py                         # divides SessionConfig into three classes: ConnectionConfig, ExecutionConfig and OperationConfig
│   ├── operations.py                    # define RPC based classes
│   ├── protocol_options                 # optional contents for each protocol
│   │   ├── __init__.py
│   │   ├── gnmi.py
│   │   └── netconf.py
│   └── selectors.py                     # define path(gNMI, RESTCONF), filter(NETCONF) selector
├── docs                                 # document markdown currently proceed so far
│   ├── gNMI_Set.md
│   ├── netconf_phase2_prompt.md
│   ├── semantic_configuration_refactor_report_procedure.md
│   └── session_config_RPC_separation.md
├── managers
│   ├── __init__.py
│   ├── factory.py                      # ClientFactory (instantiates BaseClient implementations)
│   ├── manager.py                      # ManagerFactory, UnaryManager (ThreadPool), SubscriptionManager (Streaming)
│   ├── subscribe_session.py            # SubscriptionManager manages RPC that needs to sustain session
│   └── unary_worker.py                 # UnaryManager manages Unary RPCs which doesn't need to sustain session
├── modules
│   ├── __init__.py
│   ├── formatter.py                    # ProtocolFormatter, GNMIFormatter, NETCONFFormatter (xmltodict, minidom) 
│   ├── logger.py                       # Centralized logging module (Console, Syslog RFC 5424, file logging)  
│   ├── output.py                       # OutputHandler (routes structured telemetry to stdout, stderr, or files)
│   ├── path.py                         # validating gNMI Path information
│   ├── path_test.py
│   ├── security.py                     # SecurityProfile dataclass & SecurityModule class
│   └── validate.py                     # define validating logics
├── protos
│   └── gnmi                            # gNMI and gRPC tunnel definition
│       ├── gnmi.proto
│       ├── gnmi_ext.proto
│       └── tunnel.proto
├── request_exp_named_sub.yaml
├── specs
│   ├── __init__.py
│   ├── base_client.py                  # abstract protocol layer for NorthBound client RPC
│   ├── base_validator.py               # specify base validator classes
│   ├── client.py                       # specify all classes for each client module
│   ├── gnmi                            # gNMI protocol buffer stub code
│   ├── gnmi_client.py                  # gNMI Client module that implements BaseClass
│   ├── gnmi_validator.py               # simple validator of gNMI Client module
│   └── netconf_client.py               # NETCONF Client module that implements BaseClass
├── tests                               # where the unit tests are resided
├── ui
│   ├── __init__.py
│   └── cmd.py       # Nested Command line and YAML parser (outputs are list of BaseSessionConfig inside of ParsedConfig)
└── util
    ├── __init__.py
    └── utils.py     # Defines utility functions for every python modules 
```

## 3. Project Initialization and Environment Setup

Before executing tasks, verify the virtual environment and required dependencies:

### Prerequisites & Dependencies
* Python 3.10+ (Python 3.10+ recommended)
* System C-libraries for SSH and XML manipulation (libxml2-dev, libxslt1-dev, libffi-dev)

### Setup commands

```bash
# 1. activate virtual environment(optional)
cat $HOME/.bashrc | grep venv 

# 2. Upgrade core tooling
pip install --upgrade pip setuptools wheel

# 3. Install Python dependencies
pip install grpcio grpcio-tools ncclient xmltodict pyyaml lxml pytest

# 4. Verify CLI entrypoint
python client_main.py --help
python client_main.py gnmi --help
python client_main.py netconf --help
```