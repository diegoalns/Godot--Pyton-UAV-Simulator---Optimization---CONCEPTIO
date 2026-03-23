class_name Drone
extends Area3D

# Geographic coordinate conversion constants - must match FlightPlanManager and GridMapManager
# These define the reference point for converting lat/lon to world coordinates (meters)
const ORIGIN_LAT = 40.55417343  # Reference latitude in decimal degrees (float)
const ORIGIN_LON = -73.99583928  # Reference longitude in decimal degrees (float)

# Route request timeout behavior control
const CANCEL_ON_TIMEOUT: bool = true  # If true, cancel flight on timeout; if false, use default route (bool)

# Core identification and position
var drone_id: String
var current_position: Vector3
var completed: bool = false

# Model type - matches CSV data
var model: String = ""

# Performance attributes - vary by model (simplified for holonomic movement)
var max_speed: float = 0.0          # Maximum velocity in m/s
var current_speed: float = 0.0      # Current velocity in m/s
var payload_capacity: float = 0.0   # Maximum payload in kg

# Runtime state
var distance_traveled: float = 0.0  # Total distance traveled in meters
var flight_time: float = 0.0        # Total flight time in seconds
var first_waypoint_time: float = -1.0  # Simulation time when first waypoint should be reached (float, seconds) - set to -1.0 if not yet determined

# Route and waypoint system
var route: Array = []               # Array of waypoint dictionaries
var current_waypoint_index: int = 0 # Index of current target waypoint
var returning: bool = false         # Whether drone is on return journey (deprecated - kept for compatibility)
var origin_position: Vector3        # Starting position for return journey
var destination_position: Vector3   # Final destination position
var waypoint_wait_timer: float = 0.0  # Timer for waiting at waypoint (float, seconds) - used for destination wait
var is_waiting_at_waypoint: bool = false  # Flag indicating if drone is waiting at current waypoint (bool)

# Graph node IDs for Python path planning - String type with format like "L0_X0_Y0"
# These provide direct O(1) lookup in the graph instead of expensive O(n) coordinate matching
var origin_node_id: String = ""     # Origin graph node ID (e.g., "L0_X0_Y0")
var dest_node_id: String = ""       # Destination graph node ID (e.g., "L0_X6_Y2")

# Movement state (holonomic - no physics constraints)
var target_position: Vector3        # Current target position
var target_speed: float = 0.0       # Target speed for current segment

# Response waiting state
var waiting_for_route_response: bool = false
var route_response_timer: Timer
# Hybrid timing: Track both simulation time and system clock time for accurate communication metrics
var route_request_sent_time: float = 0.0  # Simulation time when route request was sent (float, seconds)
var route_response_received_time: float = 0.0  # Simulation time when route response was received (float, seconds)
var route_request_sent_system_clock_time: float = 0.0  # System clock time when route request was sent (float, seconds since Unix epoch - matches Python time.time())
var route_response_received_system_clock_time: float = 0.0  # System clock time when route response was received (float, seconds since Unix epoch - matches Python time.time())

# Collision detection system - now using Area3D with signals
var collision_radius: float = 5.0  # Collision detection radius in meters (10m diameter when combined with another drone)
var is_colliding: bool = false      # Boolean flag indicating if drone is currently in collision state
var collision_partners: Array = []  # Array of drone IDs currently in collision with this drone
var collision_shape: CollisionShape3D = null  # Reference to collision shape for Area3D
var logger_instance: Node = null

func _get_logger() -> Node:
	if logger_instance == null:
		logger_instance = DebugLogger.get_instance()
	return logger_instance

func _log_info(event: String, data: Dictionary = {}):
	var logger = _get_logger()
	if logger:
		logger.log_event_info(DebugLogger.Category.DRONE, event, data)
	else:
		DebugLogger.print_table_row_fallback("INFO", "DRONE", event, data)

func _log_warning(event: String, data: Dictionary = {}):
	var logger = _get_logger()
	if logger:
		logger.log_event_warning(DebugLogger.Category.DRONE, event, data)
	else:
		DebugLogger.print_table_row_fallback("WARNING", "DRONE", event, data)

func _log_error(event: String, data: Dictionary = {}):
	var logger = _get_logger()
	if logger:
		logger.log_event_error(DebugLogger.Category.DRONE, event, data)
	else:
		DebugLogger.print_table_row_fallback("ERROR", "DRONE", event, data)


func initialize(id: String, start: Vector3, end: Vector3, drone_model: String, start_node_id: String = "", end_node_id: String = "", precomputed_route: Array = []):
	"""
	Initialize drone with position, destination and model-specific attributes
	
	Args:
		id: String - Unique identifier for the drone (e.g., "FP000001")
		start: Vector3 - Starting position in 3D space (Godot world coordinates)
		end: Vector3 - Destination position in 3D space (Godot world coordinates)
		drone_model: String - Type of drone (Long Range FWVTOL, Light Quadcopter, Heavy Quadcopter)
		start_node_id: String - Origin graph node ID for path planning (e.g., "L0_X0_Y0")
		end_node_id: String - Destination graph node ID for path planning (e.g., "L0_X6_Y2")
		precomputed_route: Array - Optional precomputed route waypoints from Python (empty array if not provided)
	"""
	drone_id = id
	current_position = start
	origin_position = start
	# CRITICAL: Immediately sync Area3D global_position with logical position
	# This prevents false collisions at origin (0,0,0) before first update() call
	global_position = current_position
	destination_position = end
	model = drone_model
	
	# Store graph node IDs for efficient Python path planning
	origin_node_id = start_node_id
	dest_node_id = end_node_id
	
	# Set model-specific attributes
	_set_model_attributes()
	
	# Initialize runtime state
	distance_traveled = 0.0
	flight_time = 0.0
	current_speed = 0.0
	returning = false
	current_waypoint_index = 0
	first_waypoint_time = -1.0  # Will be set when route request is sent or route is received (float, seconds)
	
	# Set up collision detection using Area3D
	_setup_collision_detection()
	
	# Set up response timeout timer (only needed if requesting route via WebSocket)
	route_response_timer = Timer.new()
	route_response_timer.one_shot = true
	route_response_timer.wait_time = 90.0  # 90 second timeout - Timer configured to wait 90 seconds before timing out
	route_response_timer.timeout.connect(_on_route_response_timeout)
	add_child(route_response_timer)
	
	# Check if precomputed route is provided
	if precomputed_route != null and precomputed_route.size() > 0:
		# Use precomputed route - skip WebSocket request
		_log_info("precomputed_route_loaded", {
			"drone_id": drone_id,
			"waypoint_count": precomputed_route.size(),
			"websocket_request_skipped": true
		})
		
		# Store simulation time as first waypoint time (this is when the route starts)
		first_waypoint_time = SimulationEngine.current_simulation_time  # float: Simulation time when route starts (seconds)
		
		# Process the precomputed route (convert from Python format to Godot format)
		_process_server_route(precomputed_route)
		
		# Finalize route setup immediately (drone ready to fly)
		_finalize_route_setup()
		
		# Don't wait for route response - already have it
		waiting_for_route_response = false
	else:
		# No precomputed route - request route via WebSocket (existing behavior)
		# Create a dictionary with the data to include in the message
		# Using Node IDs for efficient O(1) graph lookup instead of O(n) coordinate matching
		var message_data = {
			"type": "request_route",
			"drone_id": drone_id,
			"model": model,
			# PRIMARY: Graph node IDs for fast path planning (String type - direct hash lookup)
			"start_node_id": origin_node_id,     # e.g., "L0_X0_Y0" - Origin graph node
			"end_node_id": dest_node_id,         # e.g., "L0_X6_Y2" - Destination graph node
			# FALLBACK: Coordinate positions if node IDs are not available (float type)
			"start_position": {
				"lon": start.x,  # Godot X (East/West) → Python longitude
				"lat": start.z,  # Godot Z (North/South) → Python latitude  
				"alt": start.y   # Godot Y (Up/Down) → Python altitude
			},
			"end_position": {
				"lon": end.x,    # Godot X (East/West) → Python longitude
				"lat": end.z,    # Godot Z (North/South) → Python latitude
				"alt": end.y     # Godot Y (Up/Down) → Python altitude
			},
			# Drone performance parameters for route optimization (speed-focused only)
			"max_speed": max_speed,                          # float: Maximum velocity in m/s
			# Registry synchronization: Send current simulation time for registry cleanup
			"simulation_time": SimulationEngine.current_simulation_time  # float: Current simulation time in seconds
		}

		# Hybrid timing: Record both simulation time and system clock time when route request is sent (BEFORE creating message)
		route_request_sent_time = SimulationEngine.current_simulation_time  # float: Simulation time in seconds (for simulation logic)
		route_request_sent_system_clock_time = Time.get_unix_time_from_system()  # float: System clock time in seconds since Unix epoch (matches Python time.time())
		
		# Store simulation time as first waypoint time (this is the start_time used by Python for calculating overfly times)
		first_waypoint_time = SimulationEngine.current_simulation_time  # float: Simulation time when first waypoint should be reached (seconds)
		
		# Include send timestamp in message for network latency calculation on Python side
		message_data["client_request_sent_time"] = route_request_sent_system_clock_time  # float: System clock time when Godot sent the request (for network latency calculation)

		# Convert the dictionary to a JSON string
		var message = JSON.stringify(message_data)

		# Connect to response signal before sending
		if not WebSocketManager.data_received.is_connected(_on_route_response_received):
			WebSocketManager.data_received.connect(_on_route_response_received)

		_log_info("route_request_sent", {
			"drone_id": drone_id,
			"simulation_time": route_request_sent_time,
			"system_clock_time": route_request_sent_system_clock_time
		})

		# Send the JSON-formatted message
		WebSocketManager.send_message(message)
		
		# Start waiting for response with timeout
		waiting_for_route_response = true
		route_response_timer.start()
	
	# Set initial target if route already exists
	if route.size() > 0:
		_set_current_target()

func _setup_collision_detection():
	"""
	Set up Area3D collision detection system
	
	Creates a spherical collision shape and connects to collision signals
	"""
	# Create collision shape - SphereShape3D for 360-degree detection
	collision_shape = CollisionShape3D.new()
	var sphere_shape = SphereShape3D.new()
	sphere_shape.radius = collision_radius  # 15.0 meters radius
	collision_shape.shape = sphere_shape
	add_child(collision_shape)
	
	# Connect to Area3D collision signals for automatic detection
	area_entered.connect(_on_area_entered)
	area_exited.connect(_on_area_exited)

func _set_model_attributes():
	"""
	Set performance attributes based on drone model
	
	References used for realistic values:
	- DJI M300 RTK (Heavy Quadcopter): 15m/s max speed, 55min flight time, 2.7kg payload
	- DJI Mini 3 Pro (Light Quadcopter): 16m/s max speed, 34min flight time, 0.249kg weight
	- Boeing MQ-25 Stingray (FWVTOL): 185 km/h (51.4 m/s), long range capabilities
	- NASA UAM studies for urban air mobility
	- FAA Part 107 regulations for commercial drones
	"""
	match model:
		"Long Range FWVTOL":
			# Fixed-wing VTOL optimized for speed performance
			max_speed = 55.0              # m/s (~200 km/h) - high cruise speed
			payload_capacity = 5.0        # kg - substantial cargo capacity
			
		"Light Quadcopter":
			# Small, agile quadcopter for speed performance
			max_speed = 18.0              # m/s (~65 km/h) - moderate speed
			payload_capacity = 0.5        # kg - minimal payload
			
		"Heavy Quadcopter":
			# Industrial quadcopter optimized for speed performance
			max_speed = 25.0              # m/s (~90 km/h) - good speed despite weight
			payload_capacity = 8.0        # kg - excellent payload capacity
			
		_:
			# Default to Long Range FWVTOL if unknown model
			push_warning("Unknown drone model '%s', using Long Range FWVTOL defaults" % model)
			model = "Long Range FWVTOL"
			_set_model_attributes()

func _create_default_route(start: Vector3, end: Vector3):
	"""
	Create a default route with waypoints between start and destination
	
	Includes altitude variations and speed adjustments for realistic flight path
	
	Args:
		start: Starting position
		end: Destination position
	"""
	route.clear()
	
	# Calculate route parameters
	var total_distance = start.distance_to(end)
	var _direction = (end - start).normalized()  # Prefix with underscore to indicate intentionally unused
	
	# Determine cruise altitude based on drone model and distance
	var cruise_altitude = _get_cruise_altitude_for_model()
	
	# Create waypoint sequence
	# 1. Takeoff waypoint - climb to cruise altitude
	var takeoff_pos = Vector3(start.x, cruise_altitude, start.z)
	route.append({
		"position": takeoff_pos,
		"altitude": cruise_altitude,
		"speed": max_speed * 0.6,  # Slower speed for takeoff
		"description": "Takeoff and climb"
	})
	
	# 2. Cruise waypoints - add intermediate points for longer flights
	if total_distance > 5000:  # Add waypoints for flights over 5km
		var num_waypoints = int(total_distance / 10000) + 1  # One waypoint per 10km
		for i in range(1, num_waypoints):
			var progress = float(i) / float(num_waypoints)
			var waypoint_pos = start.lerp(end, progress)
			waypoint_pos.y = cruise_altitude
			
			route.append({
				"position": waypoint_pos,
				"altitude": cruise_altitude,
				"speed": max_speed,  # Full cruise speed
				"description": "Cruise waypoint %d" % i
			})
	
	# 3. Approach waypoint - maintain altitude but reduce speed
	var approach_pos = Vector3(end.x, cruise_altitude, end.z)
	route.append({
		"position": approach_pos,
		"altitude": cruise_altitude,
		"speed": max_speed * 0.7,  # Reduced speed for approach
		"description": "Approach"
	})
	
	# 4. Landing waypoint - descend to destination
	route.append({
		"position": end,
		"altitude": end.y,
		"speed": max_speed * 0.4,  # Slow speed for landing
		"description": "Landing"
	})
	
	_log_info("default_route_created", {
		"drone_id": drone_id,
		"waypoint_count": route.size()
	})

func _get_cruise_altitude_for_model() -> float:
	"""
	Get appropriate cruise altitude based on drone model
	
	Returns:
		float: Cruise altitude in meters
	"""
	match model:
		"Long Range FWVTOL":
			return 50.0    # High altitude for efficiency
		"Light Quadcopter":
			return 50.0    # Lower altitude for regulations
		"Heavy Quadcopter":
			return 50.0    # Medium altitude for cargo operations
		_:
			return 50.0    # Default altitude

func _set_current_target():
	"""
	Set the current target position and speed based on current waypoint.
	Now handles complete round trip routes planned by the shortest-path service (origin → destination → origin).
	"""
	if current_waypoint_index < route.size():
		# More waypoints available - set next target
		var waypoint = route[current_waypoint_index]  # Current waypoint dictionary (dict)
		
		# Safety check: ensure waypoint has required fields
		if not waypoint.has("position") or not waypoint.has("speed"):
			push_warning("Drone %s: Waypoint %d missing required fields (position or speed)" % [drone_id, current_waypoint_index])
			completed = true  # Mark as completed to prevent further errors
			return
		
		target_position = waypoint.position  # Target position (Vector3)
		target_speed = min(waypoint.speed, max_speed)  # Respect model max speed (float, m/s)
	else:
		# Completed all waypoints - route is complete (planned complete round trip)
		completed = true
		_log_info("mission_completed_round_trip", {"drone_id": drone_id})
		
		# Notify Python server that drone has completed its route for registry cleanup
		_send_completion_message()

func update(delta: float):
	"""
	Update drone state with holonomic movement along waypoint route
	
	Args:
		delta: Time step in seconds since last update
	"""
	if completed or waiting_for_route_response:
		return
	
	# Update flight time
	flight_time += delta
	
	# Update waypoint wait timer if waiting
	if is_waiting_at_waypoint:
		waypoint_wait_timer += delta  # Increment wait timer (float, seconds)
		
		# Check if wait time has elapsed (check every frame, not just when at waypoint)
		if current_waypoint_index < route.size():
			var waypoint = route[current_waypoint_index]  # Current waypoint (dict)
			var waypoint_desc = waypoint.get("description", "")  # Waypoint description (str)
			
			# Extract wait duration from waypoint description
			var wait_duration = 60.0  # Default wait duration (float, seconds)
			if "Wait" in waypoint_desc:
				# Parse wait duration from description (e.g., "Wait 60s")
				var desc_parts = waypoint_desc.split("Wait")  # Split description at "Wait" (Array)
				if desc_parts.size() > 1:
					var wait_part = desc_parts[1]  # Part after "Wait" (str)
					var wait_str = wait_part.split("s")[0].strip_edges()  # Extract number before 's' and remove whitespace (str)
					if wait_str.is_valid_float():
						wait_duration = float(wait_str)  # Parse wait duration (float, seconds)
			
			# Check if wait time has elapsed
			if waypoint_wait_timer >= wait_duration:
				# Wait completed - advance to next waypoint
				is_waiting_at_waypoint = false  # Clear waiting flag (bool)
				waypoint_wait_timer = 0.0  # Reset wait timer (float, seconds)
				_log_info("waypoint_wait_completed", {
					"drone_id": drone_id,
					"waypoint_index": current_waypoint_index
				})
				current_waypoint_index += 1  # Advance to next waypoint (int)
				
				# Safety check: ensure we don't go beyond route bounds
				if current_waypoint_index < route.size():
					_set_current_target()  # Set new target
				else:
					# No more waypoints - route complete
					completed = true
					_log_info("mission_completed_round_trip", {"drone_id": drone_id})
					_send_completion_message()
		
		# Don't move while waiting - speed is already set to 0
	else:
		# Holonomic movement - direct movement toward target without physics constraints
		_update_holonomic_movement(delta)
	
	# Check if we've reached current waypoint (only if not waiting)
	if not is_waiting_at_waypoint:
		_check_waypoint_reached()
	
	# Synchronize Area3D position with logical drone position for collision detection
	global_position = current_position

func _update_holonomic_movement(delta: float):
	"""
	Update position using direct holonomic movement (no physics constraints)
	
	Args:
		delta: Time step in seconds
	"""
	if current_waypoint_index >= route.size():
		return
	
	# Calculate movement toward target
	var direction_to_target = (target_position - current_position).normalized()
	var distance_to_target = current_position.distance_to(target_position)
	
	# Calculate movement distance this frame
	var movement_distance = target_speed * delta
	
	# Clamp movement to not overshoot target
	if movement_distance >= distance_to_target:
		# Reach target exactly
		current_position = target_position
		current_speed = 0.0
	else:
		# Move toward target
		current_position += direction_to_target * movement_distance
		current_speed = target_speed
	
	# Update distance traveled
	distance_traveled += movement_distance

func _check_waypoint_reached():
	"""
	Check if current waypoint has been reached and advance to next waypoint.
	Handles wait periods at waypoints (e.g., 60s wait at destination).
	Note: Wait completion is handled in update() function to check every frame.
	"""
	var distance_to_target = current_position.distance_to(target_position)
	var arrival_threshold = 5.0  # 5 meter arrival threshold (float, meters)
	
	if distance_to_target < arrival_threshold:
		# Reached current waypoint
		var waypoint = route[current_waypoint_index]  # Waypoint data dictionary (dict)
		var waypoint_desc = waypoint.get("description", "")  # Waypoint description (str)
		
		# Check if this waypoint requires waiting (destination wait)
		if "Wait" in waypoint_desc and not is_waiting_at_waypoint:
			# Start waiting at this waypoint
			is_waiting_at_waypoint = true  # Set waiting flag (bool)
			waypoint_wait_timer = 0.0  # Reset wait timer (float, seconds)
			current_speed = 0.0  # Stop movement during wait (float, m/s)
			_log_info("waypoint_wait_started", {
				"drone_id": drone_id,
				"waypoint_index": current_waypoint_index,
				"waypoint_description": waypoint_desc
			})
			return  # Don't advance waypoint yet - wait first (wait completion handled in update())
		elif not is_waiting_at_waypoint:
			# Normal waypoint without wait - advance immediately
			current_waypoint_index += 1  # Advance to next waypoint (int)
			_set_current_target()  # Set new target


# Area3D collision signal handlers - automatic collision detection
func _on_area_entered(other_area: Area3D):
	"""
	Handle when another Area3D (drone) enters this drone's collision radius
	
	Args:
		other_area: The Area3D that entered our collision space
	"""
	# Verify the other area is a drone and not this drone itself
	if other_area is Drone and other_area != self:
		var other_drone = other_area as Drone
		
		# Skip completed drones as they're not actively flying
		if other_drone.completed:
			return
		
		# Add to collision partners if not already present
		if not collision_partners.has(other_drone.drone_id):
			collision_partners.append(other_drone.drone_id)
			
			# Calculate actual distance and threshold for CSV logging
			var distance = current_position.distance_to(other_drone.current_position)
			var threshold = collision_radius + other_drone.collision_radius
			_log_collision_event("COLLISION_START", other_drone, distance, threshold)
			
			# Create persistent collision marker at midpoint between drones
			# Only create marker if this drone's ID is lexicographically smaller (prevents duplicates)
			if drone_id < other_drone.drone_id:
				var collision_midpoint = (current_position + other_drone.current_position) / 2.0
				var sim_time = SimulationEngine.current_simulation_time
				if DroneManager.visualization_system_ref:
					DroneManager.visualization_system_ref.add_collision_marker(collision_midpoint, drone_id, other_drone.drone_id, distance, sim_time)
		
		# Update collision state
		var previous_collision_state = is_colliding
		is_colliding = true
		
		# Handle state change if needed
		if not previous_collision_state:
			_handle_collision_state_change(false, true)

func _on_area_exited(other_area: Area3D):
	"""
	Handle when another Area3D (drone) exits this drone's collision radius
	
	Args:
		other_area: The Area3D that exited our collision space
	"""
	# Verify the other area is a drone
	if other_area is Drone and other_area != self:
		var other_drone = other_area as Drone
		
		# Remove from collision partners
		var partner_index = collision_partners.find(other_drone.drone_id)
		if partner_index >= 0:
			collision_partners.remove_at(partner_index)
			
			# Log collision end event to CSV
			var distance = current_position.distance_to(other_drone.current_position)
			var threshold = collision_radius + other_drone.collision_radius
			_log_collision_event("COLLISION_END", other_drone, distance, threshold)
		
		# Update collision state
		var previous_collision_state = is_colliding
		is_colliding = collision_partners.size() > 0
		
		# Handle state change if we're no longer colliding with anyone
		if previous_collision_state and not is_colliding:
			_handle_collision_state_change(true, false)

func _log_collision_event(event_type: String, other_drone: Drone, distance: float, threshold: float):
	"""
	Log a collision event to the CSV file via the SimpleLogger singleton
	
	Args:
		event_type: Type of collision event ("COLLISION_START" or "COLLISION_END")
		other_drone: The Drone object this drone is colliding with
		distance: The actual distance between the two drone centers in meters
		threshold: The collision detection threshold distance in meters
	"""
	# Only log collision if this drone's ID is lexicographically smaller than the other drone's ID
	# This prevents duplicate logging (A->B and B->A) by ensuring only one drone logs each collision pair
	if drone_id < other_drone.drone_id:
		# Use SimpleLogger singleton to log collision event to CSV
		if SimpleLogger.instance:
			var sim_time = SimulationEngine.current_simulation_time
			SimpleLogger.instance.log_collision_event(sim_time, event_type, self, other_drone, distance, threshold)

func _handle_collision_state_change(_previous_state: bool, _new_state: bool):
	"""
	Handle transitions between collision and non-collision states
	
	Args:
		_previous_state: Previous collision state (bool) - unused, kept for interface compatibility
		_new_state: New collision state (bool) - unused, kept for interface compatibility
	"""
	# Collision state changes are now only logged to CSV via collision events
	# No console output needed - all data is captured in the CSV log
	pass

func _execute_collision_response(_other_drone: Drone):
	"""
	Execute collision avoidance response behavior
	
	Args:
		_other_drone: The drone we're colliding with (prefixed with underscore as currently unused)
	"""
	# No collision response behavior - only detection and logging
	# This function is kept for future extensibility if collision response is needed
	pass

# Note: collision_manager_reference no longer needed with Area3D collision system
# Collision detection now happens automatically through Godot's physics engine

func get_collision_info() -> Dictionary:
	"""
	Get current collision status information
	
	Returns:
		Dictionary containing collision state, partners, and radius
	"""
	return {
		"is_colliding": is_colliding,
		"collision_partners": collision_partners.duplicate(),  # Return copy to prevent external modification
		"collision_radius": collision_radius,
		"collision_partner_count": collision_partners.size()
	}

# Getter functions for accessing drone state

func get_current_waypoint_info() -> Dictionary:
	"""Returns information about current waypoint target"""
	if current_waypoint_index < route.size():
		var waypoint = route[current_waypoint_index]
		return {
			"index": current_waypoint_index,
			"total_waypoints": route.size(),
			"description": waypoint.description,
			"target_position": waypoint.position,
			"target_speed": waypoint.speed,
			"distance_to_waypoint": current_position.distance_to(waypoint.position),
			"returning": returning
		}
	else:
		return {"completed": true}

func get_route_info() -> Dictionary:
	"""Returns complete route information"""
	return {
		"total_waypoints": route.size(),
		"current_waypoint": current_waypoint_index,
		"returning": returning,
		"route_waypoints": route
	}

func _on_route_response_received(data):
	"""
	Handle response from WebSocket server for route requests
	
	Args:
		data: PackedByteArray containing the server response
	"""
	var response_text = data.get_string_from_utf8()
	
	# Parse JSON response
	var json = JSON.new()
	var parse_result = json.parse(response_text)
	
	if parse_result != OK:
		# Failed to parse JSON response - cancel flight
		_log_error("route_request_failed_invalid_json_response", {
			"drone_id": drone_id,
			"reason": "failed_to_parse_json_response",
			"action": "flight_cancelled"
		})
		# Stop the timeout timer
		if route_response_timer and not route_response_timer.is_stopped():
			route_response_timer.stop()
		# Disconnect from signal
		if WebSocketManager.data_received.is_connected(_on_route_response_received):
			WebSocketManager.data_received.disconnect(_on_route_response_received)
		waiting_for_route_response = false
		completed = true  # Mark drone as completed (cancelled)
		return
	
	var response_data = json.data
	
	# Check if this response is for our drone
	if response_data.has("drone_id") and response_data.drone_id == drone_id:
		# Hybrid timing: Record both simulation time and system clock time when route response is received
		route_response_received_time = SimulationEngine.current_simulation_time  # float: Simulation time in seconds (for simulation logic)
		route_response_received_system_clock_time = Time.get_unix_time_from_system()  # float: System clock time in seconds since Unix epoch (matches Python time.time())
		
		# Calculate delays using both time references
		var sim_delay = route_response_received_time - route_request_sent_time  # float: Simulation time delay in seconds (affected by pause/speed)
		var system_clock_delay_sec = route_response_received_system_clock_time - route_request_sent_system_clock_time  # float: Actual network/processing delay in seconds (system clock time)
		
		# Extract server-side timestamps if available (for end-to-end correlation)
		var server_request_received_time = response_data.get("server_request_received_time", 0.0)  # float: System clock time when server received request (seconds)
		var server_response_sent_time = response_data.get("server_response_sent_time", 0.0)  # float: System clock time when server sent response (seconds)
		var pathfinding_duration = response_data.get("pathfinding_duration", 0.0)  # float: Pathfinding processing time in seconds
		
		_log_info("route_response_received", {
			"drone_id": drone_id,
			"simulation_time_received": route_response_received_time,
			"simulation_delay": sim_delay,
			"request_sent_system_clock_time": route_request_sent_system_clock_time,
			"response_received_system_clock_time": route_response_received_system_clock_time,
			"round_trip_time_seconds": system_clock_delay_sec,
			"round_trip_time_ms": system_clock_delay_sec * 1000.0
		})
		if server_request_received_time > 0.0 and server_response_sent_time > 0.0:
			var server_processing_time = server_response_sent_time - server_request_received_time  # float: Total server processing time in seconds
			_log_info("route_response_server_timing", {
				"drone_id": drone_id,
				"server_request_received_time": server_request_received_time,
				"server_response_sent_time": server_response_sent_time,
				"server_processing_time": server_processing_time,
				"pathfinding_duration": pathfinding_duration
			})
		
		# Stop the timeout timer
		if route_response_timer and not route_response_timer.is_stopped():
			route_response_timer.stop()
		
		# Disconnect from signal to avoid receiving other drones' responses
		if WebSocketManager.data_received.is_connected(_on_route_response_received):
			WebSocketManager.data_received.disconnect(_on_route_response_received)
		
		# Check for failure statuses - cancel flight for any failure
		if response_data.has("status"):
			var status = response_data.status  # String: Response status
			var status_message = response_data.get("message", "Unknown error")  # String: Error message from server
			
			if status == "timeout":
				# Pathfinding timed out - no route found within 3 seconds
				_log_error("pathfinding_failed_timeout", {
					"drone_id": drone_id,
					"server_message": status_message,
					"action": "flight_cancelled"
				})
				waiting_for_route_response = false
				completed = true  # Mark drone as completed (cancelled)
				return
			elif status == "no_path":
				# No conflict-free path found
				_log_error("pathfinding_failed_no_conflict_free_path", {
					"drone_id": drone_id,
					"server_message": status_message,
					"action": "flight_cancelled"
				})
				waiting_for_route_response = false
				completed = true  # Mark drone as completed (cancelled)
				return
			elif status == "error":
				# Pathfinding error occurred
				_log_error("pathfinding_failed_error", {
					"drone_id": drone_id,
					"server_message": status_message,
					"action": "flight_cancelled"
				})
				waiting_for_route_response = false
				completed = true  # Mark drone as completed (cancelled)
				return
		
		# Check if a valid route was provided
		if response_data.has("route") and response_data.route is Array:
			# Use server-provided route
			_process_server_route(response_data.route)
			_finalize_route_setup()
		else:
			# No route provided and status is not a recognized failure - cancel flight
			var status_message = response_data.get("message", "No route provided in response")
			_log_error("route_request_failed_no_valid_route", {
				"drone_id": drone_id,
				"reason": status_message,
				"action": "flight_cancelled"
			})
			waiting_for_route_response = false
			completed = true  # Mark drone as completed (cancelled)

func _latlon_to_position(lat: float, lon: float, altitude: float) -> Vector3:
	"""
	Convert latitude/longitude/altitude to world position in meters
	Uses the same conversion method as FlightPlanManager and GridMapManager for consistency
	
	Args:
		lat: float - Latitude in decimal degrees
		lon: float - Longitude in decimal degrees
		altitude: float - Altitude in meters
	
	Returns:
		Vector3 - World position with X (longitude), Y (altitude), Z (latitude) in meters
	"""
	# Conversion constants: approximate meters per degree at this latitude
	var meters_per_deg_lat = 111320.0  # Meters per degree latitude (approximately constant globally)
	var meters_per_deg_lon = 111320.0 * cos(deg_to_rad(ORIGIN_LAT))  # Meters per degree longitude (varies by latitude)
	
	# Calculate world position relative to origin point
	var x = (lon - ORIGIN_LON) * meters_per_deg_lon  # X position in meters (East/West)
	# Invert Z calculation: higher latitude (north) → negative Z (north in Godot), lower latitude (south) → positive Z (south in Godot)
	var z = (ORIGIN_LAT - lat) * meters_per_deg_lat  # Z position in meters (North/South)
	
	# Return Vector3 with altitude as Y coordinate
	return Vector3(x, altitude, z)

func _process_server_route(server_route: Array):
	"""
	Process route data received from server
	Server now sends geographic coordinates (lat/lon/altitude) which we convert to world position
	
	Args:
		server_route: Array of waypoint dictionaries from server, each containing:
					  - lat: float (latitude in decimal degrees)
					  - lon: float (longitude in decimal degrees)
					  - altitude: float (altitude in meters)
					  - speed: float (waypoint speed in m/s)
					  - description: string (waypoint label)
	"""
	route.clear()  # Clear existing route array before populating with new waypoints
	
	# Process each waypoint from the server response
	for waypoint_data in server_route:
		if waypoint_data is Dictionary:
			# Extract geographic coordinates from server response
			var lat = waypoint_data.get("lat", 0.0)        # Latitude in decimal degrees (float)
			var lon = waypoint_data.get("lon", 0.0)        # Longitude in decimal degrees (float)
			var altitude = waypoint_data.get("altitude", 10.0)  # Altitude in meters (float)
			
			# Convert geographic coordinates to world position using the same method as other managers
			var world_pos = _latlon_to_position(lat, lon, altitude)  # Returns Vector3 in meters
			
			# Create waypoint dictionary with converted world position
			var waypoint = {
				"position": world_pos,  # Vector3 - world position in meters (X, Y, Z)
				"altitude": altitude,   # float - altitude in meters (duplicate of world_pos.y)
				"speed": waypoint_data.get("speed", max_speed * 0.8),  # float - waypoint speed in m/s
				"description": waypoint_data.get("description", "Server waypoint")  # string - waypoint label
			}
			route.append(waypoint)  # Add waypoint to route array
	
	var route_data: Dictionary = {
		"drone_id": drone_id,
		"waypoint_count": route.size()
	}
	if route.size() > 0:
		route_data["first_waypoint"] = route[0].get("description", "Unknown")
		route_data["last_waypoint"] = route[route.size() - 1].get("description", "Unknown")
	_log_info("route_processed", route_data)

func _send_completion_message():
	"""
	Send completion message to Python server to update drone registry.
	Notifies server that this drone has finished its route.
	"""
	# Create completion message dictionary
	var completion_data = {
		"type": "drone_completed",
		"drone_id": drone_id,  # String: Unique drone identifier
		"simulation_time": SimulationEngine.current_simulation_time  # float: Current simulation time in seconds
	}
	
	# Convert to JSON and send via WebSocket
	var message = JSON.stringify(completion_data)  # String: JSON-formatted message
	WebSocketManager.send_message(message)

func _finalize_route_setup():
	"""
	Complete the route setup after receiving response (or timeout)
	"""
	waiting_for_route_response = false
	
	# Set initial target if we have waypoints
	if route.size() > 0:
		_set_current_target()
		# Route finalized successfully - silent operation
	else:
		push_warning("Drone %s has no valid route!" % drone_id)
		completed = true

func _on_route_response_timeout():
	"""
	Handle timeout when no response is received from server
	Always cancels flight - no default route fallback
	"""
	# Hybrid timing: Record both simulation time and system clock time when timeout occurs
	var timeout_time = SimulationEngine.current_simulation_time  # float: Simulation time when timeout occurred (seconds)
	var timeout_system_clock_time = Time.get_unix_time_from_system()  # float: System clock time when timeout occurred (seconds since Unix epoch)
	var sim_timeout_duration = timeout_time - route_request_sent_time  # float: Simulation time elapsed since request was sent (seconds)
	var system_clock_timeout_duration_sec = timeout_system_clock_time - route_request_sent_system_clock_time  # float: Actual system clock time elapsed since request was sent (seconds)
	
	_log_warning("route_response_timeout", {
		"drone_id": drone_id,
		"timeout_simulation_time": timeout_time,
		"simulation_wait_duration": sim_timeout_duration,
		"timeout_system_clock_time": timeout_system_clock_time,
		"actual_wait_duration_seconds": system_clock_timeout_duration_sec
	})
	
	# Disconnect from signal to avoid processing late responses
	if WebSocketManager.data_received.is_connected(_on_route_response_received):
		WebSocketManager.data_received.disconnect(_on_route_response_received)
	
	# Cancel the flight - no route received within timeout period
	_log_error("flight_cancelled_route_timeout", {
		"drone_id": drone_id,
		"reason": "timeout_waiting_for_route_response"
	})
	waiting_for_route_response = false
	completed = true  # Mark drone as completed (cancelled)
