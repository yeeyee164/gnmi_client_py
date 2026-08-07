# gNMI Client (Python)

A lightweight Python-based gNMI client designed to handle defined requests across multiple network targets. This tool supports various subscription modes and provides flexible configuration interfaces via the Command Line Interface (CLI) or YAML configuration files.

## Features

- **Unary Services**:
  - `Capability`
  - `Get`
  - `SET`(TODO)
- **Multiple Subscription Modes**:
  - `ONCE`: Retrieve a single snapshot of the requested paths.
  - `POLL`: Periodic retrieval of data.
  - `STREAM`: Real-time updates with support for:
    - `SAMPLE`: Data sent at a regular interval.
    - `ON_CHANGE`: Data sent only when a value changes.
    - `TARGET_DEFINED`: Mode defined by the network device.
- **Multi-Target Support**: Ability to spawn multiple clients across a list of targets simultaneously using the `--target` option.
- **Duplicated Requests**: Ability to request multiple Requests using the `--times` multiplier.
- **Flexible Configuration**: 
  - Dynamic CLI arguments for quick testing.
  - YAML-based configuration files for complex, repeatable deployments.
- **Customizable Output**: Define output types, destinations (e.g., `stdout`), and formats (e.g., `json`).

## Installation

Ensure you have Python 3.7+ installed.

## Usage

The client can be operated in two primary ways: through command-line arguments or a YAML configuration file.

### 1. Using Command Line Interface (CLI)

**Example: Single request (Capability Request)**
```bash
python main.py --target 10.0.0.1:57400 --mode capabilities
```

**Example: Single request (Get Request)**
```bash
python main.py --target 10.0.0.1:57400 --mode get --path '/interfaces/interface[name=hello]'
```

**Example: Single request (ONCE mode)**
```bash
python main.py --target 10.0.0.1:57400 subscribe --path '/interfaces/interface' --mode once
```

**Example: Streaming updates (STREAM mode) with a 30s sample interval**
```bash
python3 gnmi_main.py --target 10.0.0.1:57400 --target 10.0.0.2:57400 \
               subscribe --mode stream --sub-mode sample --sample-interval 30 --path '/system/config' 
```

**Example: Custom Output Format**
```bash
python3 gnmi_main.py --target 10.0.0.1:57400 \
               --output-format json --output-file-type stdout \
               subscribe --mode once --path '/interfaces'
```

### 2. Using YAML Configuration

If you provide the `-c` or `--config` flag, the client will ignore other CLI arguments and use the settings defined in the YAML file.

**Example of [request_exp_named_sub.yaml](request_exp_named_sub.yaml) :**
```yaml
debug: false

subscriptions:
  interfaces_B:
    mode: "stream"
    encoding: "json_ietf"
    subscription:
      path:
      - '/interfaces/interface[name="mgmt0"]/state/counters'
      - '/interfaces/interface[name="te0/2"]/state'
      mode: "sample"
      sample_interval: 90 # in seconds

  interfaces:
    mode: "stream"
    encoding: "json_ietf"
    subscription:
      path:
      - '/interfaces/interface[name="te0/12"]/state/counters'
      - '/interfaces/interface[name="te0/13"]/state/counters'
      mode: "sample"
      sample_interval: 100 # in seconds
        
targets:
  10.1.11.101:9339:
    subscriptions:
      - interfaces
      - interfaces_B
    username: "admin"
    password: "admin123"
    update_only: false

outputs:
  log_file:
    type: file
    file-type: telemetry_res.json
    format: json
```

**Run with config:**
```bash
python3 gnmi_main.py --config config.yaml
```