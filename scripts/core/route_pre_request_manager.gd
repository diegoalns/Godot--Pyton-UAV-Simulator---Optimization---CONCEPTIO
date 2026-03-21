class_name RoutePreRequestManager
extends Node

# Min-heap for storing successful routes ordered by ETD (earliest first)
# MEMORY-OPTIMIZED: Heap stores only minimal metadata (~50 bytes per entry)
# Array of Dictionary entries with structure:
# {
#   "etd": float,              # Key for heap ordering (Estimated Time of Departure)
#   "plan_id": String,         # Flight plan ID (e.g., "FP000001") - used as key for route_storage
#   "received_time": float     # System clock time when route was received
# }
var successful_routes_heap: Array = []

# Full route data storage (keyed by plan_id)
# Dictionary structure: {plan_id: {"route": Array, "plan_data": Dictionary}}
# This stores the large route arrays separately from the heap for memory efficiency
var route_storage: Dictionary = {}

# Dictionary tracking pending route requests
# Key: plan_id (String), Value: Dictionary with request info
var pending_route_requests: Dictionary = {}

# Statistics tracking for failed pre-requests
var failed_pre_requests_count: int = 0  # Total count of failed pre-requests
var failed_pre_requests_by_status: Dictionary = {}  # Dictionary tracking failures by status type
var logger_instance: Node = null

# Route request timeout duration in seconds (float)
const ROUTE_REQUEST_TIMEOUT: float = 10.0  # 10 second timeout for pre-requests

# Maximum heap size to prevent unbounded growth (int)
const MAX_HEAP_SIZE: int = 1000  # Maximum number of routes in heap

func _ready():
	logger_instance = DebugLogger.get_instance()

	# Connect to WebSocket data_received signal to handle route responses
	# WebSocketManager is an autoload singleton, accessible directly
	if not WebSocketManager.data_received.is_connected(_on_websocket_response_received):
		WebSocketManager.data_received.connect(_on_websocket_response_received)
	
	# Connect to WebSocket connected signal to retry sending pending requests
	if not WebSocketManager.connected.is_connected(_on_websocket_connected):
		WebSocketManager.connected.connect(_on_websocket_connected)

func _log_info(event: String, data: Dictionary = {}):
	if logger_instance:
		logger_instance.log_event_info(DebugLogger.Category.ROUTE, event, data)
	else:
		DebugLogger.print_table_row_fallback("INFO", "ROUTE", event, data)

func _log_warning(event: String, data: Dictionary = {}):
	if logger_instance:
		logger_instance.log_event_warning(DebugLogger.Category.ROUTE, event, data)
	else:
		DebugLogger.print_table_row_fallback("WARNING", "ROUTE", event, data)

func _on_websocket_connected():
	"""
	Handle WebSocket connection established - retry sending any pending requests that failed to send
	"""
	# Retry sending any pending requests that failed to send due to connection not being ready
	# Only retry requests that were marked as not sent (sent = false)
	var requests_to_retry = []  # Array: List of plan dictionaries to retry
	
	for plan_id in pending_route_requests.keys():
		var request_info = pending_route_requests[plan_id]  # Dictionary: Request tracking info
		if not request_info.get("sent", false):  # Check if request was not successfully sent
			requests_to_retry.append(request_info.plan_data)  # Add plan data to retry list
	
	# Retry sending each request that failed
	for plan in requests_to_retry:
		send_route_request(plan)  # Retry sending the route request

func send_route_request(plan: Dictionary):
	"""
	Send route request to Python server for a flight plan
	
	Args:
		plan: Dictionary - Flight plan data containing:
			- id: String - Flight plan ID
			- etd_seconds: float - Estimated Time of Departure
			- origin_node_id: String - Origin graph node ID
			- dest_node_id: String - Destination graph node ID
			- origin_lat: float - Origin latitude
			- origin_lon: float - Origin longitude
			- dest_lat: float - Destination latitude
			- dest_lon: float - Destination longitude
			- model: String - Drone model type
	"""
	var plan_id = plan.get("id", "")  # String: Flight plan ID
	var current_simulation_time = SimulationEngine.current_simulation_time  # float: Current simulation time in seconds (for reference)
	var current_system_clock_time = Time.get_unix_time_from_system()  # float: System clock time when request is sent (seconds since Unix epoch - for timeout calculation)
	
	# Store request info in pending tracker (only if not already pending to avoid duplicates)
	if not pending_route_requests.has(plan_id):
		pending_route_requests[plan_id] = {
			"request_time_system_clock": current_system_clock_time,  # float: System clock time when request was sent (for timeout - real-world seconds)
			"request_time_simulation": current_simulation_time,  # float: Simulation time when request was sent (for reference)
			"etd": plan.get("etd_seconds", 0.0),  # float: Estimated Time of Departure
			"plan_data": plan,  # Dictionary: Full flight plan data (stored since removed from queue)
			"status": "pending",  # String: Request status ("pending" | "received" | "timeout" | "error")
			"sent": false  # bool: Whether request was successfully sent to server
		}
	else:
		# Request already pending - update request time but keep existing data
		pending_route_requests[plan_id].request_time_system_clock = current_system_clock_time  # Update system clock time for timeout calculation
		pending_route_requests[plan_id].request_time_simulation = current_simulation_time  # Update simulation time for reference
	
	# Get origin and destination positions from flight plan manager
	# RoutePreRequestManager is a child of SimulationEngine, so access flight_plan_manager through parent
	var simulation_engine = get_parent()  # SimulationEngine: Parent node (RoutePreRequestManager is child of SimulationEngine)
	
	# Check if parent exists
	if simulation_engine == null:
		# Fallback: Try absolute path if parent access fails
		simulation_engine = get_node_or_null("/root/SimulationEngine")
		if simulation_engine == null:
			return  # Exit early if SimulationEngine is not available
	
	# Get FlightPlanManager reference from SimulationEngine (may be null if not initialized)
	var flight_plan_manager = simulation_engine.get("flight_plan_manager")  # FlightPlanManager: Reference to flight plan manager (may be null)
	
	# Check if flight_plan_manager is valid before calling methods
	if flight_plan_manager == null:
		return  # Exit early if FlightPlanManager is null
	
	# Convert lat/lon coordinates to world positions using FlightPlanManager
	var origin = flight_plan_manager.latlon_to_position(plan.origin_lat, plan.origin_lon)  # Vector3: Origin position in meters
	var destination = flight_plan_manager.latlon_to_position(plan.dest_lat, plan.dest_lon)  # Vector3: Destination position in meters
	
	# Get model-specific max speed - matches drone.gd _set_model_attributes() values
	# These values must match the specifications in drone_models_specifications.txt
	var max_speed = 18.0  # float: Default max speed in m/s (Light Quadcopter)
	if plan.model == "Long Range FWVTOL":
		max_speed = 55.0  # float: Long range model max speed (m/s) - matches drone_models_specifications.txt
	elif plan.model == "Heavy Quadcopter":
		max_speed = 25.0  # float: Heavy quadcopter max speed (m/s) - matches drone_models_specifications.txt
	elif plan.model == "Light Quadcopter":
		max_speed = 18.0  # float: Light quadcopter max speed (m/s) - matches drone_models_specifications.txt
	
	# Create route request message (same format as drone route requests)
	var message_data = {
		"type": "request_route",
		"drone_id": plan_id,  # String: Use plan ID as drone_id
		"model": plan.get("model", ""),  # String: Drone model type
		"etd_seconds": plan.get("etd_seconds", 0.0),  # float: Planned ETD used as route temporal start
		"start_node_id": plan.get("origin_node_id", ""),  # String: Origin graph node ID
		"end_node_id": plan.get("dest_node_id", ""),  # String: Destination graph node ID
		"start_position": {
			"lon": origin.x,  # float: Godot X → Python longitude
			"lat": origin.z,  # float: Godot Z → Python latitude
			"alt": origin.y   # float: Godot Y → Python altitude
		},
		"end_position": {
			"lon": destination.x,  # float: Godot X → Python longitude
			"lat": destination.z,  # float: Godot Z → Python latitude
			"alt": destination.y    # float: Godot Y → Python altitude
		},
		"max_speed": max_speed,  # float: Maximum velocity in m/s
		"simulation_time": current_simulation_time  # float: Current simulation time in seconds
	}
	
	# Check if WebSocket is connected before sending
	if not WebSocketManager.is_connected:
		# Don't remove from pending - will retry when connection is established
		return
	
	# Record system clock time when request is sent
	var request_sent_time = Time.get_unix_time_from_system()  # float: System clock time when request is sent (seconds since epoch)
	
	# Add client request sent time to message for Python server timing
	message_data["client_request_sent_time"] = request_sent_time  # float: System clock time when Godot sent request
	
	# Convert to JSON and send via WebSocket
	var message = JSON.stringify(message_data)  # String: JSON-formatted message
	# WebSocketManager is an autoload singleton, accessible directly
	var send_result = WebSocketManager.send_message(message)  # bool: True if message sent successfully, False if failed
	if send_result:
		pending_route_requests[plan_id].sent = true  # Mark as successfully sent (bool)
		pending_route_requests[plan_id].request_sent_time = request_sent_time  # Store request sent time for timing calculation
		_log_info("pre_request_sent", {
			"plan_id": plan_id,
			"request_sent_system_clock_time": request_sent_time
		})
	else:
		pending_route_requests[plan_id].sent = false  # Mark as failed to send (bool)
		# Keep in pending - will retry when connection is established

func _on_websocket_response_received(data: PackedByteArray):
	"""
	Handle WebSocket response for route requests
	
	Args:
		data: PackedByteArray - WebSocket response data
	"""
	var response_text = data.get_string_from_utf8()  # String: Response text from WebSocket
	
	# Parse JSON response
	var json = JSON.new()  # JSON parser instance
	var parse_result = json.parse(response_text)  # Error: Parse result code
	
	if parse_result != OK:
		# Failed to parse JSON - ignore this response
		return
	
	var response_data = json.data  # Dictionary: Parsed response data
	
	# Check if this is a route response
	if not response_data.has("type") or response_data.type != "route_response":
		return  # Not a route response, ignore
	
	# Get plan_id from response (drone_id in response matches plan_id for pre-requests)
	var plan_id = response_data.get("drone_id", "")  # String: Flight plan ID
	
	# Check if this is a pre-request response
	if not pending_route_requests.has(plan_id):
		# This response is for an active drone, not a pre-request - ignore silently
		return
	
	# Record system clock time when response is received
	var response_received_time = Time.get_unix_time_from_system()  # float: System clock time when response is received (seconds since epoch)
	
	# Get request sent time from pending requests
	var request_info = pending_route_requests[plan_id]  # Dictionary: Request tracking info
	var request_sent_time = request_info.get("request_sent_time", 0.0)  # float: System clock time when request was sent
	
	# Calculate total round-trip time
	var total_round_trip_time = response_received_time - request_sent_time  # float: Total time from request sent to response received (seconds)
	
	_log_info("pre_request_response_received", {
		"plan_id": plan_id,
		"response_received_system_clock_time": response_received_time,
		"total_round_trip_time": total_round_trip_time
	})
	
	# Handle the response
	handle_route_response(response_data)

func handle_route_response(response_data: Dictionary):
	"""
	Process route response and either store in heap (success) or log failure
	
	Args:
		response_data: Dictionary - Route response from Python server containing:
			- drone_id: String - Flight plan ID
			- status: String - Response status ("success" | "timeout" | "error")
			- route: Array - Route waypoints (if success)
			- message: String - Error message (if failure)
	"""
	var plan_id = response_data.get("drone_id", "")  # String: Flight plan ID
	
	if not pending_route_requests.has(plan_id):
		# Orphaned response (shouldn't happen) - ignore silently
		return
	
	var request_info = pending_route_requests[plan_id]  # Dictionary: Request tracking info
	var status = response_data.get("status", "")  # String: Response status
	
	if status == "success" and response_data.has("route") and response_data.route is Array:
		# SUCCESS: Route received - store with memory-efficient separate storage
		# Check heap size limit before inserting
		if successful_routes_heap.size() >= MAX_HEAP_SIZE:
			pending_route_requests.erase(plan_id)
			return
		
		# Store full route data in separate storage dictionary (keyed by plan_id)
		route_storage[plan_id] = {
			"route": response_data.route,  # Array: Route waypoints from Python server
			"plan_data": request_info.plan_data  # Dictionary: Full flight plan data for drone creation
		}
		
		# Create minimal heap entry (only metadata needed for ordering)
		var heap_entry = {
			"etd": request_info.etd,  # float: Estimated Time of Departure (key for heap ordering)
			"plan_id": plan_id,  # String: Flight plan ID (reference key for route_storage)
			"received_time": Time.get_unix_time_from_system()  # float: System clock time when route was received
		}
		
		# Insert minimal entry into min-heap (ordered by ETD)
		heap_insert(heap_entry)
		
		# Remove from pending (now in heap and storage)
		pending_route_requests.erase(plan_id)
		
	else:
		# FAILURE: Timeout or error - don't store in heap
		# Log the failure with details
		# Use existing status variable (already declared above) or default to "unknown"
		if status == "":
			status = "unknown"
		var status_message = response_data.get("message", "Unknown error")
		var etd = request_info.get("etd", 0.0)
		
		# Update failure statistics
		failed_pre_requests_count += 1
		if not failed_pre_requests_by_status.has(status):
			failed_pre_requests_by_status[status] = 0
		failed_pre_requests_by_status[status] += 1
		
		if status == "no_path":
			_log_warning("pre_request_failed_no_path", {
				"plan_id": plan_id,
				"status": status,
				"etd": etd,
				"server_message": status_message,
				"action": "flight_plan_skipped"
			})
		elif status == "timeout":
			_log_warning("pre_request_timeout", {
				"plan_id": plan_id,
				"status": status,
				"etd": etd,
				"server_message": status_message,
				"action": "flight_plan_skipped"
			})
		elif status == "error":
			_log_warning("pre_request_error", {
				"plan_id": plan_id,
				"status": status,
				"etd": etd,
				"server_message": status_message,
				"action": "flight_plan_skipped"
			})
		else:
			_log_warning("pre_request_failed", {
				"plan_id": plan_id,
				"status": status,
				"etd": etd,
				"server_message": status_message,
				"action": "flight_plan_skipped"
			})
		
		# Remove from pending (FP is gone, not stored anywhere)
		pending_route_requests.erase(plan_id)

func check_timeouts(current_simulation_time: float):
	"""
	Check for timed-out route requests and handle them
	
	Args:
		current_simulation_time: float - Current simulation time in seconds (for reference, not used for timeout calculation)
	
	Note: Timeout is based on system clock time (real-world seconds), not simulation time,
		  because network communication and Python pathfinding happen in real-time.
	"""
	var timed_out_plans: Array = []  # Array: Plan IDs that have timed out
	var current_system_clock_time = Time.get_unix_time_from_system()  # float: Current system clock time (seconds since Unix epoch)
	
	# Check each pending request for timeout using system clock time
	for plan_id in pending_route_requests.keys():
		var request_info = pending_route_requests[plan_id]  # Dictionary: Request tracking info
		var request_time_system_clock = request_info.get("request_time_system_clock", 0.0)  # float: System clock time when request was sent
		
		# Check if timeout duration has elapsed (using real-world time, not simulation time)
		var elapsed_real_time = current_system_clock_time - request_time_system_clock  # float: Elapsed real-world time in seconds
		if elapsed_real_time > ROUTE_REQUEST_TIMEOUT:
			timed_out_plans.append(plan_id)  # Add to timeout list
	
	# Handle timed-out requests
	for plan_id in timed_out_plans:
		var request_info = pending_route_requests[plan_id]  # Dictionary: Request tracking info
		var etd = request_info.get("etd", 0.0)  # float: Estimated Time of Departure
		
		# Update failure statistics
		failed_pre_requests_count += 1
		if not failed_pre_requests_by_status.has("timeout"):
			failed_pre_requests_by_status["timeout"] = 0
		failed_pre_requests_by_status["timeout"] += 1
		
		_log_warning("pre_request_timeout_no_response", {
			"plan_id": plan_id,
			"status": "timeout",
			"etd": etd,
			"timeout_seconds": ROUTE_REQUEST_TIMEOUT,
			"action": "flight_plan_skipped"
		})
		
		# Remove from pending (FP is gone)
		pending_route_requests.erase(plan_id)

func peek_earliest_route() -> Dictionary:
	"""
	Get the route with earliest ETD without removing it from heap.
	Fetches full route data from storage and combines with heap metadata.
	
	Returns:
		Dictionary - Complete route entry with earliest ETD (includes route and plan_data),
					 or empty Dictionary if heap is empty
	"""
	if successful_routes_heap.is_empty():
		return {}  # Empty Dictionary if heap is empty
	
	var heap_entry = successful_routes_heap[0]  # Dictionary: Minimal heap entry (etd, plan_id, received_time)
	var plan_id = heap_entry.get("plan_id", "")  # String: Plan ID to lookup in storage
	
	# Check if route data exists in storage
	if not route_storage.has(plan_id):
		# Storage entry missing - this shouldn't happen, but handle gracefully
		return {}  # Return empty if storage entry missing
	
	# Fetch full route data from storage
	var route_data = route_storage[plan_id]  # Dictionary: Full route data (route, plan_data)
	
	# Combine heap metadata with full route data
	var complete_entry = {
		"etd": heap_entry.etd,  # float: Estimated Time of Departure
		"plan_id": plan_id,  # String: Flight plan ID
		"route": route_data.route,  # Array: Route waypoints from Python server
		"plan_data": route_data.plan_data,  # Dictionary: Full flight plan data
		"received_time": heap_entry.received_time  # float: System clock time when route was received
	}
	
	return complete_entry  # Return combined entry with full route data

func pop_earliest_route() -> Dictionary:
	"""
	Remove and return the route with earliest ETD from heap.
	Fetches full route data from storage, removes from both heap and storage.
	
	Returns:
		Dictionary - Complete route entry with earliest ETD (includes route and plan_data),
					 or empty Dictionary if heap is empty
	"""
	if successful_routes_heap.is_empty():
		return {}  # Empty Dictionary if heap is empty
	
	# Get earliest heap entry (minimal metadata)
	var heap_entry = successful_routes_heap[0]  # Dictionary: Minimal heap entry (etd, plan_id, received_time)
	var plan_id = heap_entry.get("plan_id", "")  # String: Plan ID to lookup in storage
	
	# Fetch full route data from storage before removing from heap
	var route_data = null  # Dictionary: Full route data (route, plan_data) or null
	if route_storage.has(plan_id):
		route_data = route_storage[plan_id]  # Fetch full route data
		route_storage.erase(plan_id)  # Remove from storage (no longer needed)
	else:
		# Storage entry missing - this shouldn't happen, but handle gracefully
		# Still remove from heap to prevent corruption
		if successful_routes_heap.size() > 1:
			successful_routes_heap[0] = successful_routes_heap.pop_back()
			_bubble_down(0)
		else:
			successful_routes_heap.pop_back()
		return {}  # Return empty if storage entry missing
	
	# Remove from heap (bubble down to maintain heap property)
	if successful_routes_heap.size() > 1:
		successful_routes_heap[0] = successful_routes_heap.pop_back()  # Move last to root
		# Bubble down to maintain heap property
		_bubble_down(0)  # Start bubbling down from root
	else:
		successful_routes_heap.pop_back()  # Remove last element
	
	# Combine heap metadata with full route data
	var complete_entry = {
		"etd": heap_entry.etd,  # float: Estimated Time of Departure
		"plan_id": plan_id,  # String: Flight plan ID
		"route": route_data.route,  # Array: Route waypoints from Python server
		"plan_data": route_data.plan_data,  # Dictionary: Full flight plan data
		"received_time": heap_entry.received_time  # float: System clock time when route was received
	}
	
	return complete_entry  # Return combined entry with full route data

func is_heap_empty() -> bool:
	"""
	Check if the heap is empty
	
	Returns:
		bool - True if heap is empty, False otherwise
	"""
	return successful_routes_heap.is_empty()

func heap_insert(heap_entry: Dictionary):
	"""
	Insert a minimal heap entry into the min-heap (ordered by ETD).
	Note: Full route data should already be stored in route_storage before calling this.
	
	Args:
		heap_entry: Dictionary - Minimal heap entry with "etd" and "plan_id" keys for ordering
					Expected structure: {"etd": float, "plan_id": String, "received_time": float}
	"""
	# Validate heap entry has required fields
	if not heap_entry.has("etd") or not heap_entry.has("plan_id"):
		return  # Invalid entry - skip silently
	
	# Add to end of array
	successful_routes_heap.append(heap_entry)  # Add minimal entry to end of heap array
	
	# Bubble up to maintain heap property
	_bubble_up(successful_routes_heap.size() - 1)  # Start bubbling up from last index

func _bubble_up(index: int):
	"""
	Bubble up element at given index to maintain min-heap property
	
	Args:
		index: int - Index of element to bubble up
	"""
	if index == 0:
		return  # Root node, can't bubble up further
	
	var parent_index = _get_parent_index(index)  # int: Parent node index
	
	# Compare ETD values (min-heap: parent should be <= child)
	if successful_routes_heap[parent_index].etd > successful_routes_heap[index].etd:
		# Swap parent and child
		var temp = successful_routes_heap[parent_index]  # Dictionary: Temporary storage
		successful_routes_heap[parent_index] = successful_routes_heap[index]
		successful_routes_heap[index] = temp
		
		# Continue bubbling up
		_bubble_up(parent_index)

func _bubble_down(index: int):
	"""
	Bubble down element at given index to maintain min-heap property
	
	Args:
		index: int - Index of element to bubble down
	"""
	var heap_size = successful_routes_heap.size()  # int: Current heap size
	var smallest = index  # int: Index of smallest element (initially current index)
	
	var left_child = _get_left_child_index(index)  # int: Left child index
	var right_child = _get_right_child_index(index)  # int: Right child index
	
	# Compare with left child
	if left_child < heap_size and successful_routes_heap[left_child].etd < successful_routes_heap[smallest].etd:
		smallest = left_child  # Left child is smaller
	
	# Compare with right child
	if right_child < heap_size and successful_routes_heap[right_child].etd < successful_routes_heap[smallest].etd:
		smallest = right_child  # Right child is smaller
	
	# If smallest is not current index, swap and continue bubbling down
	if smallest != index:
		var temp = successful_routes_heap[index]  # Dictionary: Temporary storage
		successful_routes_heap[index] = successful_routes_heap[smallest]
		successful_routes_heap[smallest] = temp
		
		# Continue bubbling down
		_bubble_down(smallest)

func _get_parent_index(index: int) -> int:
	"""
	Get parent index of given node in heap
	
	Args:
		index: int - Child node index
	
	Returns:
		int - Parent node index
	"""
	return (index - 1) / 2  # Integer division for parent index

func _get_left_child_index(index: int) -> int:
	"""
	Get left child index of given node in heap
	
	Args:
		index: int - Parent node index
	
	Returns:
		int - Left child node index
	"""
	return 2 * index + 1  # Left child index formula

func _get_right_child_index(index: int) -> int:
	"""
	Get right child index of given node in heap
	
	Args:
		index: int - Parent node index
	
	Returns:
		int - Right child node index
	"""
	return 2 * index + 2  # Right child index formula

func has_route(plan_id: String) -> bool:
	"""
	Check if a route exists in storage for a given plan ID.
	Uses O(1) dictionary lookup instead of O(n) linear search.
	
	Args:
		plan_id: String - Flight plan ID to check
	
	Returns:
		bool - True if route exists in storage, False otherwise
	"""
	# Use dictionary lookup for O(1) performance (much faster than linear search)
	return route_storage.has(plan_id)  # bool: True if route exists, False otherwise

func print_failed_pre_requests_summary():
	"""
	Print a summary of failed pre-requests.
	Useful for debugging and monitoring route generation failures.
	"""
	if failed_pre_requests_count == 0:
		return  # No failures to report

	_log_warning("pre_request_failures_summary", {
		"total_failed_pre_requests": failed_pre_requests_count,
		"failed_pre_requests_by_status": failed_pre_requests_by_status
	})

func cleanup_stale_routes(current_simulation_time: float, max_age_seconds: float = 300.0):
	"""
	Remove routes from heap and storage that have ETD far in the past.
	This prevents memory accumulation from routes that were never consumed.
	
	Args:
		current_simulation_time: float - Current simulation time in seconds
		max_age_seconds: float - Maximum age in seconds before route is considered stale (default: 300.0 = 5 minutes)
	"""
	var stale_plan_ids: Array = []  # Array: Plan IDs to remove (list of String)
	
	# Find all routes with ETD far in the past
	for heap_entry in successful_routes_heap:
		var etd = heap_entry.get("etd", 0.0)  # float: Estimated Time of Departure
		var age = current_simulation_time - etd  # float: Age of route in seconds
		
		# If route is older than max_age_seconds, mark for removal
		if age > max_age_seconds:
			var plan_id = heap_entry.get("plan_id", "")  # String: Plan ID to remove
			if plan_id != "":
				stale_plan_ids.append(plan_id)  # Add to removal list
	
	# Remove stale routes
	var removed_count = 0  # int: Number of routes removed
	for plan_id in stale_plan_ids:
		# Remove from storage
		if route_storage.has(plan_id):
			route_storage.erase(plan_id)  # Remove from storage
			removed_count += 1  # Increment removal count
		
		# Remove from heap (linear search - acceptable since cleanup is infrequent)
		var heap_index = -1  # int: Index of entry to remove (-1 if not found)
		for i in range(successful_routes_heap.size()):
			if successful_routes_heap[i].get("plan_id", "") == plan_id:
				heap_index = i  # Found entry to remove
				break
		
		# Remove from heap if found
		if heap_index >= 0:
			# Move last element to removed position
			if successful_routes_heap.size() > 1:
				successful_routes_heap[heap_index] = successful_routes_heap.pop_back()  # Move last to removed position
				# Re-heapify from the moved position
				_bubble_down(heap_index)  # Bubble down to maintain heap property
				_bubble_up(heap_index)  # Also bubble up in case moved element is smaller
			else:
				successful_routes_heap.pop_back()  # Remove last element
	
	# Cleanup completed silently (no logging needed)

func get_heap_stats() -> Dictionary:
	"""
	Get statistics about the current heap and storage state.
	Useful for monitoring memory usage and debugging.
	
	Returns:
		Dictionary - Statistics with keys:
			- heap_size: int - Number of entries in heap
			- storage_size: int - Number of routes in storage
			- heap_memory_estimate: int - Estimated heap memory in bytes (~50 bytes per entry)
			- storage_memory_estimate: int - Estimated storage memory in bytes (approximate)
			- failed_pre_requests_count: int - Total number of failed pre-requests
			- failed_pre_requests_by_status: Dictionary - Failures grouped by status type
	"""
	var heap_size = successful_routes_heap.size()  # int: Current heap size
	var storage_size = route_storage.size()  # int: Current storage size
	var heap_memory_estimate = heap_size * 50  # int: Estimated heap memory (50 bytes per minimal entry)
	
	# Estimate storage memory (rough approximation: 10 KB per route)
	var storage_memory_estimate = storage_size * 10240  # int: Estimated storage memory (10 KB per route)
	
	return {
		"heap_size": heap_size,  # int: Number of entries in heap
		"storage_size": storage_size,  # int: Number of routes in storage
		"heap_memory_estimate": heap_memory_estimate,  # int: Estimated heap memory in bytes
		"storage_memory_estimate": storage_memory_estimate,  # int: Estimated storage memory in bytes
		"max_heap_size": MAX_HEAP_SIZE,  # int: Maximum allowed heap size
		"failed_pre_requests_count": failed_pre_requests_count,  # int: Total failed pre-requests
		"failed_pre_requests_by_status": failed_pre_requests_by_status.duplicate()  # Dictionary: Failures by status
	}
