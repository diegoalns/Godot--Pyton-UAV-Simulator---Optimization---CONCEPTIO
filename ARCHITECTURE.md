# Architecture Documentation

## System Overview

The Godot UAV Simulator is a distributed simulation system consisting of two main components:

1. **Godot Client** (GDScript): 3D visualization, physics simulation, and drone management
2. **Python Server**: Pathfinding and route planning

These components communicate via WebSocket protocol for real-time bidirectional data exchange.

## Repository Organization Layers

The repository is intentionally split into three layers:

1. **Runtime Layer**: Godot (`scripts/core`, `scripts/drone`, `scripts/ui`, `scenes`) and Python route service (`scripts/Python/Route Gen Basic Shortest Path`).
2. **Orchestration Layer**: Experiment runners under `Experiments/` (GA and baselines) that coordinate replications and scoring.
3. **Artifacts Layer**: Generated logs, per-replication outputs, run configs, and summaries under `logs/` and `Experiments/...` run folders.

## Execution Modes

The project supports four execution modes:

- **Manual interactive**: Python server and Godot editor are started manually.
- **Integrated**: Experiment script launches Python+Godot automatically (headless autorun).
- **Command**: Experiment script delegates execution to an external adapter command.
- **Mock**: Deterministic synthetic metrics with no real simulator process launch.

Canonical run-mode matrix and commands are maintained in `docs/RUN_MODES.md`.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    GODOT CLIENT                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         SimulationEngine (Main Coordinator)           │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌───────────┐ │  │
│  │  │DroneManager  │  │FlightPlanMgr │  │RoutePreReq│ │  │
│  │  └──────┬───────┘  └──────┬───────┘  └─────┬──────┘ │  │
│  │         │                 │                 │         │  │
│  │  ┌──────▼─────────────────▼─────────────────▼───────┐ │  │
│  │  │         WebSocketManager (Autoload)              │ │  │
│  │  └───────────────────────┬─────────────────────────┘ │  │
│  └───────────────────────────┼───────────────────────────┘  │
│                               │                               │
│  ┌───────────────────────────▼───────────────────────────┐  │
│  │         VisualizationSystem (3D Rendering)              │  │
│  │  - Terrain GridMap                                      │  │
│  │  - Drone Meshes                                         │  │
│  │  - Drone Labels (3D Text)                               │  │
│  │  - Camera Controls                                      │  │
│  └─────────────────────────────────────────────────────────┘  │
└───────────────────────────┬───────────────────────────────────┘
                            │ WebSocket (ws://localhost:8765)
                            │
┌───────────────────────────▼───────────────────────────────────┐
│                    PYTHON SERVER                               │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │         WebSocketServer (asyncio)                         │ │
│  │  ┌────────────────────────────────────────────────────┐ │ │
│  │  │         Route Pathfinder                            │ │ │
│  │  │  - NetworkX shortest path                           │ │ │
│  │  │  - Weighted graph traversal                         │ │ │
│  │  │  - Round-trip construction                          │ │ │
│  │  └────────────────────────────────────────────────────┘ │ │
│  │                                                          │ │
│  │  ┌────────────────────────────────────────────────────┐ │ │
│  │  │         Drone Registry                              │ │ │
│  │  │  - Active drone routes                              │ │ │
│  │  │  - Overfly times                                    │ │ │
│  │  │  - Registry cleanup                                │ │ │
│  │  └────────────────────────────────────────────────────┘ │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │         Graph Data (NetworkX)                            │ │
│  │  - Regular lattice graph                                │ │
│  │  - Node positions (lat, lon, alt)                       │ │
│  │  - Edge weights (distances)                             │ │
│  └──────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────┘
```

## Component Details

### Godot Client Components

#### 1. SimulationEngine (`scripts/core/simulation_engine.gd`)

**Purpose**: Main simulation coordinator and loop manager

**Responsibilities**:
- Manages simulation time and speed multiplier
- Coordinates all subsystems (drone manager, flight plans, visualization)
- Executes three-phase simulation loop:
  1. Route pre-requests (3000 simulation seconds before ETD)
  2. Drone creation from heap (at ETD)
  3. Fallback queue-based drone launching
- Updates all drones each physics frame
- Handles UI interactions

**Key Variables**:
- `simulation_time: float` - Current simulation time in seconds
- `speed_multiplier: float` - Time acceleration factor (0.5x to 5.0x via slider)
- `running: bool` - Simulation pause/play state
- `headless_mode: bool` - Visualization on/off toggle

**Dependencies**:
- `DroneManager` - Drone lifecycle
- `FlightPlanManager` - Flight plan loading
- `RoutePreRequestManager` - Route pre-request system
- `VisualizationSystem` - 3D rendering
- `SimpleUI` - User interface (includes ActiveDronesPanel)
- `SimpleLogger` - CSV logging
- `DebugLogger` (autoload node `AppDebugLogger`) - Advanced structured logging

**UI Integration**:
- Connects ActiveDronesPanel to DroneManager via `ui.set_drone_manager(drone_manager)`
- ActiveDronesPanel displays active drones with first waypoint times on left side of screen

#### 2. DroneManager (`scripts/core/drone_manager.gd`)

**Purpose**: Manages all active drone instances

**Responsibilities**:
- Creates drone instances from flight plans
- Updates all drones each frame
- Removes completed drones from memory (including visualization cleanup)
- Coordinates with visualization system

**Key Data Structures**:
- `drones: Dictionary` - Active drones keyed by ID (String → Drone)
- `visualization_system: VisualizationSystem` - Reference to visualization system for cleanup

**Key Functions**:
- `create_test_drone()` - Creates and initializes a drone
- `update_all()` - Updates all drones with delta time
- `remove_completed_drones()` - Removes completed drones and cleans up their visual representations (meshes and labels)
- `set_visualization_system()` - Sets VisualizationSystem reference and static reference for drone access

**Static Reference**:
- `visualization_system_ref: VisualizationSystem` - Static reference to VisualizationSystem for drone access to collision marker functions

#### 3. FlightPlanManager (`scripts/core/flight_plan_manager.gd`)

**Purpose**: Loads and manages flight plan queue

**Responsibilities**:
- Loads flight plans from CSV file
- Maintains sorted queue by ETD
- Provides plans needing route requests (3000 simulation seconds before ETD)
- Provides plans ready to launch (at ETD)
- Converts lat/lon to world coordinates

**Key Data Structures**:
- `flight_plan_queue: Array` - Sorted queue of flight plans (Dictionary objects)

**Key Functions**:
- `load_flight_plans()` - Loads CSV and sorts by ETD
- `get_plans_needing_route_requests()` - Returns plans needing pre-requests
- `get_next_pending_plans()` - Returns plans ready to launch
- `latlon_to_position()` - Geographic to world coordinate conversion

**CSV Format**:
- 13 columns: FlightPlanID, DronePortID, ETD, ETD_Seconds, OriginLat, OriginLon, OriginNodeID, DestinationLat, DestinationLon, DestinationNodeID, DroneModel, EstimatedFlightTime, Ceiling

#### 4. RoutePreRequestManager (`scripts/core/route_pre_request_manager.gd`)

**Purpose**: Manages route pre-request system (3000 simulation seconds before ETD)

**Responsibilities**:
- Sends route requests 3000 simulation seconds before ETD
- Stores successful routes in min-heap ordered by ETD
- Tracks pending requests and handles timeouts
- Provides routes from heap when ETD is reached

**Key Data Structures**:
- `successful_routes_heap: Array` - Min-heap of route entries (Dictionary with etd, plan_id, received_time)
- `route_storage: Dictionary` - Full route data keyed by plan_id
- `pending_route_requests: Dictionary` - Tracking pending requests

**Key Functions**:
- `send_route_request()` - Sends WebSocket route request
- `peek_earliest_route()` - Gets earliest route without removing
- `pop_earliest_route()` - Removes and returns earliest route
- `check_timeouts()` - Handles timed-out requests (10 second timeout)
- `cleanup_stale_routes()` - Removes routes with ETD far in the past
- `get_heap_stats()` - Returns heap and storage statistics
- `heap_insert()` - Inserts entry into min-heap
- `_bubble_up()` / `_bubble_down()` - Heap maintenance functions

**Memory Optimization**:
- Heap stores minimal metadata (~50 bytes per entry)
- Full route arrays stored separately in `route_storage`
- Maximum heap size: 1000 routes
- Automatic cleanup of stale routes (default: 5 minutes old)

**Constants**:
- `ROUTE_REQUEST_TIMEOUT: float = 10.0` - Timeout for pre-requests (system clock time)
- `MAX_HEAP_SIZE: int = 1000` - Maximum routes in heap

#### 5. WebSocketManager (`scripts/core/WebSocketManager.gd`)

**Purpose**: WebSocket client for Python server communication

**Type**: Autoload singleton (accessible globally)

**Responsibilities**:
- Manages WebSocket connection to Python server
- Handles connection, disconnection, and reconnection
- Sends messages to server
- Emits signals for received data

**Key Signals**:
- `connected` - Emitted when connection established
- `disconnected` - Emitted when connection lost
- `data_received(data)` - Emitted when data received from server

**Key Functions**:
- `connect_to_server(url)` - Initiates connection
- `send_message(message)` - Sends JSON string to server
- `_physics_process()` - Polls WebSocket each physics frame (effective rate follows engine physics tick; configured at 300 Hz by SimulationEngine during runtime)

**Configuration**:
- Default URL: `ws://localhost:8765`
- Reconnect delay: 3 seconds
- Polling cadence: Physics-frame driven (runtime physics tick target is 300 Hz)

#### 6. VisualizationSystem (`scripts/core/visualization_system.gd`)

**Purpose**: 3D rendering and camera controls

**Responsibilities**:
- Renders terrain using GridMap
- Displays drone meshes (LRVTOL_UAV.glb model)
- Displays 3D labels above drones showing ID, model, speed, and status
- Manages camera (balloon-style free camera)
- Handles user input for camera movement
- Manages lighting and environment

**Key Components**:
- `terrain_gridmap: GridMap` - Terrain visualization
- `gridmap_manager: GridMapManager` - Terrain data management
- `drone_meshes: Dictionary` - Visual drone representations (String → Node3D)
- `drone_labels: Dictionary` - 3D text labels above drones (String → Label3D)
- `route_lines: Dictionary` - Route line visualizations (String → MeshInstance3D)
- `route_colors: Dictionary` - Route line colors per drone (String → Color)
- `collision_markers: Array` - Persistent collision markers (Array of marker dictionaries)
- `collision_marker_container: Node3D` - Container node for all collision markers
- `balloon_ref: CharacterBody3D` - Camera controller

**Label System**:
- `show_drone_labels: bool` - Enable/disable label display (default: true)
- `label_offset_height: float` - Vertical offset above drone in meters (default: 50.0)
- `label_font_size: int` - Font size in pixels (default: 32)
- `label_pixel_size: float` - Pixel size for 3D text scaling (default: 1.0)
- `label_billboard_mode: BaseMaterial3D.BillboardMode` - Billboard mode for camera-facing labels (default: BILLBOARD_ENABLED)
- Labels display: drone ID, model type, current speed (if moving), and status (waiting/completed)
- Labels automatically update position and text as drones move

**Route Line Visualization**:
- `route_line_width: float` - Width of route lines in meters (default: 5.0)
- `route_line_opacity: float` - Opacity of route lines 0.0-1.0 (default: 0.7)
- Route lines are displayed as colored 3D meshes following the drone's waypoint path
- Each drone gets a unique color based on its ID (HSV color space)
- Route lines are automatically shown when drone is flying and hidden when completed
- Route lines are cleaned up when drones are removed

**Drone Port Visualization**:
- Drone ports are visualized as black box meshes (500m x 2m x 500m) at their geographic locations
- Ports are added via `add_drone_port()` function during initialization
- Port positions are extracted from flight plan CSV data

**Collision Marker System**:
- `show_collision_markers: bool` - Enable/disable collision marker display (default: true)
- `collision_marker_size: float` - Size of collision markers in meters (default: 10.0)
- `collision_marker_color: Color` - Orange/yellow color for markers (default: Color(1.0, 0.65, 0.0, 0.8))
- Persistent markers are created at collision midpoint when collisions are detected
- Markers remain visible for the entire simulation duration
- Each marker displays collision information (drone IDs and distance) via Label3D
- Markers are stored in `collision_markers` array with metadata (position, drone IDs, distance, simulation time)

**Key Functions**:
- `add_drone()` - Adds visual representation, label, and route line for drone
- `update_drone_position()` - Updates drone mesh position, label text, and route line
- `remove_drone()` - Removes drone visualization, label, and route line
- `add_drone_port()` - Adds visual representation for a drone port (black box mesh)
- `add_collision_marker()` - Creates persistent collision marker at specified position
- `clear_collision_markers()` - Removes all collision markers from visualization
- `set_show_collision_markers()` - Toggles visibility of collision markers
- `get_collision_marker_count()` - Returns current number of collision markers
- `setup_terrain()` - Initializes terrain GridMap
- `setup_collision_markers()` - Initializes collision marker container
- `_update_route_line()` - Updates route line visualization for a drone
- `_create_route_line_mesh()` - Creates 3D mesh for route line visualization

**Camera Controls**:
- WASD: Move camera
- Mouse: Rotate camera
- Mouse wheel: Adjust speed
- Escape: Toggle mouse capture

#### 7. GridMapManager (`scripts/core/gridmap_manager.gd`)

**Purpose**: Manages terrain GridMap data loading and population

**Responsibilities**:
- Loads terrain altitude data from CSV file
- Maps CSV coordinates directly to grid indices
- Populates GridMap with terrain tiles
- Provides terrain altitude queries

**Key Data Structures**:
- `terrain_data: Dictionary` - CSV data storage
- `lat_to_grid_z: Dictionary` - Latitude to grid Z index mapping
- `lon_to_grid_x: Dictionary` - Longitude to grid X index mapping
- `grid_to_altitude: Dictionary` - Grid coordinates to altitude mapping

**Key Functions**:
- `initialize_gridmap()` - Initializes GridMap node
- `load_terrain_data()` - Loads CSV terrain data; after mapping, logs `terrain_alignment_verified` by comparing the first CSV point’s tile center (using the same Z inversion as `populate_gridmap`) to `latlon_to_world_position`
- `populate_gridmap()` - Populates GridMap with terrain tiles
- `get_terrain_altitude_at_position()` - Queries altitude at world position

**CSV File**:
- `Filtered_FAA_UAS_FacilityMap_Data_LGA.csv` - FAA UAS facility map data
- Format: CEILING (feet), LATITUDE, LONGITUDE

**Grid Properties**:
- `tile_width: float = 705.11` - Tile width in meters (X axis, longitude)
- `tile_height: float = 927.67` - Tile height in meters (Z axis, latitude)
- Grid spacing: 1/120 degrees (~0.008333 degrees)

#### 8. SimpleLogger (`scripts/core/simple_logger.gd`)

**Purpose**: CSV logging system for simulation data

**Type**: Singleton (via static `instance` variable)

**Responsibilities**:
- Logs drone states to CSV files
- Logs collision events
- Manages log file creation and writing

**Key Log Files**:
- `logs/simple_log.csv` - Main drone states (Time, DroneID, Position, etc.)
- `logs/collision_log.csv` - Collision events (start/end, distances, positions)

**Key Functions**:
- `create_log_file()` - Creates log files and directories
- `update()` - Called each frame to log data
- `log_drone_states()` - Logs current drone positions and states
- `log_collision_event()` - Logs collision start/end events

**Logging Interval**:
- `log_interval: float = 10.0` - Logs every 10 seconds of simulation time

#### 9. DebugLogger (`scripts/core/DebugLogger.gd`)

**Purpose**: Advanced logging system with categories, verbosity levels, and unified fixed-width table format

**Type**: Autoload singleton (when configured in Project Settings)

**Responsibilities**:
- Fixed-width table output (unified with Python sim_logger)
- Categorized logging (ROUTE, WEBSOCKET, DRONE, etc.)
- Verbosity level control (SILENT, MINIMAL, NORMAL, VERBOSE)
- Log level filtering (DEBUG, INFO, WARNING, ERROR)
- Timestamp and formatting support
- Structured event helpers (`log_event_info`, `log_event_warning`, `log_event_error`)

**Key Enums**:
- `LogLevel`: DEBUG, INFO, WARNING, ERROR
- `VerbosityLevel`: SILENT, MINIMAL, NORMAL, VERBOSE
- `Category`: ROUTE, WEBSOCKET, DRONE, SIMULATION, TERRAIN, VISUALIZATION, HEAP, FLIGHT_PLAN, GENERAL

**Key Functions**:
- `log_debug()` / `log_info()` / `log_warning()` / `log_error()` - Category-based logging
- `print_table_line()` - Direct fixed-width row output for scripts without full logger flow
- `format_table_row_string()` - Static formatter matching Python column widths
- `get_table_header()` - Header row for fixed-width table
- `set_table_format()` - Toggle fixed-width vs legacy format

**Configuration**:
- `use_table_format: bool = true` - Fixed-width columns (default)
- `current_log_level: LogLevel = LogLevel.INFO` - Minimum log level
- `current_verbosity: VerbosityLevel = VerbosityLevel.NORMAL` - Detail level
- `category_enabled: Dictionary` - Per-category enable/disable flags
- `always_include_data: bool = true` - Keeps key/value payload visible

#### 10. SimpleUI (`scripts/ui/simple_ui.gd`)

**Purpose**: User interface controls for simulation

**Responsibilities**:
- Start/Pause button control
- Speed multiplier slider (0.5x to 5.0x)
- Headless mode toggle
- Drone port selector
- Time display (simulation time and real runtime)
- Active drones panel integration

**Key Signals**:
- `start_requested` - Emitted when start button pressed
- `pause_requested` - Emitted when pause button pressed
- `speed_changed(multiplier)` - Emitted when speed slider changes
- `headless_mode_changed(enable)` - Emitted when headless toggle changes
- `port_selected(port_id)` - Emitted when port selector changes

**Key Components**:
- `active_drones_panel: ActiveDronesPanel` - Panel displaying active drones with first waypoint times

**Key Functions**:
- `setup_ui()` - Creates UI elements and active drones panel
- `set_drone_ports()` - Populates port selector dropdown
- `set_drone_manager()` - Connects active drones panel to DroneManager
- `update_time()` - Updates time display label
- `update_status()` - Updates status label text

#### 10a. ActiveDronesPanel (`scripts/ui/active_drones_panel.gd`)

**Purpose**: Displays active (flying) drones with their first waypoint times

**Responsibilities**:
- Shows list of active drones on left side of screen
- Displays drone ID and first waypoint time (simulation time)
- Updates in real-time as drones become active or complete
- Sorts drones by first waypoint time (earliest first)

**Key Variables**:
- `drone_manager: DroneManager` - Reference to DroneManager for accessing drone data
- `panel_width: int` - Width of panel in pixels (default: 250)
- `title_font_size: int` - Font size for title label (default: 18)
- `drone_entry_font_size: int` - Font size for drone entries (default: 14)

**Key Variables**:
- `update_timer: float` - Timer for throttling updates (default: 0.0)
- `update_interval: float` - Update interval in seconds (default: 0.1 = 10 updates per second)
- `last_active_drone_ids: Array` - Array of drone IDs from last update for change detection
- `max_displayed_drones: int` - Maximum number of drones to display before scrolling (default: 20)

**Key Functions**:
- `setup_panel()` - Creates and configures panel UI elements
- `set_drone_manager()` - Sets DroneManager reference
- `update_drone_list()` - Updates displayed list of active drones
- `create_drone_entry()` - Creates UI entry for a single drone

**Display Criteria**:
- Drone must not be completed (`completed = false`)
- Drone must not be waiting for route response (`waiting_for_route_response = false`)
- Drone must have valid first waypoint time (`first_waypoint_time >= 0.0`)

**Update Frequency**:
- Updates are throttled to 10 updates per second (0.1 second interval) for performance
- Uses change detection to only update UI when drone list changes

#### 11. Drone (`scripts/drone/drone.gd`)

**Purpose**: Individual drone behavior and movement

**Type**: Extends `Area3D` (for collision detection)

**Responsibilities**:
- Holonomic movement along waypoint route
- Route request/response handling
- Collision detection via Area3D signals
- Waypoint arrival detection
- Wait period handling (e.g., 60s at destination)

**Key State Variables**:
- `current_position: Vector3` - Current world position
- `route: Array` - Array of waypoint dictionaries
- `current_waypoint_index: int` - Current waypoint index
- `waiting_for_route_response: bool` - Route request pending flag
- `first_waypoint_time: float` - Simulation time when first waypoint should be reached (seconds, -1.0 if not set)
- `is_colliding: bool` - Collision state
- `collision_partners: Array` - IDs of colliding drones

**Key Functions**:
- `initialize()` - Sets up drone with start/end positions and model
- `update()` - Updates position and checks waypoint arrival
- `_process_server_route()` - Converts Python route to Godot waypoints
- `_on_route_response_received()` - Handles WebSocket route response
- `_on_area_entered()` / `_on_area_exited()` - Collision detection handlers

**Movement Model**:
- Holonomic (direct waypoint following, no physics constraints)
- Speed varies by flight phase (takeoff: 60%, cruise: 100%, approach: 70%, landing: 40%)
- Waypoint arrival threshold: 5.0 meters

**Collision Detection**:
- Radius: 5.0 meters per drone (10m diameter safety zone)
- Automatic via Area3D signals
- Logged to CSV via SimpleLogger

### Python Server Components

#### 1. WebSocketServer (`scripts/Python/Route Gen Basic Shortest Path/WebSocketServer.py`)

**Purpose**: WebSocket server for route planning requests

**Responsibilities**:
- Listens for route requests from Godot
- Coordinates pathfinding via NetworkX shortest-path algorithm
- Maintains active drone registry
- Sends route responses back to Godot
- Writes Python-side CSV route/timing logs for post-run analysis
- Uses Godot-provided `max_speed` directly for route timing and waypoint speeds
- Uses flight plan `etd_seconds` as pathfinding `start_time` for temporal planning

**Key Functions**:
- `websocket_handler()` - Main message handler
- `cleanup_registry()` - Removes completed drones from registry
- `calculate_overfly_times()` - Computes when drone will pass each node
- `find_closest_node()` - Finds nearest graph node to coordinates

**Message Types**:
- `request_route` - Route planning request from Godot
- `drone_completed` - Notification that drone finished route

**Registry Structure**:
```python
{
  "drone_id": {
    "route_nodes": [node1, node2, ...],  # List of str
    "overfly_times": [t1, t2, ...],      # List of float (seconds)
    "start_time": float                    # Route start time (ETD-based)
  }
}
```

#### 2. Route Pathfinder (`scripts/Python/Route Gen Basic Shortest Path/shortest_pathfinder.py`)

**Purpose**: Weighted shortest-path route planning module

**Algorithm**: NetworkX `shortest_path(..., weight="weight")`

**Key Features**:
- Plans complete round-trip routes (origin → destination → origin)
- Uses weighted shortest path on the graph without multi-agent conflict constraints
- Supports wait periods at destination (default: 60 seconds)
- Timeout: 3 seconds maximum pathfinding time

**Key Parameters**:
- `conflict_threshold: float` - Compatibility parameter (currently unused)
- `max_search_iterations: int` - Compatibility parameter (currently unused)
- `round_trip: bool` - Whether to plan return journey (True)
- `wait_time_at_destination: float` - Wait duration in seconds (60.0)

**Returns**:
- `(path_nodes, overfly_times)` - Tuple of node list and time list, or None if no path found

**Note**: The algorithm plans complete round-trip routes including:
- Outbound path: origin → destination
- Wait period: 60 seconds at destination
- Return path: destination → origin

#### 3. Graph Loader (`scripts/Python/Route Gen Basic Shortest Path/graph_loader.py`)

**Purpose**: Loads graph data from pickle file with comprehensive validation

**Graph Format**:
- NetworkX graph structure (Graph, DiGraph, MultiGraph, or MultiDiGraph)
- Nodes have `pos` attribute: `(lat, lon, alt)` tuple
- Edges have `weight` attribute: distance in meters
- Node IDs: Format `L{level}_X{x}_Y{y}` (e.g., `L0_X0_Y0`)

**Key Function**:
- `load_graph_from_pickle()` - Loads graph from `regular_lattice_graph.pkl`

**Validation Performed**:
- Checks graph type validity
- Validates graph is not empty
- Ensures all nodes have `pos` attribute (creates if missing from lat/lon/altitude)
- Validates edges have `weight` attribute
- Checks graph connectivity (connected/weakly connected/strongly connected)

#### 4. Coordinate Constants (`scripts/Python/Route Gen Basic Shortest Path/coordinate_constants.py`)

**Purpose**: Shared coordinate conversion constants

**Key Constants**:
- `ORIGIN_LAT_DEGREES = 40.55417343` - Reference latitude
- `ORIGIN_LON_DEGREES = -73.99583928` - Reference longitude
- `METERS_PER_DEGREE_LAT = 111320` - Meters per degree latitude
- `METERS_PER_DEGREE_LON` - Calculated based on latitude (~84,613 m/deg at 40.5°N)

**Key Functions**:
- `get_coordinate_bounds_meters()` - Returns coordinate bounds in meters
- `degrees_to_meters()` - Converts lat/lon degrees to meters relative to origin

#### 5. Python Structured Logger (`scripts/Python/Route Gen Basic Shortest Path/sim_logger.py`)

**Purpose**: Structured logging with format options; default fixed-width table matches Godot

**Responsibilities**:
- Provide `log_event(level, category, event, **fields)` API
- Fixed-width table format (default) - same column widths as Godot DebugLogger
- JSON-line format for dashboards and parsing
- Pretty format for compact human-readable output
- CSV writer for per-waypoint route timing output

**Column Layout (table format)**:
- ts (12), level (8), category (14), source (6), event (32), data (150)

**Runtime Controls**:
- `SIM_LOG_LEVEL`: minimum level (`DEBUG|INFO|WARNING|ERROR`, default: INFO)
- `SIM_LOG_FORMAT`: `table` (default), `json`, or `pretty`
- `SIM_ROUTES_RECEIVED_CSV`: optional output file path override for Python route timing CSV

**Python CSV Outputs**:
- `logs/python_routes_received.csv` - One row per waypoint for each received route (`plan_id`, node IDs, overfly time, segment/cumulative durations)
- Startup behavior: target file is cleared when `WebSocketServer.py` starts, then rows are appended for that run
- Integrated GA behavior: each replication overrides this target with `SIM_ROUTES_RECEIVED_CSV` to write `tmp/rep_*/python_routes_received.csv`

#### 6. GA Experiment Runner (`Experiments/Ex1-ShtPath-GA/GA-Experiment1.py`)

**Purpose**: Simulation-based combinatorial optimization for air-corridor edge-group orientation using a binary Genetic Algorithm.

Parameter reference file (defaults + runtime GA behavior): `Experiments/Ex1-ShtPath-GA/GA-Experiment1-Parameters.txt`.

**Responsibilities**:
- Loads lattice graph and builds corridor-group variables using the same grouping logic as `Visualize_Air_Corridor_Binary_Edge_Selection_updated.py`
- Uses contiguous air-corridor segment grouping (layer + axis + fixed index + segment ID) with forward/reverse sets split by grid-direction sign
- Represents one chromosome as a full binary orientation vector across all groups
- Evaluates chromosomes with common random numbers per generation (shared seed set)
- Computes fitness as `sum(collisions) + no_path_count + timeout_count` across replications
- Uses normalized selection score (`fitness / replications`) for generation-best choice, elitism ordering, tournament parent selection, and early-stop improvement checks so selection remains per-replication comparable
- Tracks route-failure components per chromosome evaluation:
  - `no_path_count` (Python planner no-path)
  - `timeout_count` (Python planner timeout)
  - `server_error_count` (Python server-side validation/processing errors)
  - `no_response_count` (Godot-side no response received in time)
  - `no_valid_route_count` (Godot-side response missing valid route payload)
  - `invalid_count` remains `no_path_count + timeout_count` for GA invalid-pressure logic
- Applies invalid rule tracking: `invalid_count = no_path_count + timeout_count` is still tracked for diagnostics
- Caches evaluation results by `(chromosome_bitstring, seed_set_signature)`
- Evaluates chromosome batches in parallel with a thread pool (`--workers`, default `18`) and cache-aware de-duplication
- Executes GA operators: tournament selection, uniform crossover, bit-flip mutation, elitism, generational replacement
- Enforces GA runtime guards for stability in small diagnostics (`population >= 2`, `0 <= elitism <= population`, `workers >= 1`)
- Enforces post-phase guardrails (`final_validation_top_k >= 1`, `final_validation_seeds >= 1`, `sensitivity_max_bits >= 0`)
- Supports a safe fully-elitist generation step when `population == elitism` (no offspring phase)
- GA default configuration now uses `population=120` (CLI override still supported)
- Ex2 variant at `Experiments/Ex2-ShtPath-GA 16 Workers/GA-Experiment1.py` defaults to `workers=16`
- Supports early stopping when no best-fitness improvement occurs for a fixed patience window
- Performs configurable final held-out validation (`--final-validation-top-k`, `--final-validation-seeds`) and optional one-bit sensitivity analysis (`--run-sensitivity`, `--sensitivity-max-bits`) from the best chromosome
- Exposes post-phase scaling controls for integrated testing and diagnostics:
  - `--final-validation-top-k`
  - `--final-validation-seeds`
  - `--run-sensitivity/--no-run-sensitivity`
  - `--sensitivity-max-bits` (`0` means all chromosome bits)

**TensorBoard Metrics (per generation)**:
- `best_individual/selection_score`
- `best_individual/fitness_raw`
- `best_individual/planner_invalid_count`
- `best_individual/seed_fitness_std`
- `population/selection_score_mean`
- `population/selection_score_std`
- `population/fitness_raw_mean`
- `population/fitness_raw_std`
- `population/invalid_individuals_count`
- `population/invalid_individuals_ratio`
- `population/diversity_hamming_mean`
- `population/no_path_count_mean`
- `population/planner_timeout_count_mean`
- `population/server_error_count_mean`
- `population/no_response_count_mean`
- `population/no_valid_route_count_mean`
- `generation/seconds`
- Terminal generation output mirrors the same schema and still includes:
  - `best_seed_scores`: per-seed best-individual fitness as `seed:score` pairs
- Terminal post-phase output now reports progress for long-running steps:
  - `[FinalVal ...]` start/progress/end lines during held-out top-k validation
  - `[Sensitivity ...]` start/progress/end lines during one-bit sweep, periodic every 10 bits, or explicit skipped line when `--no-run-sensitivity` is used
- Runtime dashboard behavior:
  - TensorBoard can be auto-launched by `GA-Experiment1.py` at run start
  - Default TensorBoard port is `6007` (configurable via `--tensorboard-port`)
  - Optional auto-open browser to configured URL (`--tensorboard-host`, `--tensorboard-port`)
  - Can be disabled with `--no-auto-launch-tensorboard` and `--no-auto-open-tensorboard-browser`
  - TensorBoard subprocess logs are persisted per run in `tensorboard_process.log`
  - Auto-launch validates short-lived startup: if the TensorBoard process exits immediately, launch is treated as failed and a warning is emitted
  - Scalar metrics are flushed each generation to improve live dashboard update consistency
  - **Log mode** (`--log-mode`, default `normal`):
    - `quiet`: Python `SIM_LOG_LEVEL=ERROR`, `SIM_LOG_FORMAT=json`; Godot `GA_LOG_LEVEL=quiet`
    - `normal`: Python `SIM_LOG_LEVEL=INFO`, `SIM_LOG_FORMAT=table`; Godot `GA_LOG_LEVEL=normal`
    - `verbose`: Python `SIM_LOG_LEVEL=DEBUG`, `SIM_LOG_FORMAT=json`; Godot `GA_LOG_LEVEL=verbose`
  - **Artifact mode** (`--artifact-mode`, default `keep_all`):
    - `keep_all`: keep all per-replication files
    - `keep_failures`: keep only replications with route-failure counters > 0
    - `minimal`: keep only `python_server.log`, `godot.log`, `collision_log.csv`, `python_routes_received.csv`, `godot_summary.json`
  - Godot core writers currently treat only `GA_LOG_LEVEL=quiet` specially (`simple_logger.gd` and `simulation_engine.gd`).

**Output Artifacts (run folder)**:
- `generation_metrics.csv`
  - Explicit schema using `best_individual_*`, `population_*`, `generation_seconds`, and `seed_signature_base`
  - Includes `best_individual_seed_fitness_std` for best-individual seed variability tracking
- `best_solution.json`
  - Explicit final keys: `best_individual_*` and `seed_signature_heldout`
- `final_validation_summary.json`
  - Explicit final-validation keys: `seed_signature_heldout`, `heldout_seed_count`, and `candidate_*` records in `top_results`
- `sensitivity_analysis.csv` (generated only when sensitivity is enabled)
- `tensorboard/` event files
- `terminal_output.txt` (mirrored GA terminal stdout/stderr for that run)

**Simulation Adapter Contract**:
- Integrated mode (default):
  - Builds per-replication oriented graph pickle from chromosome-selected horizontal edges (vertical edges preserved)
  - Performs preflight validation before GA loop:
    - Resolves `--godot-exe` from executable path, PATH command, or Godot binary directory
    - Falls back to auto-discovery in common local folders when explicit `--godot-exe` resolution fails
    - Verifies Python WebSocket server script exists
    - Verifies `project.godot` exists in `--godot-project-dir`
    - Runs Godot with `--version` to confirm the binary starts (fails fast on wrong path or missing DLLs)
  - Starts Python `WebSocketServer.py` with environment overrides:
    - `GRAPH_PICKLE_PATH=<rep_oriented_graph.pkl>`
    - `WS_SERVER_HOST=127.0.0.1`
    - `WS_SERVER_PORT=<rep_port>` (replication-specific port isolation for parallel workers)
    - `SIM_LOG_LEVEL=<mode-mapped>`
    - `SIM_LOG_FORMAT=<mode-mapped>`
    - `SIM_ROUTES_RECEIVED_CSV=<rep_python_routes_received.csv>` (replication-specific route timing CSV isolation)
  - Retries Python server startup with automatic new-port fallback when bind/startup fails under parallel contention
- Startup readiness accepts either `server_running` in server logs or a successful TCP connect on the assigned replication port (supports quiet logging where INFO markers may be absent)
  - After server signals ready, starts Godot in headless batch mode via environment flags (below); if Godot exits within 3 seconds, raises with Godot log path and log tail for debugging:
- Early Godot exits are escalated only when exit code is non-zero (fast clean exits are valid for short smoke runs).
  If non-zero within the early window, raises with Godot log path and log tail for debugging:
    - `GA_AUTORUN=1`
    - `GA_HEADLESS=1`
    - `GA_MAX_SIM_TIME=<seconds>`
    - `GA_SUMMARY_JSON=<path>`
    - `GA_WEBSOCKET_URL=ws://127.0.0.1:<rep_port>`
    - `GA_COLLISION_LOG_CSV=<rep_collision_log.csv>`
    - `GA_SIMPLE_LOG_CSV=<rep_simple_log.csv>`
    - `GA_LOG_LEVEL=<mode-mapped>`
  - Collects objective signals from runtime artifacts:
    - Collisions from per-replication collision CSV (`COLLISION_START` rows)
    - Pathfinder failures from Python server logs (`pathfinding_no_path`, `pathfinding_timeout`)
    - Python server errors from log events (`route_request_rejected_invalid_nodes`, `pathfinding_error`)
    - Godot no-response events (`pre_request_timeout_no_response`, `flight_cancelled_route_timeout`)
    - Godot invalid-route-payload events (`route_request_failed_no_valid_route`)
  - Event parsing for long names also accepts fixed-width-truncated variants to avoid undercounting when reading table-formatted logs
- Command-mode evaluator is still supported for external adapters.

#### 6a. Baseline Undirected-Orientation Runner (`Experiments/Ex0-Baseline/Baseline Undirected Graph test.py`)

**Purpose**: Evaluate baseline performance over repeated replications using the original graph orientation (no optimization, no edge reorientation).

**Responsibilities**:
- Reuses GA integrated simulation path by dynamically loading `GA-Experiment1.py` and using its `SimulationAdapter`
- Registers the dynamically loaded GA module in `sys.modules` before execution to keep import-time decorators compatible
- Uses the raw graph from `regular_lattice_graph.pkl` with original edge directions preserved
- Executes `N` replications (default `100`) in parallel (`--workers`, default `24`)
- Captures GA-aligned per-replication metrics:
  - `collisions`
  - `no_path_count`
  - `timeout_count`
  - `server_error_count`
  - `no_response_count`
  - `no_valid_route_count`
  - derived `invalid_count` and `fitness = collisions + no_path_count + timeout_count`

**Output Artifacts**:
- `baseline_experiment.csv` (one row per replication)
- `baseline_summary.csv` (aggregate mean/std/min/max/sum and rates)
- `baseline_run_config.json` (run settings + seed list)

#### 6b. Baseline Directed-5 Runner (`Experiments/Ex0-Baseline/Baseline Directed Graph 5 test.py`)

**Purpose**: Compare five fixed directed orientation configurations using the same integrated simulation pipeline.

**Responsibilities**:
- Builds and evaluates five corridor-orientation presets (all-forward, all-reverse, alternating, random A, random B)
- Reuses `SimulationAdapter` from `GA-Experiment1.py`
- Executes replications per orientation and writes per-orientation summaries (`--workers` default `18`)

**Output Artifacts**:
- `graph_0..graph_4/directed_experiment.csv` (per-replication metrics)
- `graph_0..graph_4/directed_summary.csv` (aggregate metrics including collision/fitness mean and std)
- `graph_0..graph_4/directed_run_config.json` (config + seed info)

## Logging Standardization (Fixed-Width Table)

The simulation uses a unified fixed-width table format across both runtimes:

- **Godot**: `DebugLogger` emits `ts | level | category | source | event | data` rows
- **Python**: `sim_logger.py` uses the same column layout when `SIM_LOG_FORMAT=table` (default)

Columns: ts (12), level (8), category (14), source (6), event (32), data (150). Source is `godot` or `python`.

This improves:
- **Readability**: aligned columns for quick terminal scanning
- **Consistency**: one format for both runtimes
- **Correlation**: same structure makes it easy to merge Godot and Python logs

## Data Flow

### Route Pre-Request Flow (3000 simulation seconds before ETD)

```
SimulationEngine (simulation_time)
    │
    ├─> FlightPlanManager.get_plans_needing_route_requests()
    │   └─> Returns plans where (ETD - 3000s) <= simulation_time
    │
    ├─> RoutePreRequestManager.send_route_request(plan)
    │   ├─> Creates WebSocket message
    │   ├─> Includes etd_seconds from flight plan
    │   ├─> WebSocketManager.send_message(message)
    │   └─> Tracks request in pending_route_requests
    │
    └─> Python Server receives request
        ├─> Route Pathfinder finds route using ETD as start_time
        ├─> Stores route in registry
        └─> Sends response back
            │
            └─> RoutePreRequestManager receives response
                ├─> Stores route in heap (ordered by ETD)
                └─> Stores full route in route_storage
```

### Drone Launch Flow (at ETD)

```
SimulationEngine (simulation_time >= ETD)
    │
    ├─> RoutePreRequestManager.peek_earliest_route()
    │   └─> Checks if earliest route ETD <= simulation_time
    │
    ├─> RoutePreRequestManager.pop_earliest_route()
    │   └─> Removes route from heap and returns it
    │
    ├─> DroneManager.create_test_drone()
    │   ├─> Creates Drone instance
    │   ├─> Initializes with precomputed route
    │   └─> Adds to visualization system
    │
    └─> Drone.update() (each physics frame)
        ├─> Moves toward current waypoint
        ├─> Checks waypoint arrival
        └─> Updates collision detection
```

### Fallback Route Request Flow (if no pre-request)

```
Drone.initialize() (no precomputed route)
    │
    ├─> Creates route request message
    ├─> WebSocketManager.send_message(message)
    ├─> Starts timeout timer (90 seconds)
    │
    └─> Waits for response
        │
        ├─> Response received
        │   ├─> Drone._on_route_response_received()
        │   ├─> Processes route waypoints
        │   └─> Starts movement
        │
        └─> Timeout (90 seconds)
            └─> Cancel flight (no default route fallback)
```

## Coordinate Systems

### Geographic Coordinates (Lat/Lon)

- **Format**: Decimal degrees
- **Reference Point**: 
  - Latitude: 40.55417343°
  - Longitude: -73.99583928°
- **Usage**: Flight plan CSV, Python graph nodes, WebSocket messages

### World Coordinates (Godot)

- **Format**: Vector3 (x, y, z) in meters
- **Axes**:
  - X: East/West (positive = East)
  - Y: Up/Down (positive = Up, altitude)
  - Z: North/South (positive = South, inverted from lat)
- **Conversion**: `latlon_to_position()` function in FlightPlanManager

### Graph Node IDs

- **Format**: `L{level}_X{x}_Y{y}` (e.g., `L0_X0_Y0`)
- **Purpose**: O(1) graph lookup instead of O(n) coordinate matching
- **Usage**: Flight plan CSV, WebSocket route requests

## Timing Systems

### Simulation Time

- **Type**: `float` (seconds)
- **Updates**: Every physics frame (300 Hz)
- **Formula**: `simulation_time += time_step * speed_multiplier`
- **Usage**: ETD comparison, route timing, collision logging

### System Clock Time

- **Type**: `float` (seconds since Unix epoch)
- **Purpose**: Network latency measurement, timeout calculation
- **Usage**: WebSocket message timestamps, pathfinding duration

### Hybrid Timing

Both simulation time and system clock time are tracked for:
- **Simulation Logic**: Uses simulation time (affected by pause/speed)
- **Network Metrics**: Uses system clock time (real-world seconds)

## Memory Management

### Route Pre-Request System

- **Heap Storage**: Minimal metadata only (~50 bytes per entry)
- **Full Route Storage**: Separate dictionary for large route arrays
- **Maximum Heap Size**: 1000 routes (prevents unbounded growth)
- **Cleanup**: Routes removed from heap when drone launches

### Drone Registry (Python)

- **Structure**: Dictionary mapping drone_id to route data
- **Cleanup**: Removed when drone completes route (last overfly time < current time)
- **Cleanup Trigger**: On each route request (before pathfinding)

### Drone Instances (Godot)

- **Storage**: Dictionary in DroneManager
- **Cleanup**: Removed when `completed = true` (includes visualization cleanup: meshes and labels)
- **Cleanup Trigger**: `remove_completed_drones()` called each frame
- **Cleanup Order**: 
  1. Remove from visualization system (meshes and labels)
  2. Free drone node from scene tree
  3. Remove from dictionary

## Performance Characteristics

### Physics Rate

- **Rate**: 300 Hz (300 physics ticks per second)
- **Purpose**: Smooth drone movement and collision detection
- **Configuration**: `Engine.physics_ticks_per_second = 300` in SimulationEngine

### Route Pre-Request Timing

- **Pre-Request Window**: 3000 simulation seconds before ETD
- **Purpose**: Allows pathfinding to complete before launch
- **Timeout**: 10 seconds for pre-requests (system clock time, not simulation time)
- **Note**: Timeout uses system clock because network communication happens in real-time

### Pathfinding Timeout

- **Pathfinding Timeout**: 3 seconds (system clock time)
- **Purpose**: Prevents hanging on complex pathfinding problems
- **Fallback**: Returns timeout status, drone flight cancelled

### Route Request Timeout (Individual)

- **Timeout**: 90 seconds (simulation time)
- **Purpose**: Prevents drones waiting indefinitely for routes
- **Behavior**: Always cancels flight (no default route fallback)

## Error Handling

### WebSocket Connection

- **Reconnection**: Automatic with 3-second delay
- **Failed Sends**: Logged as warnings, requests retried on reconnect
- **State Tracking**: `is_connected` flag prevents sending when disconnected

### Pathfinding Failures

- **No Path Found**: Returns `status: "no_path"`, flight cancelled
- **Timeout**: Returns `status: "timeout"`, flight cancelled
- **Graph Node Not Found**: Returns `status: "error"`, flight cancelled
- **Timing Variable Order**: `total_processing_time` is computed before CSV logging in the success path to avoid `UnboundLocalError`

### Route Response Handling

- **Invalid JSON**: Flight cancelled with debug message
- **Missing Route Data**: Flight cancelled with debug message
- **No Path Found** (`status: "no_path"`): Flight cancelled with debug message
- **Pathfinding Error** (`status: "error"`): Flight cancelled with debug message
- **Pathfinding Timeout** (`status: "timeout"`): Flight cancelled with debug message
- **Client Timeout** (90s): Flight cancelled with debug message
- **Wrong Drone ID**: Ignored (signal disconnection prevents processing)
- **Note**: Drones only fly if they receive a valid route from Python server (`status: "success"` with route array)

## Extension Points

### Adding New Drone Models

1. Add model case to `Drone._set_model_attributes()`
2. Update `drone_models_specifications.txt`
3. Ensure CSV includes model name

### Modifying Pathfinding Algorithm

1. Replace `shortest_pathfinder.py` with new algorithm
2. Maintain interface: `(graph, start_node, goal_node, start_time, speed, registry, ...)`
3. Return format: `(path_nodes, overfly_times)` or `None`

### Adding New Message Types

1. Add message type to WebSocket handler in Python
2. Add corresponding signal handler in Godot
3. Update protocol documentation

### Custom Visualization

1. Modify `VisualizationSystem` rendering functions
2. Add new mesh types to `add_drone()`
3. Customize camera controls in `_process()` and `_input()`

### Adding New Experiment Folders

1. Create a new `Experiments/ExN-*` folder using `docs/EXPERIMENT_TEMPLATE.md`.
2. Reuse existing execution-mode contract (`integrated`, `command`, `mock`) instead of introducing a new one-off evaluator mode.
3. Keep simulator runtime logic in `scripts/` and place experiment-specific orchestration, configs, and analysis in the experiment folder.
4. Write outputs to experiment-owned run directories to preserve isolation across experiments.

---

## Additional Components

### Local tooling (Windows)

- **`open_in_godot_editor.bat`** (project root): starts the Godot **editor** with `--editor --path` pointed at this folder. Use this (or the same CLI) when you need the GUI; invoking Godot with `--path` alone runs the exported main scene without opening the editor.

### Editor / filesystem performance

- **`Experiments/.gdignore`**: Marks the bulk experiment-output tree as ignored by Godot (see [Ignoring specific folders](https://docs.godotengine.org/en/stable/tutorials/best_practices/project_organization.html#ignoring-specific-folders)). This repo’s `Experiments/` subtree can hold **40k+** small files from batch runs; scanning and importing them on every editor start makes the GUI appear frozen or “looping” on the splash screen. Ignored folders do not appear in the FileSystem dock but remain normal files for Python and shell tools.

### Autoload Singletons

**AppDebugLogger** (`scripts/core/DebugLogger.gd`):
- Configured in `project.godot` as autoload singleton **AppDebugLogger** (not `DebugLogger`: a node name matching `class_name DebugLogger` causes a parse error in Godot 4)
- Scripts obtain the node via `DebugLogger.get_instance()` → `/root/AppDebugLogger`
- Fixed-width table format unified with Python sim_logger; categorized logging with verbosity control

**WebSocketManager** (`scripts/core/WebSocketManager.gd`):
- Configured in `project.godot` as autoload singleton
- Accessible globally via `WebSocketManager`
- Manages WebSocket connection to Python server
- When `Engine.is_editor_hint()` is true, skips `_ready()` networking setup and does not poll the peer in `_physics_process()`, so the open editor does not maintain a useless client loop to `localhost:8765`

### Data Files

**Flight Plans**:
- `data/Regular_Lattice_Manhattan_200 FP_2DP_2Hrs_Ordered.csv` - Main flight plan data
- Format: 13 columns with flight plan details

**Terrain Data**:
- `data/Filtered_FAA_UAS_FacilityMap_Data_LGA.csv` - FAA UAS facility map data
- Format: CEILING (feet), LATITUDE, LONGITUDE
- Used by GridMapManager for terrain visualization

**Graph Data**:
- `scripts/Python/Route Gen Basic Shortest Path/regular_lattice_graph.pkl` - NetworkX graph pickle file
- Contains airspace graph with node positions and edge weights

**Python Timing Analysis Logs**:
- `logs/python_routes_received.csv` - Detailed waypoint timing exported by `WebSocketServer.py` via `sim_logger.py`
- `logs/python_routes_received.csv` lifecycle - reset on server startup to avoid cross-run carryover, then append mode during runtime (unless overridden by `SIM_ROUTES_RECEIVED_CSV`)
- `logs/uav_route_visualization.ipynb` - Route plotting notebook; can label each waypoint with `overfly_time_sim_s` from `python_routes_received.csv` for 3D/2D inspection (commonly kept as local analysis output)
- `logs/uav_route_visualization.ipynb` label readability - seeded random label jitter (and 2D text background boxes) reduces overlap when multiple drones share identical waypoint paths; current default spread is `xy=0.15`, `z=0.06` (3D), `2d=0.15`
- `logs/uav_route_visualization.ipynb` route-color matching - waypoint labels use each route line's color to improve visual association between text and path
- `logs/uav_route_visualization.ipynb` interactive visibility controls - Plotly legends toggle per-route visibility and `Labels ON/OFF` buttons control waypoint time-label traces in both 3D and 2D views

**Experiment artifacts & absolute paths**:
- Under `Experiments/`, generated `*_run_config.json`, CSV exports, and logs may embed absolute `run_dir`, `python_exe`, and `godot_exe` paths from the host that produced the run.
- After moving or renaming the project folder, those stored paths can be stale; new runs rewrite them. Historical files can be bulk-updated to the new root if you need old configs to stay self-consistent (otherwise treat them as read-only records).

### Version-control hygiene

- A root `.gitignore` defines the GitHub baseline for this repository.
- Source/runtime code and static inputs remain tracked by default (`scripts/`, `scenes/`, `docs/`, `data/`, `resources/`).
- Generated artifacts are intentionally ignored to keep history clean and repository size stable:
  - Godot/editor caches (`.godot/`, `.import/`, `*.import`)
  - Python local/runtime caches (`__pycache__/`, virtual env folders, notebook checkpoints)
  - Local IDE/session-only files (`.cursor/`, `terminal_*.txt`, `cursor_purpose_*.md`)
  - Runtime output under `logs/` (`*.csv`, `*.log`, `*.ipynb`)
  - Experiment run outputs under `Experiments/` (`tmp/`, `tensorboard/`, per-replication logs/CSVs/JSONs, and generated run folders such as `baseline_runs/`, `directed_graph_5_runs/`, `ga_runs/`)

---

**Last Updated**: 2026-03-30 - Updated GA Experiment 1 metrics schema to explicit best_individual/population and candidate/final artifact naming
**Documentation Version**: 1.8

