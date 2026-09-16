# Run Modes

This document is the single source of truth for how the project is executed.

## Mode Matrix

| Mode | Entry point | Launches Python server | Launches Godot | Primary use |
|------|-------------|------------------------|----------------|-------------|
| Manual interactive | `WebSocketServer.py` + `./godot.sh` (or Godot editor Play `F5`) | Manual | Manual | Development, visual debugging, UI/camera inspection |
| Integrated | `GA-Experiment1.py` and baseline runners with `--eval-mode integrated` | Yes (auto) | Yes (headless autorun) | Batch replications, optimization, reproducible scoring |
| Command | `GA-Experiment1.py` and baseline runners with `--eval-mode command --sim-command` | External adapter dependent | External adapter dependent | Plug-in evaluator or external simulator contract |
| Mock | `GA-Experiment1.py` and baseline runners with `--eval-mode mock` | No | No | Dry runs of orchestration and reporting pipelines |

## Launching Godot

All run modes resolve the engine binary through `tools/godot_runtime.py`, so the
launcher and the Python experiment runners always agree on which executable is used.

| Command | Effect |
|---------|--------|
| `./godot.sh` | Open this project in the Godot editor |
| `./godot.sh --headless --path .` | Headless run; all arguments pass through |
| `./godot.sh --version` | Print the resolved engine version |
| `python3 tools/godot_runtime.py --print-exe` | Print the resolved binary path only |

Resolution order for `--godot-exe auto` (the default):

1. Project-local binary at the repository root (for example `Godot_v4.3-stable_linux.x86_64`)
2. Project-local binary under `tools/godot/`
3. `PATH` commands `godot4` then `godot`
4. Common per-user download and document folders

Any other `--godot-exe` value is treated as an explicit override: a file path, a
directory containing the binary, or a command on `PATH`.

The engine binary is gitignored and installed per machine, because it exceeds
GitHub's 100 MiB per-file limit. Place a Godot 4.3 build at the repository root
(or in `tools/godot/`) on each workstation. `PYTHON_BIN` overrides the interpreter
`godot.sh` uses for resolution; `GODOT_EXE` overrides the resolution input itself.

## Python Environment Prerequisite

Every mode that runs Python (manual interactive, integrated, and command mode when the
adapter is Python) requires the project virtual environment to be active:

```bash
source .venv/bin/activate
```

See [Python Environment Setup](../README.md#python-environment-setup) for creating it
from `requirements.txt`. Mock mode is the only mode that needs no third-party packages.

## Manual Interactive Mode

1. Start Python route server:
   - `source .venv/bin/activate`
   - `python "scripts/Python/Route Gen Basic Shortest Path/WebSocketServer.py"`
2. Open the project in the Godot editor with `./godot.sh` and run (`F5`),
   or launch the game window directly with `./godot.sh --path .`.
3. Use in-game UI Start/Pause and speed controls.

`GA_AUTORUN` is unset in this mode, so the simulation waits for the in-game Start button.

Outputs:
- `logs/collision_log.csv`
- `logs/simple_log.csv`
- `logs/python_routes_received.csv`

## Integrated Mode

Supported by:
- `Experiments/Ex1-ShtPath-GA/GA-Experiment1.py`
- `Experiments/Ex0-Baseline/Baseline Undirected Graph test.py`
- `Experiments/Ex0-Baseline/Baseline Directed Graph 5 test.py`

For the two Ex0 runners, `Experiments/Ex0-Baseline/EX0_CLI_Comand.txt` holds
ready-to-paste command lines with all 16 flags set explicitly, in both
multi-line and single-line form, plus mock and command mode variants.

For Ex1 GA, `Experiments/Ex1-ShtPath-GA/GA-Experiment1-Parameters.txt` provides
the full defaults-based CLI template in bash-ready multi-line and single-line form.

Prerequisite: activate the virtual environment before launching a runner. Because
`--python-exe` defaults to `sys.executable`, the spawned `WebSocketServer.py` and
TensorBoard subprocesses inherit the active environment automatically; no
`--python-exe` override is needed. Godot requires nothing from the venv.

Characteristics:
- Creates replication-specific WebSocket endpoints.
- Launches Python and Godot automatically.
- Uses per-replication output isolation for worker-safe execution.
- Resolves the engine via `tools/godot_runtime.py` (`--godot-exe` defaults to `auto`).
- Preflight warns on stderr when the resolved binary does not report Godot 4.3,
  since a newer engine can trigger project conversion. The run is not blocked.
- `--websocket-server-script` and `--godot-project-dir` default to repository-root
  absolute paths, so runners work from any working directory.

Caveats:
- `--integrated-max-sim-time` must exceed the first `ETD` in the flight plan, or no
  drone ever launches and every chromosome scores `0.0`. The tell is `queue_remaining`
  equal to the full plan count and `stop_reason: "max_sim_time_reached"` in
  `tmp/rep_*/godot_summary.json`. For the bundled Manhattan plan the first ETD is
  around `3600`, so smoke runs should use at least `--integrated-max-sim-time 4200`.
- `--pickle-file` defaults to a path relative to the current working directory, so run
  the Ex1 GA runner from the repository root or pass an absolute path.

Outputs:
- Per-replication artifacts in `Experiments/.../tmp/rep_*/`
- Per-run summaries in each experiment run folder

### Logging and Artifact Modes (Ex1 GA)

`Experiments/Ex1-ShtPath-GA/GA-Experiment1.py` supports mode controls for integrated runs:

- `--log-mode quiet|normal|verbose` (default: `normal`)
  - `quiet` -> Python `SIM_LOG_LEVEL=ERROR`, `SIM_LOG_FORMAT=json`; Godot `GA_LOG_LEVEL=quiet`
  - `normal` -> Python `SIM_LOG_LEVEL=INFO`, `SIM_LOG_FORMAT=table`; Godot `GA_LOG_LEVEL=normal`
  - `verbose` -> Python `SIM_LOG_LEVEL=DEBUG`, `SIM_LOG_FORMAT=json`; Godot `GA_LOG_LEVEL=verbose`
- `--artifact-mode keep_all|keep_failures|minimal` (default: `keep_all`)
  - `keep_all`: keep all `tmp/rep_*` artifacts
  - `keep_failures`: keep only replications with route-failure counters > 0
  - `minimal`: keep only `python_server.log`, `godot.log`, `collision_log.csv`, `python_routes_received.csv`, `godot_summary.json`
- `--mutation-prob FLOAT` (default: `0.03`)
  - Per-bit mutation probability used by Ex1 GA bit-flip mutation
  - Must be in range `[0.0, 1.0]`

Notes:
- Godot core log writers currently interpret only `GA_LOG_LEVEL=quiet` specially.
- Startup and scoring still rely on `python_server.log` and `godot.log`, so those are preserved in all artifact modes.

## Command and Mock Modes

Command mode:
- Requires `--sim-command`.
- Accepts payload/seed placeholders and returns JSON metrics.
- Useful for integration with custom external evaluators.

Mock mode:
- Deterministic synthetic metrics.
- No real simulation process launch.
- Useful for CI-style pipeline checks and quick smoke tests.
