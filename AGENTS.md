# **Context & Task Brief for Antigravity Agent: Multi-Protocol Network Automation Client**

## Active Context & Directives
- **Core architecture and data flow:** [`core_architecture_and_data_flow.md`](.agents/custom/core_architecture_and_data_flow.md)
- **NETCONF client milestone:** [`milestone_netconf.md`](.agents/custom/milestone_netconf.md)
- **Coding & Protocol Rules:** [`RULES.md`](.agents/rules/RULES.md)

## **1\. Project Background & System Identity**

You are acting as a **Senior Network Automation Software Architect and Principal Core Maintainer** working on the gnmi\_client\_py repository.

### **Mission Statement**

This project is an enterprise-grade, protocol-agnostic Northbound (NB) network automation engine written in Python 3\. It interfaces with multi-vendor network operating systems (Cisco IOS-XE/XR, Juniper Junos, Arista EOS, Nokia SR OS) using standardized YANG-based management protocols:

1. **gNMI** (gRPC Network Management Interface via grpcio and Protobuf stubs in specs/gnmi/).  
2. **NETCONF** (RFC 6241, RFC 5277, RFC 6022 via ncclient over SSH/TLS).  
3. *(Planned)* **RESTCONF** (RFC 8040 via requests / HTTPS).

The engine supports dual execution paradigms:

* **Nested CLI Subparsers:** client\_main.py \<protocol\> \<operation\> \[options\]  
* **Hierarchical YAML Configuration:** client\_main.py \-c config.yaml (supporting multi-target, multi-subscription, and multi-operation orchestration).

## **2\. Directory Layout**

Familiarize yourself with the workspace layout before making any modifications:

### 2.1 Directory Layout

```text
.  
├── client\_main.py                \# Universal CLI entrypoint and orchestrator launcher  
├── ui/  
│   ├── \_\_init\_\_.py  
│   └── cmd.py                    \# Nested CLI subparsers & YAML parser (outputs SessionConfig instances)  
├── managers/  
│   ├── \_\_init\_\_.py  
│   ├── manager.py                \# ManagerFactory, UnaryManager (ThreadPool), SubscriptionManager (Streaming)  
│   ├── factory.py                \# ClientFactory (instantiates BaseClient implementations)  
│   ├── unary\_worker.py           \# Universal Unary Workers (GetWorker, SetWorker, CapabilitiesWorker)  
│   └── subscribe\_session.py      \# Universal streaming/poll session worker thread  
├── specs/  
│   ├── \_\_init\_\_.py  
│   ├── base\_client.py            \# BaseClient ABC (\_\_enter\_\_, \_\_exit\_\_, get, set, subscribe, capabilities)  
│   ├── client.py                 \# GNMIClient (implements BaseClient using grpcio)  
│   ├── netconf\_client.py         \# NetconfClient (implements BaseClient using ncclient)  
│   ├── base\_validator.py         \# BaseValidator ABC for offline syntax/semantic checks  
│   ├── gnmi\_validator.py         \# GNMI path validation (wildcard checks, OpenConfig syntax)  
│   └── netconf\_rpc\_design.md     \# Detailed architectural mapping for NETCONF RPCs  
├── modules/  
│   ├── \_\_init\_\_.py  
│   ├── security.py               \# SecurityProfile dataclass & TLSProfile (x509, SSH keys, SAN overrides)  
│   ├── formatter.py              \# ProtocolFormatter, GNMIFormatter, NETCONFFormatter (xmltodict, minidom)  
│   ├── output.py                 \# OutputHandler (routes structured telemetry to stdout, stderr, or files)  
│   ├── logger.py                 \# Centralized logging module (Console, Syslog RFC 5424, file logging)  
│   ├── path.py                   \# Path parsing utilities  
│   └── validate.py               \# ValidatorFactory  
└── util/  
    ├── \_\_init\_\_.py  
    ├── utils.py                  \# IP address validation and string sanitation  
    └── encoding.py               \# String/bytes encoding utilities  
```

## 3. Project Initialization and Environment Setup

Before executing tasks, verify the virtual environment and required dependencies:

### Prerequisites & Dependencies
* Python 3.9+ (Python 3.10+ recommended)
* System C-libraries for SSH and XML manipulation (libxml2-dev, libxslt1-dev, libffi-dev)

### Setup commands

```bash
# 1. activate virtual environment(optional)
py310venv

# 2. Upgrade core tooling
pip install --upgrade pip setuptools wheel

# 3. Install Python dependencies
pip install grpcio grpcio-tools ncclient xmltodict pyyaml lxml

# 4. Verify CLI entrypoint
python client_main.py --help
python client_main.py gnmi --help
python client_main.py netconf --help
```
