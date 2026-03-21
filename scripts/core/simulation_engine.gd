class_name SimulationEngine
extends Node

# Get DebugLogger singleton instance (autoload singleton)
# Access via: logger_instance instead of DebugLogger directly
var logger_instance: Node = null

@onready var drone_manager = DroneManager.new()
@onready var flight_plan_manager = FlightPlanManager.new()
@onready var visualization_system = VisualizationSystem.new()
@onready var logger = SimpleLogger.new()
@onready var route_pre_request_manager = RoutePreRequestManager.new()

var simulation_time: float = 0.0
# Static reference for global access to simulation time
static var current_simulation_time: float = 0.0
var running: bool = false
var speed_multiplier: float = 1.0
var time_step: float = 1.0
var real_runtime: float = 0.0
var headless_mode: bool = false
var ui: SimpleUI  # Store UI instance for access in _physics_process
var ga_autorun: bool = false
var ga_headless: bool = false
var ga_max_sim_time: float = -1.0
var ga_summary_json_path: String = "user://ga_run_summary.json"
var ga_finished: bool = false

func _ready():
	# Get DebugLogger singleton instance (autoload singleton)
	logger_instance = DebugLogger.get_instance()
	if logger_instance == null:
		push_error("AppDebugLogger autoload not found (scripts/core/DebugLogger.gd). Check project.godot autoloads.")
	
	add_child(visualization_system)
	add_child(drone_manager)
	add_child(flight_plan_manager)
	add_child(logger)
	add_child(route_pre_request_manager)

	# Connect systems
	drone_manager.set_visualization_system(visualization_system)
	
	# Load flight plans into queue
	flight_plan_manager.load_flight_plans()

	await get_tree().process_frame
	
	# Add drone ports to visualization
	var ports = flight_plan_manager.get_drone_ports()
	for port_id in ports.keys():
		var lat = ports[port_id]["lat"]
		var lon = ports[port_id]["lon"]
		var pos = flight_plan_manager.latlon_to_position(lat, lon)
		visualization_system.add_drone_port(pos, port_id)

	# Add UI
	var canvas_layer = CanvasLayer.new()
	ui = SimpleUI.new()
	canvas_layer.add_child(ui)
	add_child(canvas_layer)

	# Set drone ports in UI
	ui.set_drone_ports(ports.keys())

	# Connect UI signals
	ui.start_requested.connect(_on_start_requested)
	ui.pause_requested.connect(_on_pause_requested)
	ui.speed_changed.connect(_on_speed_changed)
	ui.headless_mode_changed.connect(_on_headless_mode_changed)
	ui.port_selected.connect(_on_port_selected)
	
	# Connect active drones panel to DroneManager
	ui.set_drone_manager(drone_manager)  # Pass DroneManager reference to UI for active drones display (void)

	# Batch automation mode for GA integration.
	ga_autorun = OS.get_environment("GA_AUTORUN") == "1"
	ga_headless = OS.get_environment("GA_HEADLESS") == "1"
	var ga_max_sim_time_str = OS.get_environment("GA_MAX_SIM_TIME")
	if ga_max_sim_time_str != "":
		ga_max_sim_time = float(ga_max_sim_time_str)
	var ga_summary_override = OS.get_environment("GA_SUMMARY_JSON")
	if ga_summary_override != "":
		ga_summary_json_path = ga_summary_override

	if ga_headless:
		headless_mode = true
		visualization_system.set_enabled(false)
	if ga_autorun:
		running = true

func _on_start_requested():
	running = true

func _on_pause_requested():
	running = false

func _on_speed_changed(multiplier: float):
	speed_multiplier = multiplier

func _on_headless_mode_changed(enabled: bool):
	headless_mode = enabled
	visualization_system.set_enabled(!enabled)
	
func _physics_process(delta: float):
	Engine.physics_ticks_per_second = 300  # Set to 300 physics FPS
	if not running:
		return
		
	# Simulation time and real runtime calculation - float type updated every physics frame
	simulation_time += time_step * speed_multiplier
	current_simulation_time = simulation_time  # Update static reference for global access
	real_runtime += delta
	
	# Phase 1: Route Pre-Requests (10 minutes before ETD)
	# Get all flight plans that need route requests sent (removes them from queue)
	var plans_needing_routes = flight_plan_manager.get_plans_needing_route_requests(simulation_time)
	
	# Send route requests for plans needing them
	for plan in plans_needing_routes:
		# Send route request via RoutePreRequestManager (plan removed from queue)
		route_pre_request_manager.send_route_request(plan)
	
	# Check for timed-out route requests
	route_pre_request_manager.check_timeouts(simulation_time)
	
	# Phase 2: Drone Creation from Heap (at ETD)
	# Check min-heap for routes ready at their ETD
	while not route_pre_request_manager.is_heap_empty():
		var earliest_route = route_pre_request_manager.peek_earliest_route()  # Dictionary: Route entry with earliest ETD
		
		# Check if this route's ETD has been reached
		if earliest_route.has("etd") and earliest_route.etd <= simulation_time:
			# ETD reached - pop route from heap and create drone
			var route_entry = route_pre_request_manager.pop_earliest_route()  # Dictionary: Route entry popped from heap
			var plan_data = route_entry.plan_data  # Dictionary: Full flight plan data
			
			# Convert latitude/longitude coordinates to Vector3 world positions
			var origin = flight_plan_manager.latlon_to_position(plan_data.origin_lat, plan_data.origin_lon)  # Vector3: Origin position
			var destination = flight_plan_manager.latlon_to_position(plan_data.dest_lat, plan_data.dest_lon)  # Vector3: Destination position
			
			# Print drone launch information
			var route_info = "%s → %s" % [plan_data.origin_node_id, plan_data.dest_node_id]  # String: Route node info
			if logger_instance:
				logger_instance.log_info(DebugLogger.Category.DRONE, "Launching %s with precomputed route (ETD: %.1fs) | Route: %s" % [plan_data.id, plan_data.etd_seconds, route_info], {"drone_id": plan_data.id, "etd": plan_data.etd_seconds, "route": route_info})
			
			# Create drone with precomputed route (route already received from Python)
			drone_manager.create_test_drone(
				plan_data.id,  # String: Flight plan ID
				origin,  # Vector3: Origin position
				destination,  # Vector3: Destination position
				plan_data.model,  # String: Drone model type
				plan_data.origin_node_id,  # String: Origin graph node ID
				plan_data.dest_node_id,  # String: Destination graph node ID
				route_entry.route  # Array: Precomputed route waypoints
			)
		else:
			# No more routes ready at current time
			break
	
	# Phase 3: Handle any remaining plans in queue (shouldn't happen, but fallback)
	# Queue-based drone launching - efficient O(k) where k = number of ready plans
	# Get all flight plans ready to launch at current simulation time
	# This function automatically removes processed plans from the queue
	var plans_to_launch = flight_plan_manager.get_next_pending_plans(simulation_time)
	
	# Launch each ready drone - Array of Dictionary objects
	for plan in plans_to_launch:
		# Convert latitude/longitude coordinates to Vector3 world positions
		var origin = flight_plan_manager.latlon_to_position(plan.origin_lat, plan.origin_lon)
		var destination = flight_plan_manager.latlon_to_position(plan.dest_lat, plan.dest_lon)
		
		# Log drone launch (fixed-width table format)
		var route_info = "%s → %s" % [plan.origin_node_id, plan.dest_node_id]
		if logger_instance:
			logger_instance.log_info(DebugLogger.Category.DRONE, "drone_launch", {"drone_id": plan.id, "model": plan.model, "etd": plan.etd_seconds, "route": route_info})
		
		# Create and initialize the drone with route request to Python server
		# Pass both Vector3 positions (for Godot) and Node IDs (for Python path planning)
		drone_manager.create_test_drone(plan.id, origin, destination, plan.model, plan.origin_node_id, plan.dest_node_id)
	
	# Update all created drones
	drone_manager.update_all(time_step * speed_multiplier)
	
	# Log data
	logger.update(time_step, simulation_time, drone_manager.drones)
	
	# Remove completed drones from memory
	drone_manager.remove_completed_drones()
	
	# Update time label in UI
	ui.update_time(simulation_time, real_runtime)

	# In GA batch mode, finish and quit when done or when max time is reached.
	if ga_autorun and not ga_finished:
		if ga_max_sim_time > 0.0 and simulation_time >= ga_max_sim_time:
			_finalize_ga_run_and_quit("max_sim_time_reached")
			return
		if _is_simulation_workload_drained():
			_finalize_ga_run_and_quit("workload_drained")
			return

	#if int(simulation_time) % 1 == 0 and simulation_time - delta < int(simulation_time):
	# print("Simulation time: %.5f seconds" % simulation_time)
	# print("Real runtime: %.5f seconds" % real_runtime)

func _on_port_selected(port_id: String):
	var ports = flight_plan_manager.get_drone_ports()
	if ports.has(port_id):
		var lat = ports[port_id]["lat"]
		var lon = ports[port_id]["lon"]
		var pos = flight_plan_manager.latlon_to_position(lat, lon)
		visualization_system.move_balloon_to_port(pos)

func get_terrain_altitude_at_position(world_pos: Vector3) -> float:
	"""
	Get terrain altitude at a specific world position
	@param world_pos: Vector3 - World position to query
	@return float - Altitude value at that position, or -1 if terrain not ready
	"""
	if visualization_system and visualization_system.is_terrain_ready():
		return visualization_system.get_terrain_altitude_at_position(world_pos)
	return -1.0

func get_terrain_info() -> Dictionary:
	"""
	Get terrain system information for debugging/display purposes
	@return Dictionary - Terrain information or empty dict if not ready
	"""
	if visualization_system and visualization_system.is_terrain_ready():
		return visualization_system.get_terrain_info()
	return {}

func _is_simulation_workload_drained() -> bool:
	# Consider the simulation drained when no queued plans, no pending/heap routes, and no active drones remain.
	var queue_stats = flight_plan_manager.get_queue_statistics()
	var remaining_queue = int(queue_stats.get("remaining", 0))
	var route_heap_size = route_pre_request_manager.successful_routes_heap.size()
	var route_pending_size = route_pre_request_manager.pending_route_requests.size()
	var active_drones = drone_manager.drones.size()
	return remaining_queue == 0 and route_heap_size == 0 and route_pending_size == 0 and active_drones == 0

func _finalize_ga_run_and_quit(stop_reason: String) -> void:
	ga_finished = true
	running = false

	var queue_stats = flight_plan_manager.get_queue_statistics()
	var heap_stats = route_pre_request_manager.get_heap_stats()
	var summary = {
		"stop_reason": stop_reason,
		"simulation_time": simulation_time,
		"real_runtime": real_runtime,
		"active_drones_remaining": drone_manager.drones.size(),
		"queue_remaining": int(queue_stats.get("remaining", 0)),
		"route_heap_size": int(heap_stats.get("heap_size", 0)),
		"route_pending_size": route_pre_request_manager.pending_route_requests.size(),
		"failed_pre_requests_count": int(heap_stats.get("failed_pre_requests_count", 0)),
		"failed_pre_requests_by_status": heap_stats.get("failed_pre_requests_by_status", {}),
		"ga_autorun": ga_autorun,
	}

	# Skip writing summary JSON in GA quiet mode to reduce I/O
	var ga_log_level = OS.get_environment("GA_LOG_LEVEL")
	if ga_log_level != "quiet":
		var abs_summary_path = ProjectSettings.globalize_path(ga_summary_json_path)
		var dir_path = abs_summary_path.get_base_dir()
		DirAccess.make_dir_recursive_absolute(dir_path)
		var file = FileAccess.open(abs_summary_path, FileAccess.WRITE)
		if file:
			file.store_string(JSON.stringify(summary))
			file.close()

	logger.close_log()
	get_tree().quit()
