# gNMI Subscription Client (Python)

A lightweight Python-based gNMI client designed to handle `Subscribe` requests across multiple network targets. This tool supports various subscription modes and provides flexible configuration interfaces via the Command Line Interface (CLI) or YAML configuration files.

## Features

- **Multiple Subscription Modes**:
  - `ONCE`: Retrieve a single snapshot of the requested paths.
  - `POLL`: Periodic retrieval of data.
  - `STREAM`: Real-time updates with support for:
    - `SAMPLE`: Data sent at a regular interval.
    - `ON_CHANGE`: Data sent only when a value changes.
    - `TARGET_DEFINED`: Mode defined by the network device.
- **Multi-Target Support**: Ability to spawn multiple clients across a list of targets simultaneously using the `--times` multiplier.
- **Flexible Configuration**: 
  - Dynamic CLI arguments for quick testing.
  - YAML-based configuration files for complex, repeatable deployments.
- **Customizable Output**: Define output types, destinations (e.g., `stdout`), and formats (e.g., `json`).

## Installation

Ensure you have Python 3.7+ installed. You will need the `PyYAML` library to use YAML configuration files.

```bash
pip install pyyaml
```

## Usage

The client can be operated in two primary ways: through command-line arguments or a YAML configuration file.

### 1. Using Command Line Interface (CLI)

**Example: Single request (ONCE mode)**
```bash
python main.py --target 10.0.0.1:57400 --path /interfaces/interface --mode once
```

**Example: Streaming updates (STREAM mode) with a 30s sample interval**
```bash
python main.py --target 10.0.0.1:57400 --target 10.0.0.2:57400 \
               --path /system/config \
               stream --sub-mode sample --sample-interval 30
```

**Example: Custom Output Format**
```bash
python main.py --target 10.0.0.1:57400 --path /interfaces \
               --output-format json --output-file-type stdout \
               once
```

### 2. Using YAML Configuration

If you provide the `-c` or `--config` flag, the client will ignore other CLI arguments and use the settings defined in the YAML file.

**Example `config.yaml`:**
```yaml
targets: 
  - "10.0.0.1:57400"
  - "10.0.0.2:57400"
encoding: "json_ietf"
username: "admin"
password: "password123"
times: 1 # denotes how many clients would you want to spawn - default is 1
debug: false
prefix: ""
subscribe:
  mode: "stream"
  update_only: false
  subscription:
    paths: 
      - "/interfaces/interface"
      - "/system/config"
    mode: "sample"
    sample_interval: 60
outputs:
  default_output:
    type: "file"
    file-type: "stdout"
    format: "json"
```

**Run with config:**
```bash
python main.py --config config.yaml