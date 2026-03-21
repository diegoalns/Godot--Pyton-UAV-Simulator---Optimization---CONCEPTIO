# Run Modes

This document is the single source of truth for how the project is executed.

## Mode Matrix

| Mode | Entry point | Launches Python server | Launches Godot | Primary use |
|------|-------------|------------------------|----------------|-------------|
| Manual interactive | `WebSocketServer.py` + Godot editor Play (`F5`) | Manual | Manual | Development, visual debugging, UI/camera inspection |
| Integrated | `GA-Experiment1.py` and baseline runners with `--eval-mode integrated` | Yes (auto) | Yes (headless autorun) | Batch replications, optimization, reproducible scoring |
| Command | `GA-Experiment1.py` and baseline runners with `--eval-mode command --sim-command` | External adapter dependent | External adapter dependent | Plug-in evaluator or external simulator contract |
| Mock | `GA-Experiment1.py` and baseline runners with `--eval-mode mock` | No | No | Dry runs of orchestration and reporting pipelines |

## Manual Interactive Mode

1. Start Python route server:
   - `python "scripts/Python/Route Gen Basic Shortest Path/WebSocketServer.py"`
2. Open project in Godot editor and run (`F5`).
3. Use in-game UI Start/Pause and speed controls.

Outputs:
- `logs/collision_log.csv`
- `logs/simple_log.csv`
- `logs/python_routes_received.csv`

## Integrated Mode

Supported by:
- `Experiments/Ex1-ShtPath-GA/GA-Experiment1.py`
- `Experiments/Ex0-Baseline/Baseline Undirected Graph test.py`
- `Experiments/Ex0-Baseline/Baseline Directed Graph 5 test.py`

Characteristics:
- Creates replication-specific WebSocket endpoints.
- Launches Python and Godot automatically.
- Uses per-replication output isolation for worker-safe execution.

Outputs:
- Per-replication artifacts in `Experiments/.../tmp/rep_*/`
- Per-run summaries in each experiment run folder

## Command and Mock Modes

Command mode:
- Requires `--sim-command`.
- Accepts payload/seed placeholders and returns JSON metrics.
- Useful for integration with custom external evaluators.

Mock mode:
- Deterministic synthetic metrics.
- No real simulation process launch.
- Useful for CI-style pipeline checks and quick smoke tests.
