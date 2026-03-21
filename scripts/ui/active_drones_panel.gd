class_name ActiveDronesPanel
extends Control

# Reference to DroneManager for accessing active drones
var drone_manager: DroneManager = null  # DroneManager reference for accessing drone data (DroneManager)

# UI components
var panel_container: VBoxContainer = null  # Main container for the panel (VBoxContainer)
var title_label: Label = null  # Title label showing "Active Drones" (Label)
var scroll_container: ScrollContainer = null  # Scrollable container for drone list (ScrollContainer)
var drone_list_container: VBoxContainer = null  # Container for individual drone entries (VBoxContainer)

# Style configuration
var panel_width: int = 250  # Width of the panel in pixels (int)
var panel_padding: int = 10  # Padding around panel content in pixels (int)
var title_font_size: int = 18  # Font size for title label in pixels (int)
var drone_entry_font_size: int = 14  # Font size for drone entries in pixels (int)
var max_displayed_drones: int = 20  # Maximum number of drones to display before scrolling (int)

# Update throttling
var update_timer: float = 0.0  # Timer for throttling updates in seconds (float)
var update_interval: float = 0.1  # Update interval in seconds (0.1 = 10 updates per second) (float)
var last_active_drone_ids: Array = []  # Array of drone IDs from last update for change detection (Array of String)

func _ready():
	"""
	Initialize the active drones panel UI components
	Sets up the panel layout, styling, and positioning on the left side of the screen
	"""
	setup_panel()

func setup_panel():
	"""
	Create and configure the panel UI elements
	Sets up the panel container, title, scroll container, and drone list
	"""
	# Set panel anchor to left side of screen, positioned from middle to bottom
	anchor_left = 0.0  # Anchor to left edge (float)
	anchor_right = 0.0  # Anchor to left edge (float)
	anchor_top = 0.5  # Anchor to middle of screen (50% from top) (float)
	anchor_bottom = 1.0  # Anchor to bottom edge (float)
	offset_left = 0  # Left offset in pixels (int)
	offset_right = panel_width  # Right offset sets panel width (int)
	offset_top = 0  # Top offset in pixels (int) - starts at middle of screen
	offset_bottom = 0  # Bottom offset in pixels (int)
	
	# Ensure Control fills its area
	size_flags_horizontal = Control.SIZE_EXPAND_FILL  # Expand to fill horizontal space (enum)
	size_flags_vertical = Control.SIZE_EXPAND_FILL  # Expand to fill vertical space (enum)
	
	# Create main container with vertical layout
	panel_container = VBoxContainer.new()
	# Set anchors to fill parent Control
	panel_container.set_anchors_preset(Control.PRESET_FULL_RECT)  # Set anchors to fill parent (void)
	panel_container.size_flags_horizontal = Control.SIZE_EXPAND_FILL  # Expand to fill horizontal space (enum)
	panel_container.size_flags_vertical = Control.SIZE_EXPAND_FILL  # Expand to fill vertical space (enum)
	add_child(panel_container)  # Add container to panel
	
	# Create title label
	title_label = Label.new()
	title_label.text = "Active Drones"  # Set title text (str)
	title_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER  # Center align text (enum)
	title_label.add_theme_font_size_override("font_size", title_font_size)  # Set title font size (int)
	title_label.add_theme_color_override("font_color", Color.WHITE)  # Set text color to white for visibility (Color)
	title_label.add_theme_color_override("font_shadow_color", Color.BLACK)  # Set shadow color for contrast (Color)
	panel_container.add_child(title_label)  # Add title to container
	
	# Create scroll container for drone list
	scroll_container = ScrollContainer.new()
	scroll_container.size_flags_horizontal = Control.SIZE_EXPAND_FILL  # Expand to fill horizontal space (enum)
	scroll_container.size_flags_vertical = Control.SIZE_EXPAND_FILL  # Expand to fill vertical space (enum)
	scroll_container.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED  # Disable horizontal scrolling (enum)
	scroll_container.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_SHOW_ALWAYS  # Always show vertical scrollbar (enum)
	# Set minimum size to ensure ScrollContainer has height
	scroll_container.custom_minimum_size = Vector2(0, 100)  # Minimum height to ensure visibility (Vector2)
	panel_container.add_child(scroll_container)  # Add scroll container to panel
	
	# Create container for drone entries inside scroll container
	drone_list_container = VBoxContainer.new()
	drone_list_container.size_flags_horizontal = Control.SIZE_EXPAND_FILL  # Expand to fill horizontal space (enum)
	# Note: Do NOT set vertical size flags - container should size to content for scrolling
	# Set minimum width to match ScrollContainer width for proper layout
	drone_list_container.custom_minimum_size = Vector2(panel_width - 20, 0)  # Minimum width accounting for scrollbar (Vector2)
	scroll_container.add_child(drone_list_container)  # Add drone list container to scroll container
	
	# Add a test entry to verify UI structure (will be removed on first update)
	await get_tree().process_frame  # Wait one frame for layout to settle (void)
	add_test_entry()  # Add test entry to verify UI works (void)

func add_test_entry():
	"""
	Add a test entry to verify the UI structure is working
	This will be removed when real drone data is available
	"""
	if drone_list_container == null:
		return  # Exit if container not ready (void)
	var test_container = HBoxContainer.new()
	test_container.name = "TestEntry"  # Set test entry name (str)
	test_container.custom_minimum_size = Vector2(0, 20)  # Set minimum height (Vector2)
	
	var test_label = Label.new()
	test_label.text = "TEST"  # Set test text (str)
	test_label.add_theme_color_override("font_color", Color.YELLOW)  # Yellow for visibility (Color)
	test_label.custom_minimum_size = Vector2(120, 20)  # Set minimum size (Vector2)
	test_container.add_child(test_label)  # Add test label
	
	var test_time = Label.new()
	test_time.text = "0.00 s"  # Set test time (str)
	test_time.add_theme_color_override("font_color", Color.YELLOW)  # Yellow for visibility (Color)
	test_time.custom_minimum_size = Vector2(100, 20)  # Set minimum size (Vector2)
	test_container.add_child(test_time)  # Add test time label
	
	drone_list_container.add_child(test_container)  # Add test entry to container

func set_drone_manager(manager: DroneManager):
	"""
	Set the DroneManager reference for accessing drone data
	
	Args:
		manager: DroneManager - Reference to the DroneManager instance
	"""
	drone_manager = manager  # Store DroneManager reference (DroneManager)
	# Remove test entry if it exists
	var test_entry = drone_list_container.get_node_or_null("TestEntry")  # Get test entry if exists (Node or null)
	if test_entry != null:
		drone_list_container.remove_child(test_entry)  # Remove test entry (void)
		test_entry.queue_free()  # Queue test entry for deletion (void)
	# Update immediately when manager is set
	update_timer = update_interval  # Set timer to trigger immediate update (float)
	update_drone_list()  # Update drone list display immediately (void)

func update_drone_list():
	"""
	Update the displayed list of active drones with their first waypoint times
	Queries DroneManager for active drones and updates the UI accordingly
	"""
	if drone_manager == null:
		return  # Exit early if DroneManager not set
	
	# Get all drones from DroneManager
	var all_drones = drone_manager.get_all_drones()  # Dictionary of all drones (Dictionary: str -> Drone)
	var active_drones: Array = []  # Array to store active drone references (Array of Drone)
	var current_active_ids: Array = []  # Array of current active drone IDs for change detection (Array of String)
	
	# Filter for active drones (not completed, not waiting for route response, has route)
	for drone_id in all_drones.keys():
		var drone = all_drones[drone_id]  # Get drone reference (Drone)
		if drone != null:
			# Check if drone is active: not completed, not waiting for route, has a route
			# A drone is considered active if it has a route and is not waiting/completed
			var has_route: bool = drone.route != null and drone.route.size() > 0  # Check if drone has a route (bool)
			var has_valid_time: bool = drone.first_waypoint_time >= 0.0  # Check if first waypoint time is valid (bool)
			# Drone is active if: not completed, not waiting, has route, and (has valid time OR is already moving)
			var is_moving: bool = drone.current_speed > 0.1  # Check if drone is moving (threshold: 0.1 m/s) (bool)
			var is_active: bool = not drone.completed and not drone.waiting_for_route_response and has_route and (has_valid_time or is_moving)  # Check if drone is active (bool)
			
			if is_active:
				active_drones.append(drone)  # Add active drone to array (Drone)
				current_active_ids.append(drone_id)  # Add drone ID to current list (String)
	
	# Sort active drones by first waypoint time (earliest first)
	active_drones.sort_custom(func(a: Drone, b: Drone) -> bool:
		return a.first_waypoint_time < b.first_waypoint_time
	)
	
	# Check if the list has changed - update UI if drones changed OR if we have active drones (to update times)
	var ids_changed: bool = current_active_ids.size() != last_active_drone_ids.size()  # Check if count changed (bool)
	if not ids_changed:
		# Check if IDs are different
		for id in current_active_ids:
			if not id in last_active_drone_ids:
				ids_changed = true  # Found new ID (bool)
				break
	
	# Always update UI if we have active drones (to refresh times), or if the list changed
	# This ensures times are updated even if the drone list hasn't changed
	if not ids_changed and active_drones.size() == 0:
		return  # Exit early only if no active drones and no changes
	
	# Clear existing drone entries (remove and free immediately)
	var children_to_remove = drone_list_container.get_children()  # Get list of children to remove (Array)
	for child in children_to_remove:
		drone_list_container.remove_child(child)  # Remove child from container (void)
		child.queue_free()  # Queue child for deletion (void)
	
	# Create UI entries for each active drone
	for drone in active_drones:
		create_drone_entry(drone)  # Create UI entry for drone (void)
	
	# Update ScrollContainer content size to ensure scrolling works
	if drone_list_container.get_child_count() > 0:
		# Force update of container size and layout
		drone_list_container.queue_sort()  # Queue layout update (void)
		drone_list_container.update_minimum_size()  # Update minimum size based on children (void)
		# Ensure ScrollContainer updates its size
		scroll_container.queue_sort()  # Queue ScrollContainer layout update (void)
		scroll_container.update_minimum_size()  # Update ScrollContainer minimum size (void)
		# Ensure panel container updates
		panel_container.queue_sort()  # Queue panel container layout update (void)
	
	# Store current IDs for next comparison
	last_active_drone_ids = current_active_ids.duplicate()  # Copy current IDs for next update (Array)

func create_drone_entry(drone: Drone):
	"""
	Create a UI entry displaying a single active drone's information
	
	Args:
		drone: Drone - The drone object to display information for
	"""
	# Create container for this drone entry
	var entry_container = HBoxContainer.new()
	entry_container.size_flags_horizontal = Control.SIZE_EXPAND_FILL  # Expand to fill horizontal space (enum)
	entry_container.custom_minimum_size = Vector2(0, 20)  # Set minimum height for entry (Vector2)
	drone_list_container.add_child(entry_container)  # Add entry to drone list container
	
	# Create label for drone ID
	var drone_id_label = Label.new()
	drone_id_label.text = drone.drone_id  # Set drone ID text (str)
	drone_id_label.add_theme_font_size_override("font_size", drone_entry_font_size)  # Set font size (int)
	drone_id_label.add_theme_color_override("font_color", Color.WHITE)  # Set text color to white for visibility (Color)
	drone_id_label.custom_minimum_size = Vector2(120, 20)  # Set minimum width and height for consistent layout (Vector2)
	drone_id_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL  # Expand to fill available space (enum)
	entry_container.add_child(drone_id_label)  # Add drone ID label to entry
	
	# Create label for first waypoint time
	var time_label = Label.new()
	# Format time as "XXX.XX s" with 2 decimal places
	time_label.text = "%.2f s" % drone.first_waypoint_time  # Set formatted time text (str)
	time_label.add_theme_font_size_override("font_size", drone_entry_font_size)  # Set font size (int)
	time_label.add_theme_color_override("font_color", Color.WHITE)  # Set text color to white for visibility (Color)
	time_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT  # Right align time text (enum)
	time_label.custom_minimum_size = Vector2(100, 20)  # Set minimum width and height for consistent layout (Vector2)
	entry_container.add_child(time_label)  # Add time label to entry

func _process(delta: float):
	"""
	Update the drone list periodically to reflect current active drones
	Called automatically by Godot's process loop
	
	Args:
		delta: float - Time elapsed since last frame in seconds
	"""
	if drone_manager == null:
		return  # Exit early if DroneManager not set
	
	# Throttle updates to avoid excessive UI recreation
	update_timer += delta  # Accumulate time since last update (float)
	if update_timer >= update_interval:
		update_timer = 0.0  # Reset timer (float)
		update_drone_list()  # Update drone list display (void)
