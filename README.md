# Godot UAV Simulator

A comprehensive multi-drone simulation system built with Godot Engine 4.3, featuring real-time pathfinding, collision detection, and 3D visualization for Urban Air Mobility (UAM) operations.

## Overview

The Godot UAV Simulator is designed to simulate multiple autonomous drones operating in an urban airspace environment. It combines a Godot-based 3D visualization engine with a Python-based pathfinding server that uses NetworkX weighted shortest-path routing to plan drone routes.

### Key Features

- **Multi-Drone Simulation**: Supports concurrent operation of multiple drones with different models and capabilities
- **Shortest-Path Routing**: Python server uses NetworkX weighted shortest path for route planning
- **Real-Time Visualization**: 3D terrain rendering with interactive camera controls
- **Active Drones Display**: Left-side GUI panel showing active drones with their first waypoint times (simulation time)
- **Collision Detection**: Automatic detection and logging of drone proximity events
- **Pre-Request Route System**: Routes are requested 3000 simulation seconds before ETD for efficient planning
- **Multiple Drone Models**: Three distinct drone types with varying performance characteristics
- **Terrain System**: GridMap-based terrain visualization with altitude data
- **WebSocket Communication**: Real-time bidirectional communication between Godot and Python

## Project Organization (3 Layers)

The repository is organized to separate simulation runtime, experiment orchestration, and generated artifacts:

1. **Runtime Layer**: Godot and Python simulator components used by the base system.
2. **Orchestration Layer**: GA/baseline experiment runners that execute and evaluate simulation replications.
3. **Artifacts Layer**: Generated logs, run configs, per-replication outputs, summaries, and notebooks.

## Project Structure

```
Godot- Pyton UAV-Simulator - Tests Setup/
├── docs/
│   ├── RUN_MODES.md               # Canonical execution mode matrix
│   └── EXPERIMENT_TEMPLATE.md     # Template for adding new ExN folders
├── Experiments/                   # Orchestration scripts + generated experiment outputs
├── scripts/
│   ├── core/              # Core simulation systems
│   │   ├── simulation_engine.gd      # Main simulation loop and coordination
│   │   ├── drone_manager.gd           # Drone lifecycle management
│   │   ├── flight_plan_manager.gd    # CSV flight plan loading and queue management
│   │   ├── route_pre_request_manager.gd  # Pre-request route system (3000 sim seconds before ETD)
│   │   ├── visualization_system.gd    # 3D rendering and camera controls
│   │   ├── WebSocketManager.gd        # WebSocket client for Python communication
│   │   ├── gridmap_manager.gd         # Terrain GridMap management
│   │   ├── simple_logger.gd          # CSV logging system
│   │   └── DebugLogger.gd             # Advanced logging with categories
│   ├── drone/
│   │   └── drone.gd                   # Individual drone behavior and movement
│   ├── Python/
│   │   └── Route Gen Basic Shortest Path/
│   │       ├── WebSocketServer.py     # Python WebSocket server
│   │       ├── shortest_pathfinder.py # NetworkX shortest-path planner
│   │       ├── graph_loader.py        # Graph data loading
│   │       ├── sim_logger.py          # Structured logger + Python CSV route outputs
│   │       └── coordinate_constants.py # Coordinate system constants
│   └── ui/
│       └── simple_ui.gd                # User interface controls
├── scenes/
│   ├── main/
│   │   └── main.tscn                  # Main scene entry point
│   └── GridMap/
│       └── terrain_gridmap.tscn       # Terrain visualization scene
├── data/
│   ├── Regular_Lattice_Manhattan_200 FP_2DP_2Hrs_Ordered.csv  # Flight plan data
│   └── Filtered_FAA_UAS_FacilityMap_Data_LGA.csv  # Terrain altitude data
├── resources/                         # 3D models and meshes
├── tools/
│   ├── .gdignore                      # Hides tools/ from the Godot editor scan
│   └── godot_runtime.py               # Shared Godot executable resolution + version check
├── drone_models_specifications.txt    # Detailed drone model documentation
├── godot.sh                           # Linux/macOS: unified Godot launcher (editor by default)
├── open_in_godot_editor.bat           # Windows: open this project in Godot editor (GUI)
├── Godot_v4.3-stable_linux.x86_64     # Local engine binary (gitignored, per machine)
└── project.godot                      # Godot project configuration
```

> **Note:** `Experiments/` may contain generated configs, CSVs, and logs with absolute paths (`run_dir`, tool paths) from the machine that produced each run. After moving or renaming the project folder, prefer re-running experiments for fresh paths, or update those artifacts if you need old runs to stay self-consistent.
>
> **Editor performance:** `Experiments/` contains a **`.gdignore`** file so Godot skips scanning tens of thousands of experiment artifacts when opening the project. Without it, the editor can sit on “loading” for a long time (looks like a hang). Python/GA tooling can still read those files from disk; they are only excluded from Godot’s FileSystem dock and import pipeline.

## System Requirements

### Godot Engine
- **Version**: 4.3 (GL Compatibility renderer)
- **Platform**: Windows, Linux, macOS
- **Display**: 1920x1080 recommended
- **Installation**: the engine binary is gitignored and installed per machine. See [Godot Executable Setup](#godot-executable-setup).

### Python Server
- **Python**: 3.9 or higher (both GA runners use `argparse.BooleanOptionalAction`, added in 3.9)
- **Dependencies**: pinned in [requirements.txt](requirements.txt), which is the single source of truth. See [Python Environment Setup](#python-environment-setup).
- **Graph Data**: `regular_lattice_graph.pkl` must be present in Python script directory

### Hardware
- **RAM**: 4GB minimum, 8GB recommended
- **GPU**: OpenGL 3.3 compatible graphics card
- **Storage**: ~500MB for project files

## Godot Executable Setup

The Godot binary is **not tracked in git**: it is roughly 107 MiB, above GitHub's
hard 100 MiB per-file limit. Install it once per machine.

1. Download Godot **4.3** for your platform from the
   [Godot 4.3 archive](https://godotengine.org/download/archive/4.3-stable/).
   The version must be 4.3 to match `config/features` in `project.godot`; a newer
   engine will prompt to convert the project.
2. Extract the binary into the **repository root** (or into `tools/godot/`).
3. On Linux and macOS, ensure it is executable:

```bash
chmod +x Godot_v4.3-stable_linux.x86_64
```

Then verify resolution:

```bash
./godot.sh --version                          # expect 4.3.stable.official.<hash>
python3 tools/godot_runtime.py --print-exe    # prints the resolved binary path
```

`tools/godot_runtime.py` is the single source of truth for engine resolution, shared
by `godot.sh` and all Python experiment runners. Resolution order for the default
`--godot-exe auto`:

1. Project-local binary at the repository root
2. Project-local binary under `tools/godot/`
3. `PATH` commands `godot4` then `godot`
4. Common per-user download and document folders

Environment overrides: `PYTHON_BIN` selects the interpreter `godot.sh` uses for
resolution, and `GODOT_EXE` overrides the resolution input.

## Python Environment Setup

All Python dependencies are pinned in [requirements.txt](requirements.txt). Use a
project-local virtual environment: modern Debian/Ubuntu systems mark the system
interpreter as externally managed (PEP 668) and refuse `pip install` into it.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

If `python3 -m venv` reports that `ensurepip` is unavailable, Debian/Ubuntu ships it
in a separate package. Either install it:

```bash
sudo apt install python3-venv python3-pip
```

or, when `sudo` is not available, bootstrap `pip` into the environment directly:

```bash
python3 -m venv --without-pip .venv
curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
```

### Why `torch` is a dependency

`torch` is used **only** for `SummaryWriter` TensorBoard scalar logging in the GA and
baseline runners; no modeling or training uses it. It is therefore pinned to the CPU
build (`torch==2.14.0+cpu`) via the PyTorch CPU index declared at the top of
`requirements.txt`, which avoids pulling roughly 2.5 GB of `nvidia-*` CUDA libraries.
To use a GPU build instead, install an NVIDIA driver first, then reinstall `torch`
without the CPU index.

### Activation is all that is required

The experiment runners default `--python-exe` to `sys.executable`, so once the venv is
active, the WebSocket server and TensorBoard subprocesses inherit it automatically. No
extra flags are needed. The Godot engine needs nothing from the venv.

### Reproducing an exact environment

[requirements.lock.txt](requirements.lock.txt) records the fully resolved transitive
dependency set from `pip freeze`, for reproducing a known-good environment across
machines or over time:

```bash
pip install -r requirements.lock.txt
```

Verify the install:

```bash
python -c "import networkx, numpy, pandas, plotly, websockets, torch; \
from torch.utils.tensorboard import SummaryWriter; print('imports OK')"
python -m tensorboard.main --help > /dev/null && echo "tensorboard OK"
```

## Quick Start

### 1. Start the Python WebSocket Server

Activate the virtual environment first (see [Python Environment Setup](#python-environment-setup)):

```bash
source .venv/bin/activate
cd scripts/Python/Route\ Gen\ Basic\ Shortest\ Path
python WebSocketServer.py
```

The server will start on `ws://localhost:8765` and wait for connections from Godot.

### 2. Open Project in Godot (editor GUI)

**Important:** Starting Godot with only `--path` runs the **game window**, not the **editor**. Use `--editor` (or the launcher below) when you want the GUI.

- **Easiest (Linux/macOS):** run **`./godot.sh`** in the project root. It resolves the engine automatically and opens the editor.
- **Easiest (Windows):** double-click **`open_in_godot_editor.bat`** in the project root (edit `GODOT_EXE` inside the file if your Godot install path differs).
- **Command line (any platform):** `./godot.sh` passes every argument through, so `./godot.sh --path .` runs the game window directly and `./godot.sh --headless --path .` runs headless.
- **Command line (explicit binary):**
  ```text
  "C:\Godot_v4.3-stable_win64.exe\Godot_v4.3-stable_win64.exe" --editor --path "D:\path\to\Godot- Pyton UAV-Simulator - Tests Setup"
  ```
  Use the **project folder** (the directory that contains `project.godot`), not only the `.godot` file, so the correct project loads.
- **Project Manager:** open Godot → **Import** → select `project.godot` → **Import & Edit**.

Then press **F5** (or **Play**) in the editor to run the simulation.

### 3. Control the Simulation

- **Start/Pause**: Use the UI controls in the top-left corner
- **Speed Multiplier**: Adjust simulation speed via slider (0.5x to 5.0x)
- **Headless Mode**: Disable visualization for faster performance
- **Drone Port Selection**: Select different drone ports to view their locations
- **Active Drones Panel**: Left side of screen displays all active (flying) drones with their first waypoint times (simulation time)

## Execution Modes (Single Source of Truth)

All supported run modes are documented in `docs/RUN_MODES.md`.

| Mode | Main entrypoint | Launches Python | Launches Godot | Typical use |
|------|------------------|-----------------|----------------|-------------|
| Manual interactive | `WebSocketServer.py` + `./godot.sh` (or editor `F5`) | Manual | Manual | Visual debugging and interactive simulation |
| Integrated | GA/Baseline scripts with `--eval-mode integrated` | Auto | Auto (headless autorun) | Batch experiments and scoring |
| Command | GA/Baseline scripts with `--eval-mode command` | External | External | Plug external evaluators/adapters |
| Mock | GA/Baseline scripts with `--eval-mode mock` | No | No | Fast pipeline smoke checks |

## Drone Models

The simulator supports three drone models with distinct performance characteristics:

### 1. Long Range FWVTOL (Fixed-Wing VTOL)
- **Max Speed**: 55.0 m/s (~200 km/h)
- **Max Range**: 150 km
- **Battery**: 2,000 Wh
- **Payload**: 5.0 kg
- **Usage**: ~90% of flight plans (primary workhorse)

### 2. Light Quadcopter
- **Max Speed**: 18.0 m/s (~65 km/h)
- **Max Range**: 8 km
- **Battery**: 250 Wh
- **Payload**: 0.5 kg
- **Usage**: ~1-2% of flight plans (short-range deliveries)

### 3. Heavy Quadcopter
- **Max Speed**: 25.0 m/s (~90 km/h)
- **Max Range**: 15 km
- **Battery**: 800 Wh
- **Payload**: 8.0 kg
- **Usage**: ~5-8% of flight plans (heavy cargo)

For detailed specifications, see `drone_models_specifications.txt`.

## Flight Plan Data

Flight plans are loaded from CSV files in the `data/` directory. The default file is:
- `Regular_Lattice_Manhattan_200 FP_2DP_2Hrs_Ordered.csv`

### CSV Format

Each row contains:
- `FlightPlanID`: Unique identifier (e.g., "FP000001")
- `DronePortID`: Origin port (e.g., "DP1", "DP2")
- `ETD`: Estimated Time of Departure (formatted time)
- `ETD_Seconds`: ETD in seconds (float)
- `OriginLat`, `OriginLon`: Origin coordinates (decimal degrees)
- `OriginNodeID`: Origin graph node ID (e.g., "L0_X0_Y0")
- `DestinationLat`, `DestinationLon`: Destination coordinates
- `DestinationNodeID`: Destination graph node ID
- `DroneModel`: Model type (String)
- `EstimatedFlightTime`: Duration in minutes (float)
- `Ceiling`: Maximum altitude in meters (float)

## Architecture Overview

The simulator uses a hybrid architecture:

1. **Godot Client**: Handles visualization, drone movement, collision detection, and simulation timing
2. **Python Server**: Performs pathfinding using NetworkX shortest path and maintains drone registry
3. **WebSocket Bridge**: Real-time bidirectional communication between systems

### Key Systems

- **SimulationEngine**: Main coordinator, manages simulation loop and system integration
- **DroneManager**: Creates, updates, and removes drone instances
- **FlightPlanManager**: Loads and queues flight plans from CSV
- **RoutePreRequestManager**: Sends route requests 3000 simulation seconds before ETD
- **VisualizationSystem**: 3D rendering, camera controls, terrain visualization
- **WebSocketManager**: Autoload singleton for Python communication

For detailed architecture documentation, see [ARCHITECTURE.md](ARCHITECTURE.md).

## WebSocket Protocol

### Route Request (Godot → Python)

```json
{
  "type": "request_route",
  "drone_id": "FP000001",
  "model": "Long Range FWVTOL",
  "etd_seconds": 1234.5,
  "start_node_id": "L0_X0_Y0",
  "end_node_id": "L0_X6_Y2",
  "start_position": {"lon": 0.0, "lat": 0.0, "alt": 0.0},
  "end_position": {"lon": 1000.0, "lat": 1000.0, "alt": 50.0},
  "max_speed": 55.0,
  "simulation_time": 1234.5,
  "client_request_sent_time": 1698765432.123
}
```

### Route Response (Python → Godot)

```json
{
  "type": "route_response",
  "drone_id": "FP000001",
  "status": "success",
  "route": [
    {
      "lat": 40.55417343,
      "lon": -73.99583928,
      "altitude": 50.0,
      "speed": 55.0,
      "description": "Origin (waypoint 1)"
    }
  ],
  "server_request_received_time": 1698765432.125,
  "server_response_sent_time": 1698765432.456,
  "pathfinding_duration": 0.331
}
```

Path timing and returned waypoint speeds use the same `max_speed` provided by Godot (no speed scaling factor applied in Python). For pre-requested routes, temporal planning starts from `etd_seconds`, while `simulation_time` is still used for housekeeping (e.g., registry cleanup).

## Collision Detection

- **Detection Radius**: 5.0 meters per drone (10m diameter safety zone)
- **Arrival Threshold**: 5.0 meters for waypoint arrival
- **Method**: Area3D-based automatic collision detection via Godot physics engine
- **Logging**: All collision events logged to CSV via SimpleLogger
- **Visualization**: Persistent collision markers are automatically created at collision locations
  - Orange/yellow sphere markers (10m radius) mark where collisions occurred
  - Markers display drone IDs and distance information
  - Markers remain visible for the entire simulation duration
  - Markers can be toggled on/off via `VisualizationSystem.set_show_collision_markers()`
  - All markers can be cleared via `VisualizationSystem.clear_collision_markers()`

## Coordinate Systems

### Geographic to World Conversion

The simulator uses a reference point for coordinate conversion:
- **Origin Latitude**: 40.55417343° (decimal degrees)
- **Origin Longitude**: -73.99583928° (decimal degrees)

Conversion formula:
- `meters_per_deg_lat = 111320.0`
- `meters_per_deg_lon = 111320.0 * cos(latitude_radians)`
- `x = (lon - origin_lon) * meters_per_deg_lon` (East/West)
- `z = (origin_lat - lat) * meters_per_deg_lat` (North/South, inverted for Godot)

### Graph Node IDs

Nodes use format: `L{level}_X{x}_Y{y}` (e.g., `L0_X0_Y0`)
- Enables O(1) graph lookup instead of O(n) coordinate matching
- Significantly improves pathfinding performance

## Performance Characteristics

- **Physics Rate**: 300 Hz (300 physics ticks per second)
- **Route Pre-Request**: Routes requested 3000 simulation seconds before ETD
- **Route Timeout**: 
  - 10 seconds for pre-requests (system clock time)
  - 90 seconds for individual drone requests (simulation time)
  - 3 seconds for shortest-path planning (system clock time)
- **Memory Optimization**: Heap-based route storage with maximum 1000 routes
- **Logging Interval**: CSV logs written every 10 seconds of simulation time

## Logging and Output

### CSV Logging (SimpleLogger)
- **Drone States**: `logs/simple_log.csv` - Position, speed, target, completion status
- **Collision Events**: `logs/collision_log.csv` - Collision start/end events with distances
- **Logging Interval**: Every 10 seconds of simulation time

### Python Route/Time CSV Logging
- **Received Routes**: `logs/python_routes_received.csv` - One row per waypoint per planned drone route from Python (includes overfly timing)
- **Startup behavior**: target CSV is cleared when the Python WebSocket server starts, then rows are appended during that run
- **Integrated GA behavior**: each replication writes to its own `tmp/rep_*/python_routes_received.csv` via `SIM_ROUTES_RECEIVED_CSV`, avoiding cross-replication overwrite
- **Notebook waypoint labels**: `logs/uav_route_visualization.ipynb` can annotate each plotted waypoint with `overfly_time_sim_s` from `python_routes_received.csv` (3D and 2D plots)
- **Overlap handling in notebook**: waypoint time labels use seeded random positional jitter (plus a light bbox in 2D) to keep labels readable when drones share the same route/waypoints; current jitter defaults are `label_jitter_xy=0.15`, `label_jitter_z=0.06`, `label_jitter_2d=0.15`
- **Route-color labels in notebook**: each waypoint time label uses the same color as its corresponding plotted route line for easier route association
- **Interactive route controls**: notebook now uses Plotly for interactive 3D/2D route views; click legend items to toggle per-route visibility and use `Labels ON/OFF` buttons to control time-label traces

### Debug Logging (DebugLogger)
- **Categories**: ROUTE, WEBSOCKET, DRONE, SIMULATION, TERRAIN, VISUALIZATION, HEAP, FLIGHT_PLAN, GENERAL
- **Log Levels**: DEBUG, INFO, WARNING, ERROR
- **Verbosity Levels**: SILENT, MINIMAL, NORMAL, VERBOSE
- **Table Format**: All messages use fixed-width columns for unified readable output with Python
- **Autoload**: The script is registered in `project.godot` as **AppDebugLogger** (the node name must differ from `class_name DebugLogger` in Godot 4). Access the instance with `DebugLogger.get_instance()`.

### Cross-Language Log Standard (Fixed-Width Table)

Godot (`DebugLogger`) and Python (`sim_logger.py`) emit logs in a unified fixed-width table format:

| Column | Width | Description |
|--------|-------|-------------|
| ts | 12 | Timestamp (sim time in Godot, Unix time in Python) |
| level | 8 | DEBUG, INFO, WARNING, ERROR |
| category | 14 | Subsystem (ROUTE, WEBSOCKET, DRONE, etc.) |
| source | 6 | `godot` or `python` |
| event | 32 | Short event name |
| data | 150 | Key=value pairs |

Example output (both Godot and Python):

```
ts            level    category       source event                           data
12.34s        INFO     ROUTE          godot  connection_established         {url=ws://localhost:8765}
1730556789.12 INFO     WEBSOCKET      python client_connected                {client_address=127.0.0.1 status=ready}
```

Python logger runtime controls:
- `SIM_LOG_LEVEL`: `DEBUG`, `INFO`, `WARNING`, `ERROR` (default: `INFO`)
- `SIM_LOG_FORMAT`: `table` (default), `json`, or `pretty`
- `SIM_ROUTES_RECEIVED_CSV`: optional output path override for per-waypoint route CSV

Examples:
- `SIM_LOG_FORMAT=table` for aligned fixed-width output (default)
- `SIM_LOG_FORMAT=json` for one JSON object per line (dashboards/parsing)
- `SIM_LOG_FORMAT=pretty` for compact `[LEVEL][CATEGORY][python] event | key=value` format

## Development

### Key Files to Modify

- **Drone Behavior**: `scripts/drone/drone.gd`
- **Pathfinding Algorithm**: `scripts/Python/Route Gen Basic Shortest Path/shortest_pathfinder.py`
- **Simulation Logic**: `scripts/core/simulation_engine.gd`
- **Visualization**: `scripts/core/visualization_system.gd`
- **Route Pre-Request System**: `scripts/core/route_pre_request_manager.gd`
- **Terrain System**: `scripts/core/gridmap_manager.gd`
- **Logging**: `scripts/core/simple_logger.gd` or `scripts/core/DebugLogger.gd`

### Adding New Experiment Folders

Use `docs/EXPERIMENT_TEMPLATE.md` to create new `Experiments/ExN-*` folders consistently.

Recommended rules:
- Keep runtime behavior in `scripts/` and use experiment folders as orchestration wrappers.
- Reuse existing mode contract (`integrated`, `command`, `mock`) to avoid mode fragmentation.
- Keep outputs isolated under each experiment's run directory.

### GA Experiment 1 (Edge-Group Orientation Optimization)

`Experiments/Ex1-ShtPath-GA/GA-Experiment1.py` runs a simulation-based Genetic Algorithm to optimize binary orientation settings for air-corridor edge groups:

- Full parameter reference (defaults + runtime GA behavior): `Experiments/Ex1-ShtPath-GA/GA-Experiment1-Parameters.txt`
  - Includes bash-ready canonical CLI command templates (multi-line and single-line, full flag surface).
- **Decision variables**: one bit per contiguous corridor segment group (`0=forward`, `1=reverse`)
- **Grouping source**: uses `identify_air_corridor_edge_groups()` from `Experiments/Ex1-ShtPath-GA/Visualize_Air_Corridor_Binary_Edge_Selection_updated.py`
- **Grouping rule**: layer + corridor axis + fixed index + contiguous segment ID, with forward/reverse sets derived from grid-direction sign
- **Chromosome**: full binary vector across all groups
- **Mutation control**: bit-flip mutation uses `--mutation-prob` (default `0.03`, valid range `[0.0, 1.0]`)
- **Objective**: minimize `sum(collisions) + no_path_count + timeout_count` from simulation outcomes
- **Invalid handling**: chromosome evaluation still flags invalid when `no_path_count + timeout_count >= 1000`, but fitness is now computed from the objective sum above
- **Replication schedule**:
  - All generations: `k=--generation-seeds` for all individuals (default `3`)
  - Final validation: top `--final-validation-top-k` candidates at held-out `k=--final-validation-seeds`
- **Selection metric**:
  - GA parent selection, elitism, generation-best tracking, and early-stop improvement checks use normalized fitness (`fitness / replications`) so selection remains per-replication comparable.
  - Raw objective sum (`sum(collisions) + no_path_count + timeout_count`) is logged as `best_individual_fitness_raw` and `population_fitness_raw_*`.
- **Post-processing controls** (for faster integrated smoke checks):
  - `--generation-seeds` (default `3`)
  - `--final-validation-top-k` (default `5`)
  - `--final-validation-seeds` (default `20`)
  - `--run-sensitivity/--no-run-sensitivity` (default enabled)
  - `--sensitivity-max-bits` (default `0` = all bits)
  - Note: `Experiments/Ex2-ShtPath-GA 16 Workers/test_integrated_run.py` uses bounded values so a full pipeline run (GA loop + validation + sensitivity + artifact export) can complete quickly.
- **Ex2 16-workers variant**: `Experiments/Ex2-ShtPath-GA 16 Workers/GA-Experiment1.py` sets `--workers` default to `16`.
- **GA parameter guards**:
  - `population >= 2`
  - `0 <= elitism <= population`
  - `workers >= 1`
  - `generation-seeds >= 1`
  - `final-validation-top-k >= 1`
  - `final-validation-seeds >= 1`
  - `sensitivity-max-bits >= 0`
  - Reproduction step now safely handles `population == elitism` (fully elitist carry-over), preventing tiny-run crashes
  - Default `population` is set to `120` (override with `--population` as needed)
  - Default `workers` is set to `10` for parallel batch evaluation (override with `--workers`)
- **Log mode** (`--log-mode`, default: `normal`):
  - `quiet`: Python `SIM_LOG_LEVEL=ERROR`, `SIM_LOG_FORMAT=json`; Godot `GA_LOG_LEVEL=quiet` (skips `simple_log.csv` and `godot_summary.json` in core writers)
  - `normal`: Python `SIM_LOG_LEVEL=INFO`, `SIM_LOG_FORMAT=table`; Godot `GA_LOG_LEVEL=normal`
  - `verbose`: Python `SIM_LOG_LEVEL=DEBUG`, `SIM_LOG_FORMAT=json`; Godot `GA_LOG_LEVEL=verbose`
- **Artifact mode** (`--artifact-mode`, default: `keep_all`):
  - `keep_all`: keep all per-rep files in `tmp/rep_*`
  - `keep_failures`: delete successful `rep_*` folders, keep only reps with route-failure counters > 0
  - `minimal`: keep only `python_server.log`, `godot.log`, `collision_log.csv`, `python_routes_received.csv`, and `godot_summary.json`
- **Logging/outputs**:
  - TensorBoard per-generation live metrics now use explicit namespaces:
    - `best_individual/*` (selection/raw/planner-invalid/seed-std)
    - `population/*` (selection/raw aggregates, invalid ratio, route-failure means, diversity)
    - `generation/seconds`
  - Terminal generation line uses the same explicit naming model:
    - best individual: `best_sel`, `best_raw`, `best_planner_invalid`, `best_seed_std`
    - population: `pop_sel_mean`, `pop_sel_std`, `pop_invalid`, route-failure means, `pop_diversity`
    - debug context: `best_seed_scores` (best individual's per-seed fitness as `seed:score`)
  - Terminal output now includes post-phase progress lines so long final steps are observable:
    - `[FinalVal ...]` start/progress/end for held-out candidate validation
    - `[Sensitivity ...]` start/progress/end (periodic progress every 10 bits, plus skip message when disabled)
  - `generation_metrics.csv`
    - uses explicit schema with `best_individual_*`, `population_*`, `generation_seconds`, `seed_signature_base`
    - includes `best_individual_seed_fitness_std` (seed-level variability of the best individual)
  - `best_solution.json`
    - uses explicit final keys (`best_individual_*`, `seed_signature_heldout`)
  - `final_validation_summary.json`
    - uses explicit candidate keys in `top_results` (`candidate_*`) and held-out seed metadata
  - `sensitivity_analysis.csv` (only when sensitivity is enabled)
  - `terminal_output.txt` (mirrored GA terminal stdout/stderr)
- **Integrated run mode (default)**:
  - Builds an oriented graph per chromosome/seed replication
  - Launches Python `WebSocketServer.py` with `GRAPH_PICKLE_PATH` override
  - Uses per-replication WebSocket isolation (`WS_SERVER_HOST`/`WS_SERVER_PORT` + Godot `GA_WEBSOCKET_URL`) so parallel workers do not contend on port `8765`
  - Server startup readiness now accepts either an explicit `server_running` log marker or successful socket connect on the assigned WS port (important when quiet logging suppresses INFO lines)
  - Adds startup retry with automatic port fallback for transient bind/startup failures during parallel runs
  - Uses per-replication log file isolation (`GA_COLLISION_LOG_CSV`, `GA_SIMPLE_LOG_CSV`) so collision scoring remains worker-safe
  - Uses per-replication Python route CSV isolation (`SIM_ROUTES_RECEIVED_CSV`) so waypoint timing exports are worker-safe
  - Injects mode-controlled env vars:
    - Python: `SIM_LOG_LEVEL`, `SIM_LOG_FORMAT`
    - Godot: `GA_LOG_LEVEL`
  - Launches Godot headless in GA autorun mode
  - **Wall-clock guard**: Python waits on the Godot subprocess with `--sim-timeout-seconds` (default **800** seconds) so long 2-hour-scenario batches can finish under typical physics tick rates without false timeouts; override if your machine or scenario needs more headroom.
  - Stops simulation automatically when workload drains (or max sim time)
  - Scores from per-replication collision CSV (`COLLISION_START` count) and route-failure diagnostics:
    - Python pathfinding events: `pathfinding_no_path`, `pathfinding_timeout`
    - Python server errors: `route_request_rejected_invalid_nodes`, `pathfinding_error`
    - Godot no-response events: `pre_request_timeout_no_response`, `flight_cancelled_route_timeout`
    - Godot invalid-route-payload events: `route_request_failed_no_valid_route`
  - Route-failure counters accept full and fixed-width-truncated event names to avoid silent undercount when parsing table logs

#### Running GA Experiment 1

Example (fully integrated mode):

```bash
python Experiments/Ex1-ShtPath-GA/GA-Experiment1.py \
  --eval-mode integrated \
  --mutation-prob 0.03
```

`--godot-exe` and `--godot-project-dir` no longer need to be passed when the engine
binary sits at the repository root. See
[Godot Executable Setup](#godot-executable-setup) for resolution details.

Godot executable resolution behavior:
- `--godot-exe` defaults to `auto`, which resolves in this order: project-local binary at the repository root, project-local binary under `tools/godot/`, `PATH` commands (`godot4`, `godot`), then common per-user download and document folders.
- Any other `--godot-exe` value is an explicit override and accepts a direct executable path, a PATH command (e.g. `godot4`), or a directory containing Godot binaries.
- For Windows extracted bundles where the folder name ends with `.exe`, the script auto-resolves the actual executable inside that folder.
- On Linux and macOS, a binary found without the execute bit produces an explicit `chmod +x` message rather than a misleading "not found" error.
- Integrated mode performs a startup preflight check: WebSocket server script and `project.godot` path are validated, then **Godot is run with `--version`** to confirm the binary starts and to warn when it does not report 4.3 (a newer engine can trigger project conversion). A version mismatch warns on stderr but does not block the run. If Godot exits shortly after launch during a replication, the script reports the Godot log path and the last 2000 characters of the log to help debug.
- Early Godot exits are treated as failures only when the return code is non-zero; fast clean exits are accepted (useful for tiny smoke tests with low `--integrated-max-sim-time`).
- `--websocket-server-script` and `--godot-project-dir` default to repository-root absolute paths, so runners can be launched from any working directory.

Optional external adapter mode is still available via `--eval-mode command` and `--sim-command`.

TensorBoard behavior:
- By default, the script auto-starts TensorBoard and opens your browser.
- Default URL is `http://127.0.0.1:6007` (customize with `--tensorboard-host` and `--tensorboard-port`).
- Disable auto-launch with `--no-auto-launch-tensorboard`.
- Disable browser auto-open with `--no-auto-open-tensorboard-browser`.
- TensorBoard process output is written to `tensorboard_process.log` inside the run folder.
- Full GA terminal output (stdout/stderr) is mirrored to `terminal_output.txt` inside the run folder.
- Auto-launch now performs a short startup health check; if TensorBoard exits immediately (for example, port conflict), the run prints a warning instead of reporting a false success.
- GA metrics are flushed every generation so curves appear more consistently during long runs.

### Baseline Tests (No Optimization)

This project currently includes two baseline scripts under `Experiments/Ex0-Baseline/`:

- `Baseline Undirected Graph test.py`: runs replications on the original graph orientation (no optimization).
- `Baseline Directed Graph 5 test.py`: evaluates five fixed directed-orientation configurations (all-forward, all-reverse, alternating, and two random variants). `--replications` is applied per configuration, so the total run count is five times that value.

Both baseline scripts reuse the same Python+Godot integrated simulation path as `GA-Experiment1.py` (via `SimulationAdapter`) and output per-replication plus summary artifacts in their respective run folders.
Both also report collision and fitness dispersion via standard deviation (`collisions_std`, `fitness_std`) in summary CSV outputs and terminal summaries.
Both expose the same 16 CLI flags, differing only in the `--run-root` default (`baseline_runs` vs `directed_graph_5_runs`), and both default `--workers` to `10`.

Ready-to-paste command lines with every flag set explicitly are kept in
`Experiments/Ex0-Baseline/EX0_CLI_Comand.txt` (multi-line and single-line forms per script,
plus a full flag reference and mock/command-mode variants).

Example (original-orientation baseline):

```bash
python "Experiments/Ex0-Baseline/Baseline Undirected Graph test.py" \
  --replications 100 \
  --workers 24 \
  --eval-mode integrated
```

### Adding New Drone Models

1. Add model specification to `drone.gd` `_set_model_attributes()` function
2. Update `drone_models_specifications.txt` documentation
3. Ensure CSV flight plan data includes new model name

### Git Ignore Policy

- A repository-level `.gitignore` is provided and should be used for first-time GitHub publishing.
- Keep generated/local artifacts untracked: `.godot/`, `.import/`, Python caches, virtual envs (`.venv/`), and notebook checkpoints.
- Keep `requirements.txt` and `requirements.lock.txt` **tracked**. They are the dependency source of truth; only the resulting `.venv/` is ignored.
- Keep the local Godot engine binary untracked (`/Godot_v*_linux.x86_64`, `/Godot_v*.exe`, `/Godot_v*.app/`, `tools/godot/`). A Godot 4.3 build is roughly 107 MiB, above GitHub's hard 100 MiB per-file limit, so committing it makes pushes fail. Install it per machine as described in [Godot Executable Setup](#godot-executable-setup).
- Keep local IDE scratch/workspace state untracked (for example `.cursor/`, transient terminal dump files like `terminal_*.txt`, and ad-hoc AI notes such as `cursor_purpose_*.md`).
- Keep runtime outputs untracked: `logs/*.csv`, `logs/*.log`, and `logs/*.ipynb`.
- Keep experiment-run artifacts untracked under `Experiments/` (for example: `tmp/`, `tensorboard/`, per-rep logs/CSVs/JSONs, and generated run folders such as `baseline_runs/` and `directed_graph_5_runs/`).
- If a notebook should be versioned intentionally, move it outside `logs/` or add an explicit exception rule in `.gitignore`.

## Troubleshooting

### WebSocket Connection Failed
- Ensure Python server is running on `localhost:8765`
- Check firewall settings
- Verify no other process is using port 8765

### Godot Executable Not Found
- Run `python3 tools/godot_runtime.py --print-exe` to see what resolution finds and why it fails
- Confirm a Godot 4.3 binary is at the repository root or in `tools/godot/`
- On Linux/macOS, a binary found without the execute bit reports an explicit `chmod +x` message
- Override explicitly with `--godot-exe /path/to/binary` if automatic resolution is not wanted

### Python Dependencies Not Found
- `ModuleNotFoundError` usually means the virtual environment is not active. Run `source .venv/bin/activate` and confirm with `which python`, which should point inside `.venv/`.
- `error: externally-managed-environment` means `pip` is targeting the system interpreter. Create and activate the venv instead of installing globally.
- If `python3 -m venv` fails on `ensurepip`, see [Python Environment Setup](#python-environment-setup) for the apt package and the no-sudo bootstrap.

### Drones Not Launching
- Check flight plan CSV file format
- Verify ETD times are in the future
- Check console for error messages
- In integrated GA runs, no drone launches before the first `ETD` in the flight plan. If `--integrated-max-sim-time` is lower than that ETD, every score is `0.0` with `queue_remaining` equal to the full plan count in `godot_summary.json`. This is a too-short time cap, not a failure.

### Pathfinding Timeouts
- Increase pathfinding timeout in `WebSocketServer.py`
- Reduce number of concurrent drones
- Check graph connectivity
- If you see `Pathfinding error: cannot access local variable 'total_processing_time'`, update to a version with the timing-order fix in `WebSocketServer.py`

## References

- **Drone Specifications**: See `drone_models_specifications.txt`
- **Architecture Details**: See [ARCHITECTURE.md](ARCHITECTURE.md)
- **Godot Documentation**: https://docs.godotengine.org/
- **NetworkX Documentation**: https://networkx.org/

## License

[Add your license information here]

## Contributors

[Add contributor information here]

---

**Last Updated**: 2026-09-10 - Added Ex0 and Ex1 copy-paste CLI references (`Experiments/Ex0-Baseline/EX0_CLI_Comand.txt`, `Experiments/Ex1-ShtPath-GA/GA-Experiment1-Parameters.txt`) and aligned documented `--workers` defaults with code (`10`)
**Godot Version**: 4.3 (GL Compatibility)
**Python Version**: 3.9+

