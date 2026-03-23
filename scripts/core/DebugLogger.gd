class_name DebugLogger
extends Node

# ============================================================================
# NOTE: This is an autoload singleton
# ============================================================================
# When DebugLogger is added as an autoload singleton in Project Settings,
# it becomes accessible globally. However, since we also use class_name,
# we need to access the singleton instance, not the class.
#
# Autoload node name must differ from class_name (Godot restriction). This project uses
# /root/AppDebugLogger. Use DebugLogger.get_instance() from scripts.
# ============================================================================

# ============================================================================
# LOG LEVELS - Enum for message importance
# ============================================================================
enum LogLevel {
	DEBUG = 0,    # Detailed diagnostic information
	INFO = 1,    # General informational messages
	WARNING = 2, # Warning messages
	ERROR = 3    # Error conditions
}

# ============================================================================
# VERBOSITY LEVELS - Control detail level of output
# ============================================================================
enum VerbosityLevel {
	SILENT = 0,   # Only errors
	MINIMAL = 1,  # Only critical operations
	NORMAL = 2,   # Standard operations (default)
	VERBOSE = 3   # All operations including debug details
}

# ============================================================================
# CATEGORIES - Message categories for filtering
# ============================================================================
enum Category {
	ROUTE,         # Route pre-request manager operations
	WEBSOCKET,     # WebSocket connection/communication
	DRONE,         # Drone creation/management
	SIMULATION,    # Simulation engine updates
	TERRAIN,       # Terrain/gridmap operations
	VISUALIZATION, # Visualization system
	HEAP,          # Heap operations
	FLIGHT_PLAN,   # Flight plan management
	GENERAL        # General/unclassified messages
}

# ============================================================================
# CONFIGURATION - Logging settings
# ============================================================================
# Current log level - only messages at or above this level will be printed
var current_log_level: LogLevel = LogLevel.INFO

# Current verbosity level - controls detail level of output
var current_verbosity: VerbosityLevel = VerbosityLevel.NORMAL

# Category enable/disable flags - Dictionary mapping Category enum to bool
var category_enabled: Dictionary = {}

# Enable timestamps in log messages
var show_timestamps: bool = true

# Enable color coding (if console supports ANSI colors)
var use_colors: bool = false

# Emit dictionary payloads even at NORMAL verbosity to keep logs parse-friendly.
var always_include_data: bool = true

# Use fixed-width table format for all log output (unified Godot + Python format)
var use_table_format: bool = true

# Fixed-width column sizes: ts | level | category | source | event | data
const TABLE_WIDTH_TS: int = 12
const TABLE_WIDTH_LEVEL: int = 8
const TABLE_WIDTH_CATEGORY: int = 14
const TABLE_WIDTH_SOURCE: int = 6
const TABLE_WIDTH_EVENT: int = 32
const TABLE_WIDTH_DATA: int = 150

# Reference to simulation engine for getting simulation time
var simulation_engine: Node = null

var _table_header_printed: bool = false

# ============================================================================
# INITIALIZATION
# ============================================================================
func _ready():
	# Initialize all categories as enabled by default
	for category in Category.values():
		category_enabled[category] = true

	# Apply batch run log mode from environment so Godot matches Python orchestration.
	var ga_log_level = OS.get_environment("GA_LOG_LEVEL").strip_edges().to_lower()
	if ga_log_level == "quiet":
		current_log_level = LogLevel.ERROR
		current_verbosity = VerbosityLevel.MINIMAL
	elif ga_log_level == "verbose":
		current_log_level = LogLevel.DEBUG
		current_verbosity = VerbosityLevel.VERBOSE
	elif ga_log_level == "normal":
		current_log_level = LogLevel.INFO
		current_verbosity = VerbosityLevel.NORMAL
	
	# Try to find simulation engine for timestamps (will be set up after simulation starts)
	# Don't log here to avoid circular initialization issues
	# simulation_engine will be set when first accessed via get_current_simulation_time()

	# Emit resolved mode once at startup for observability.
	log_event_info(Category.GENERAL, "logging_mode_applied", {
		"ga_log_level": ga_log_level if ga_log_level != "" else "(unset)",
		"log_level": LogLevel.keys()[current_log_level],
		"verbosity": VerbosityLevel.keys()[current_verbosity]
	})

# ============================================================================
# LOGGING METHODS - Main interface for logging
# ============================================================================
func log_debug(category: Category, message: String, data: Dictionary = {}):
	"""
	Log a DEBUG level message with optional data dictionary.
	
	Args:
		category: Category - Message category for filtering
		message: String - Message text to log
		data: Dictionary - Optional additional data (default: empty)
	"""
	log_message(LogLevel.DEBUG, category, message, data)

func log_info(category: Category, message: String, data: Dictionary = {}):
	"""
	Log an INFO level message with optional data dictionary.
	
	Args:
		category: Category - Message category for filtering
		message: String - Message text to log
		data: Dictionary - Optional additional data (default: empty)
	"""
	log_message(LogLevel.INFO, category, message, data)

func log_warning(category: Category, message: String, data: Dictionary = {}):
	"""
	Log a WARNING level message with optional data dictionary.
	
	Args:
		category: Category - Message category for filtering
		message: String - Message text to log
		data: Dictionary - Optional additional data (default: empty)
	"""
	log_message(LogLevel.WARNING, category, message, data)

func log_error(category: Category, message: String, data: Dictionary = {}):
	"""
	Log an ERROR level message with optional data dictionary.
	Also calls push_error() for Godot error system integration.
	
	Args:
		category: Category - Message category for filtering
		message: String - Message text to log
		data: Dictionary - Optional additional data (default: empty)
	"""
	log_message(LogLevel.ERROR, category, message, data)
	# Also push to Godot error system
	push_error("[%s] %s" % [Category.keys()[category], message])

# ============================================================================
# CORE LOGGING LOGIC
# ============================================================================
func log_message(level: LogLevel, category: Category, message: String, data: Dictionary = {}):
	"""
	Core logging method that handles filtering and formatting.
	
	Args:
		level: LogLevel - Message importance level
		category: Category - Message category
		message: String - Message text
		data: Dictionary - Optional additional data
	"""
	# Check if message should be logged based on level
	if level < current_log_level:
		return  # Message level too low, skip
	
	# Check if category is enabled
	if not category_enabled.get(category, true):
		return  # Category disabled, skip
	
	# Print table header on first log (fixed-width format)
	if use_table_format and not _table_header_printed:
		_table_header_printed = true
		print(get_table_header())
	
	# Format and print the message
	var formatted_message = format_message(level, category, message, data)
	print(formatted_message)

func format_message(level: LogLevel, category: Category, message: String, data: Dictionary) -> String:
	"""
	Format a log message with level, category, timestamp, and optional data.
	Uses fixed-width table format when use_table_format is true.
	
	Args:
		level: LogLevel - Message importance level
		category: Category - Message category
		message: String - Message text
		data: Dictionary - Optional additional data
	
	Returns:
		String - Formatted log message
	"""
	if use_table_format:
		var ts = get_timestamp() if show_timestamps else ""
		var level_str = LogLevel.keys()[level]
		var category_str = Category.keys()[category]
		var data_str = ""
		if not data.is_empty() and (always_include_data or current_verbosity >= VerbosityLevel.VERBOSE):
			data_str = format_data(data)
		return format_table_row_string(ts, level_str, category_str, "godot", message, data_str)
	
	# Legacy format
	var parts: Array = []
	if show_timestamps:
		parts.append("[%s]" % get_timestamp())
	parts.append("[%s]" % LogLevel.keys()[level])
	parts.append("[%s]" % Category.keys()[category])
	parts.append(message)
	if not data.is_empty() and (always_include_data or current_verbosity >= VerbosityLevel.VERBOSE):
		parts.append(" | Data: %s" % format_data(data))
	return " ".join(parts)

static func _pad_cell(s: String, width: int, truncate: bool = true) -> String:
	"""Pad or truncate string to fixed width."""
	var str_val = str(s)
	if str_val.length() >= width:
		return str_val.substr(0, width) if truncate else str_val
	return str_val + " ".repeat(width - str_val.length())

static func format_table_row_string(ts: String, level: String, category: String, source: String, event: String, data: String) -> String:
	"""
	Format a single log line as fixed-width table row.
	Unified format for Godot and Python - same column widths and alignment.
	
	Args:
		ts: Timestamp (e.g. "12.34s" or "1730556789.12")
		level: DEBUG, INFO, WARNING, ERROR
		category: ROUTE, WEBSOCKET, DRONE, etc.
		source: "godot" or "python"
		event: Short event name
		data: Key=value pairs or additional info
	
	Returns:
		String - Fixed-width formatted row
	"""
	var ts_pad = _pad_cell(ts, TABLE_WIDTH_TS)
	var level_pad = _pad_cell(level, TABLE_WIDTH_LEVEL)
	var cat_pad = _pad_cell(category, TABLE_WIDTH_CATEGORY)
	var src_pad = _pad_cell(source, TABLE_WIDTH_SOURCE)
	var evt_pad = _pad_cell(event, TABLE_WIDTH_EVENT)
	var data_pad = _pad_cell(data, TABLE_WIDTH_DATA)
	return "%s %s %s %s %s %s" % [ts_pad, level_pad, cat_pad, src_pad, evt_pad, data_pad]

static func get_table_header() -> String:
	"""Return fixed-width table header row."""
	return format_table_row_string("ts", "level", "category", "source", "event", "data")

static var _fallback_header_printed: bool = false

static func format_data_static(data: Dictionary) -> String:
	"""Format data dictionary for table data column. Use when logger instance unavailable."""
	if data.is_empty():
		return ""
	var parts: Array = []
	var sorted_keys = data.keys()
	sorted_keys.sort()
	for key in sorted_keys:
		parts.append("%s=%s" % [key, str(data[key])])
	return "{%s}" % ", ".join(parts)

static func print_table_row_fallback(level_str: String, category_str: String, event: String, data: Dictionary = {}):
	"""
	Print fixed-width table row when DebugLogger instance is unavailable.
	Use in else branch when logger_instance is null.
	"""
	if not _fallback_header_printed:
		_fallback_header_printed = true
		print(get_table_header())
	var ts = "%.2fs" % Time.get_unix_time_from_system()
	var data_str = format_data_static(data)
	print(format_table_row_string(ts, level_str, category_str, "godot", event, data_str))

func _parse_level_string(level_str: String) -> int:
	var normalized = level_str.strip_edges().to_upper()
	if normalized == "DEBUG":
		return LogLevel.DEBUG
	if normalized == "WARNING":
		return LogLevel.WARNING
	if normalized == "ERROR":
		return LogLevel.ERROR
	return LogLevel.INFO

func _is_category_enabled_by_name(category_str: String) -> bool:
	var normalized = category_str.strip_edges().to_upper()
	var category_names = Category.keys()
	var idx = category_names.find(normalized)
	if idx == -1:
		return true
	var category_value = Category.values()[idx]
	return category_enabled.get(category_value, true)

func print_table_line(level_str: String, category_str: String, event: String, data_dict: Dictionary = {}):
	"""
	Print a single table row. Use when not going through log_message.
	Ensures header is printed on first use. Source is always "godot".
	"""
	var level_value = _parse_level_string(level_str)
	if level_value < current_log_level:
		return
	if not _is_category_enabled_by_name(category_str):
		return
	if use_table_format and not _table_header_printed:
		_table_header_printed = true
		print(get_table_header())
	var ts = get_timestamp() if show_timestamps else ""
	var data_str = format_data(data_dict) if not data_dict.is_empty() else ""
	print(format_table_row_string(ts, level_str, category_str, "godot", event, data_str))

func format_data(data: Dictionary) -> String:
	"""
	Format a data dictionary as a string for logging.
	
	Args:
		data: Dictionary - Data to format
	
	Returns:
		String - Formatted data string
	"""
	var parts: Array = []  # Array: Formatted key-value pairs
	var sorted_keys = data.keys()
	sorted_keys.sort()
	for key in sorted_keys:
		var value = data[key]  # Value to format
		var value_str = str(value)  # String: String representation of value
		parts.append("%s=%s" % [key, value_str])
	return "{%s}" % ", ".join(parts)

func get_timestamp() -> String:
	"""
	Get current timestamp for log messages.
	Uses simulation time if available, otherwise system time.
	
	Returns:
		String - Formatted timestamp
	"""
	var sim_time = get_current_simulation_time()  # float: Simulation time (or 0.0 if not available)
	if sim_time > 0.0:
		# Use simulation time if available
		return "%.2fs" % sim_time
	else:
		# Fallback to system time
		var system_time = Time.get_unix_time_from_system()  # float: System time
		return "%.2fs" % system_time

# ============================================================================
# CONFIGURATION METHODS - Control logging behavior
# ============================================================================
func set_log_level(level: LogLevel):
	"""
	Set the minimum log level. Only messages at or above this level will be printed.
	
	Args:
		level: LogLevel - Minimum log level to display
	"""
	current_log_level = level
	log_info(Category.GENERAL, "Log level set to: %s" % LogLevel.keys()[level])

func set_verbosity(verbosity: VerbosityLevel):
	"""
	Set the verbosity level. Controls detail level of output.
	
	Args:
		verbosity: VerbosityLevel - Verbosity level to use
	"""
	current_verbosity = verbosity
	log_info(Category.GENERAL, "Verbosity set to: %s" % VerbosityLevel.keys()[verbosity])

func set_category_enabled(category: Category, enabled: bool):
	"""
	Enable or disable a specific message category.
	
	Args:
		category: Category - Category to enable/disable
		enabled: bool - True to enable, False to disable
	"""
	category_enabled[category] = enabled
	var status = "enabled" if enabled else "disabled"  # String: Status text
	log_info(Category.GENERAL, "Category %s %s" % [Category.keys()[category], status])

func enable_all_categories():
	"""Enable all message categories."""
	for category in Category.values():
		category_enabled[category] = true
	log_info(Category.GENERAL, "All categories enabled")

func disable_all_categories():
	"""Disable all message categories."""
	for category in Category.values():
		category_enabled[category] = false
	log_info(Category.GENERAL, "All categories disabled")

func set_timestamps_enabled(enabled: bool):
	"""
	Enable or disable timestamps in log messages.
	
	Args:
		enabled: bool - True to show timestamps, False to hide
	"""
	show_timestamps = enabled

func set_table_format(enabled: bool):
	"""Enable or disable fixed-width table format."""
	use_table_format = enabled

# ============================================================================
# CONVENIENCE METHODS - Quick access for common operations
# ============================================================================
func log_route_debug(message: String, data: Dictionary = {}):
	"""Convenience method for route debug messages."""
	log_debug(Category.ROUTE, message, data)

func log_route_info(message: String, data: Dictionary = {}):
	"""Convenience method for route info messages."""
	log_info(Category.ROUTE, message, data)

func log_route_warning(message: String, data: Dictionary = {}):
	"""Convenience method for route warning messages."""
	log_warning(Category.ROUTE, message, data)

func log_route_error(message: String, data: Dictionary = {}):
	"""Convenience method for route error messages."""
	log_error(Category.ROUTE, message, data)

func log_websocket_info(message: String, data: Dictionary = {}):
	"""Convenience method for WebSocket info messages."""
	log_info(Category.WEBSOCKET, message, data)

func log_websocket_warning(message: String, data: Dictionary = {}):
	"""Convenience method for WebSocket warning messages."""
	log_warning(Category.WEBSOCKET, message, data)

func log_websocket_error(message: String, data: Dictionary = {}):
	"""Convenience method for WebSocket error messages."""
	log_error(Category.WEBSOCKET, message, data)

func log_drone_info(message: String, data: Dictionary = {}):
	"""Convenience method for drone info messages."""
	log_info(Category.DRONE, message, data)

func log_drone_debug(message: String, data: Dictionary = {}):
	"""Convenience method for drone debug messages."""
	log_debug(Category.DRONE, message, data)

func log_simulation_info(message: String, data: Dictionary = {}):
	"""Convenience method for simulation info messages."""
	log_info(Category.SIMULATION, message, data)

func log_event_info(category: Category, event: String, data: Dictionary = {}):
	"""Structured event log helper at INFO level."""
	var payload = data.duplicate()
	payload["event"] = event
	log_info(category, event, payload)

func log_event_warning(category: Category, event: String, data: Dictionary = {}):
	"""Structured event log helper at WARNING level."""
	var payload = data.duplicate()
	payload["event"] = event
	log_warning(category, event, payload)

func log_event_error(category: Category, event: String, data: Dictionary = {}):
	"""Structured event log helper at ERROR level."""
	var payload = data.duplicate()
	payload["event"] = event
	log_error(category, event, payload)

# ============================================================================
# SINGLETON ACCESS HELPER - Get singleton instance
# ============================================================================
static func get_instance() -> Node:
	"""
	Get the DebugLogger singleton instance.
	Use this when class_name conflicts with singleton access.
	
	Returns:
		Node - DebugLogger singleton instance, or null if not found
	"""
	return Engine.get_main_loop().root.get_node_or_null("/root/AppDebugLogger")

# ============================================================================
# UTILITY METHODS - Helper functions
# ============================================================================
func get_stats() -> Dictionary:
	"""
	Get statistics about current logging configuration.
	
	Returns:
		Dictionary - Statistics with keys:
			- log_level: String - Current log level name
			- verbosity: String - Current verbosity level name
			- enabled_categories: Array - List of enabled category names
			- disabled_categories: Array - List of disabled category names
			- timestamps_enabled: bool - Whether timestamps are shown
	"""
	var enabled: Array = []  # Array: Enabled category names
	var disabled: Array = []  # Array: Disabled category names
	
	for category in Category.values():
		var category_name = Category.keys()[category]  # String: Category name
		if category_enabled.get(category, true):
			enabled.append(category_name)
		else:
			disabled.append(category_name)
	
	return {
		"log_level": LogLevel.keys()[current_log_level],
		"verbosity": VerbosityLevel.keys()[current_verbosity],
		"enabled_categories": enabled,
		"disabled_categories": disabled,
		"timestamps_enabled": show_timestamps
	}

# ============================================================================
# VERBOSITY HELPER METHODS - Check if certain outputs should be shown
# ============================================================================
func should_show_tables() -> bool:
	"""
	Check if table outputs should be shown based on verbosity level.
	Tables are only shown in VERBOSE mode.
	
	Returns:
		bool - True if tables should be shown, False otherwise
	"""
	return current_verbosity >= VerbosityLevel.VERBOSE

func should_show_verbose() -> bool:
	"""
	Check if verbose outputs should be shown based on verbosity level.
	Verbose outputs are shown in VERBOSE mode.
	
	Returns:
		bool - True if verbose outputs should be shown, False otherwise
	"""
	return current_verbosity >= VerbosityLevel.VERBOSE

func should_show_debug_details() -> bool:
	"""
	Check if debug details should be shown based on verbosity level.
	Debug details are shown in VERBOSE mode.
	
	Returns:
		bool - True if debug details should be shown, False otherwise
	"""
	return current_verbosity >= VerbosityLevel.VERBOSE

# ============================================================================
# SIMULATION TIME ACCESS - Helper for getting simulation time
# ============================================================================
func get_current_simulation_time() -> float:
	"""
	Get current simulation time if available.
	Used by timestamp formatting.
	
	Returns:
		float - Current simulation time in seconds, or 0.0 if not available
	"""
	# Try to find simulation engine if not already cached
	if simulation_engine == null:
		simulation_engine = get_node_or_null("/root/SimulationEngine")
	
	if simulation_engine != null:
		# Try to access simulation_time property directly
		if simulation_engine.has("current_simulation_time"):
			return simulation_engine.current_simulation_time
		# Or try method call
		if simulation_engine.has_method("get_current_simulation_time"):
			return simulation_engine.get_current_simulation_time()
	
	return 0.0

