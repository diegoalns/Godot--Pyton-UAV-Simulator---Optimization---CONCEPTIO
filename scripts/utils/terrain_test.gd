extends Node

# Simple test script to verify terrain system functionality
# This can be attached to a test node to validate the GridMap terrain loading

var logger_instance: Node = null

func _log(event: String, data: Dictionary = {}):
	if logger_instance:
		logger_instance.print_table_line("INFO", "TERRAIN", event, data)
	else:
		DebugLogger.print_table_row_fallback("INFO", "TERRAIN", event, data)

func test_terrain_system():
	"""
	Test function to validate terrain system functionality
	Call this from _ready() or manually to test the system
	"""
	logger_instance = DebugLogger.get_instance()
	_log("terrain_test_start", {})
	
	# Wait a moment for the terrain system to initialize
	await get_tree().create_timer(2.0).timeout
	
	# Find the simulation engine in the scene
	var simulation_engine = get_tree().get_first_node_in_group("simulation_engine")
	if not simulation_engine:
		# Try to find it by class name
		simulation_engine = get_node("/root/Main")
		if not simulation_engine or not simulation_engine is SimulationEngine:
			_log("simulation_engine_not_found", {})
			return
	
	_log("simulation_engine_found", {})
	
	# Test terrain info retrieval
	var terrain_info = simulation_engine.get_terrain_info()
	if terrain_info.is_empty():
		_log("terrain_info_empty", {})
	else:
		var data: Dictionary = {
			"data_points": terrain_info.get("data_points", "unknown"),
			"approach": terrain_info.get("approach", "unknown"),
			"tile_size_meters": terrain_info.get("tile_size_meters", "unknown")
		}
		var bounds = terrain_info.get("coordinate_bounds", {})
		if not bounds.is_empty():
			data["min_lat"] = bounds.get("min_lat", 0)
			data["max_lat"] = bounds.get("max_lat", 0)
			data["min_lon"] = bounds.get("min_lon", 0)
			data["max_lon"] = bounds.get("max_lon", 0)
		var origin = terrain_info.get("origin_reference", {})
		if not origin.is_empty():
			data["origin_lat"] = origin.get("lat", 0)
			data["origin_lon"] = origin.get("lon", 0)
		_log("terrain_info", data)
	
	# Test visualization system terrain access directly
	var vis_system = simulation_engine.visualization_system
	if vis_system and vis_system.is_terrain_ready():
		_log("terrain_ready", {"gridmap_exists": vis_system.terrain_gridmap != null, "gridmap_manager_exists": vis_system.gridmap_manager != null})
	else:
		_log("terrain_not_ready", {})
	
	# Test altitude queries at various positions
	var test_positions = [
		Vector3(0, 0, 0),
		Vector3(1000, 0, 1000),
		Vector3(5000, 0, 5000),
		Vector3(-1000, 0, -1000)
	]
	
	for pos in test_positions:
		var altitude = simulation_engine.get_terrain_altitude_at_position(pos)
		_log("altitude_query", {"position": str(pos), "altitude": altitude})
	
	_log("terrain_test_complete", {})

func _ready():
	# Automatically run test when this node is ready
	logger_instance = DebugLogger.get_instance()
	if logger_instance:
		logger_instance.print_table_line("INFO", "TERRAIN", "terrain_test_ready", {})
	else:
		DebugLogger.print_table_row_fallback("INFO", "TERRAIN", "terrain_test_ready", {})
	await get_tree().create_timer(3.0).timeout
	test_terrain_system()
