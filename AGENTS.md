# AGENTS.md — Repository Agent Instructions

Purpose: Concise, link-first guidance to help AI agents be productive in this repository.

Key entrypoints
- `gnmi_main.py`: CLI entrypoint; builds config via `ui/cmd.py` and dispatches work to managers.
- `ui/cmd.py`: CLI and YAML parsing; produces `ParsedConfig`/`SessionConfig` used by managers.
- `managers/manager.py` & `managers/gnmi_manager.py`: Manager factory and orchestrators for subscribe/unary flows.
- `managers/gnmi_subscribe_session.py` / `managers/gnmi_unary_worker.py`: Per-target workers for streaming and unary RPCs.
- `specs/client.py`: `GNMIClient` gRPC wrapper used by workers.

Run & test (concise examples)
- Run CLI (examples):
```bash
python3 gnmi_main.py --target 10.0.0.1:57400 capabilities
python3 gnmi_main.py --config request_exp_named_sub.yaml
python3 gnmi_main.py --target 10.0.0.1:57400 subscribe --mode once --path '/interfaces/interface'
```
- Run unit tests:
```bash
pytest -q
```
- Install minimal deps (if missing):
```bash
pip install grpcio pyyaml pytest
```

Important directories
- `managers/`: orchestration and worker logic. See [managers/gnmi_manager.py](managers/gnmi_manager.py).
- `modules/`: path parsing, validation, and formatting. See [modules/path.py](modules/path.py) and [modules/validate.py](modules/validate.py).
- `ui/`: CLI parsing and config normalization. See [ui/cmd.py](ui/cmd.py).
- `specs/gnmi/`: pre-generated proto bindings used by the client; do not re-generate without instruction.

Conventions & notes for agents
- Link-first: reference files rather than embedding large blocks of code or docs.
- Minimal changes: prefer small, well-scoped edits that preserve existing behaviors.
- Protos: the repo includes generated protos in `specs/gnmi/`; avoid regenerating or modifying them unless requested.
- YAML is authoritative for request shape: preserve compatibility when changing `ui/cmd.py`.
- Path parsing is subtle: update `modules/path_test.py` when changing `modules/path.py`.

Files to reference when working
- [README.md](README.md)
- [gnmi_main.py](gnmi_main.py)
- [ui/cmd.py](ui/cmd.py)
- [managers/manager.py](managers/manager.py)
- [managers/gnmi_manager.py](managers/gnmi_manager.py)
- [managers/gnmi_subscribe_session.py](managers/gnmi_subscribe_session.py)
- [managers/gnmi_unary_worker.py](managers/gnmi_unary_worker.py)
- [modules/path.py](modules/path.py)
- [modules/validate.py](modules/validate.py)
- [modules/path_test.py](modules/path_test.py)
- [specs/gnmi/gnmi_pb2.py](specs/gnmi/gnmi_pb2.py)
- [specs/gnmi/gnmi_pb2_grpc.py](specs/gnmi/gnmi_pb2_grpc.py)
- [request_exp.yaml](request_exp.yaml)
- [request_exp_named_sub.yaml](request_exp_named_sub.yaml)

How to use this instruction
- Start here when exploring the repository. Follow the linked files for implementation details and tests.

Next steps I can do
- Add a focused `instructions.md` for contributor workflows (testing, linting, examples).
- Create a small `AGENT` skill to run `pytest -q` and validate CLI invocations automatically.

Feedback
- Tell me which next step you'd like: expand testing instructions, add CI guidance, or create a copilot-instructions file.
