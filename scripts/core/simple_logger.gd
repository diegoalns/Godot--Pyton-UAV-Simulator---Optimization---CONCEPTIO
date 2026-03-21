class_name SimpleLogger
extends Node

var logger_instance: Node = null

# FileAccess objects for different log files
var log_file: FileAccess  # Main drone states log
var collision_log_file: FileAccess  # Collision events log
var log_interval: float = 10.0  # Log every 10 seconds
var time_since_log: float = 0.0

# Singleton reference for collision logging from anywhere
static var instance: SimpleLogger

func _ready():
	logger_instance = DebugLogger.get_instance()
	# Set singleton instance for global access
	instance = self
	create_log_file()

func create_log_file():
	# Create logs directory if it doesn't exist
	var dir = DirAccess.open("res://")
	if not dir.dir_exists("logs"):
		dir.make_dir("logs")
	
	# Create main drone states log file (skip in GA quiet mode to reduce I/O)
	var ga_log_level = OS.get_environment("GA_LOG_LEVEL")
	if ga_log_level != "quiet":
		var filename = "res://logs/simple_log.csv"
		var filename_override = OS.get_environment("GA_SIMPLE_LOG_CSV")
		if filename_override != "":
			filename = filename_override
			DirAccess.make_dir_recursive_absolute(filename.get_base_dir())
		log_file = FileAccess.open(filename, FileAccess.WRITE)
		if log_file:
			log_file.store_csv_line(["Time", "DroneID", "X", "Y", "Z", "Target position", "Target Speed", "Origin Lat", "Origin Lon", "Destination Lat", "Destination Lon", "Completed"])
			if logger_instance:
				logger_instance.print_table_line("INFO", "GENERAL", "log_file_created", {"filename": filename})
			else:
				DebugLogger.print_table_row_fallback("INFO", "GENERAL", "log_file_created", {"filename": filename})
	
	# Create collision events log file
	var collision_filename = "res://logs/collision_log.csv"
	var collision_filename_override = OS.get_environment("GA_COLLISION_LOG_CSV")
	if collision_filename_override != "":
		collision_filename = collision_filename_override
		DirAccess.make_dir_recursive_absolute(collision_filename.get_base_dir())
	collision_log_file = FileAccess.open(collision_filename, FileAccess.WRITE)
	if collision_log_file:
		collision_log_file.store_csv_line(["Simulation_Time", "Event_Type", "Drone_1", "Drone_2", "Distance", "Collision_Threshold", "Drone_1_Position", "Drone_2_Position", "Drone_1_Speed", "Drone_2_Speed"])

func update(time_step: float, sim_time: float, drones: Dictionary):
	time_since_log += time_step
	
	if time_since_log >= log_interval:
		log_drone_states(sim_time, drones)
		time_since_log = 0.0

func log_drone_states(sim_time: float, drones: Dictionary):
	if not log_file:
		return
	
	for drone in drones.values():
		log_file.store_csv_line([
			"%.2f" % sim_time,
			#drone.port_id,
			drone.drone_id,
			"%.2f" % drone.current_position.x,
			"%.2f" % drone.current_position.y,
			"%.2f" % drone.current_position.z,
			drone.target_position,
			drone.target_speed,
			drone.origin_position.x,
			drone.origin_position.z,
			drone.destination_position.x,
			drone.destination_position.z,
			str(drone.completed)
		])

func log_collision_event(sim_time: float, event_type: String, drone1: Drone, drone2: Drone, distance: float, threshold: float):
	"""
	Log a collision event to the CSV file
	
	Args:
		sim_time: Current simulation time in seconds
		event_type: Type of collision event ("COLLISION_START" or "COLLISION_END")
		drone1: First drone involved in collision
		drone2: Second drone involved in collision  
		distance: Distance between drone centers in meters
		threshold: Collision threshold distance in meters
	"""
	if not collision_log_file:
		return
	
	# Format position vectors as strings for CSV
	var drone1_pos_str = "(%.2f,%.2f,%.2f)" % [drone1.current_position.x, drone1.current_position.y, drone1.current_position.z]
	var drone2_pos_str = "(%.2f,%.2f,%.2f)" % [drone2.current_position.x, drone2.current_position.y, drone2.current_position.z]
	
	# Log collision event data to CSV
	collision_log_file.store_csv_line([
		"%.2f" % sim_time,                    # Simulation time
		event_type,                           # Event type (START/END)
		drone1.drone_id,                      # First drone ID
		drone2.drone_id,                      # Second drone ID
		"%.2f" % distance,                    # Distance between drones
		"%.2f" % threshold,                   # Collision threshold
		drone1_pos_str,                       # Drone 1 position
		drone2_pos_str,                       # Drone 2 position
		"%.2f" % drone1.current_speed,        # Drone 1 speed
		"%.2f" % drone2.current_speed         # Drone 2 speed
	])
	
	# Flush to ensure data is written immediately
	collision_log_file.flush()

func close_log():
	# Close main drone states log file
	if log_file:
		log_file.close()
	
	# Close collision events log file
	if collision_log_file:
		collision_log_file.close()

func _exit_tree():
	close_log()
