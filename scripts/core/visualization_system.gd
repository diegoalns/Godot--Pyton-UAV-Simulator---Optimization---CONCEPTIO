class_name VisualizationSystem
extends Node3D

var drone_meshes: Dictionary = {}  # Dictionary mapping drone_id (str) to visual Node3D nodes
var drone_labels: Dictionary = {}  # Dictionary mapping drone_id (str) to Label3D nodes for displaying drone information
var route_lines: Dictionary = {}  # Dictionary mapping drone_id (str) to MeshInstance3D nodes for route visualization
var route_colors: Dictionary = {}  # Dictionary mapping drone_id (str) to Color for route line color
var enabled: bool = true
var balloon_ref: CharacterBody3D = null  # Reference to the balloon

# Terrain system components
var terrain_gridmap: GridMap = null  # GridMap node for terrain visualization
var gridmap_manager: GridMapManager = null  # Manager for terrain data and population

# Movement and control variables
var move_speed = 30000.0  # Speed for movement
var rotation_speed = 0.001  # Speed of rotation with mouse
var mouse_sensitivity = 0.001
var camera_offset = Vector3(0, 5, 0)  # Offset from balloon position - slightly above center for better view
var mouse_captured = false

# Camera settings
var camera_fov = 90.0  # Field of view in degrees - adjustable for different viewing preferences (size: 1 float, range typically 30-120 degrees)
var camera_near_plane = 0.1  # Near clipping plane distance - objects closer than this won't render (size: 1 float in meters)
var camera_far_plane = 100000.0  # Far clipping plane distance - objects farther than this won't render (size: 1 float in meters)

# Environment settings - Realistic daytime aerial simulation colors
var sky_color_top = Color(0.3, 0.7, 1.0)  # Deep blue sky at zenith (size: Color with RGBA values)
var sky_color_horizon = Color(0.2, 0.2, 0.8)  # Light blue/white at horizon for realistic atmosphere (size: Color with RGBA values)
var ground_color = Color(0.2, 0.2, 0.2)  # Natural brown/tan earth color (size: Color with RGBA values)0.5, 0.4, 0.25
var sun_elevation_degrees = 230.0  # Sun elevation angle in degrees above horizon - 90° = apogee (directly overhead) (size: 1 float, 0-90 degrees)
var sun_azimuth_degrees = 0.0  # Sun azimuth angle in degrees - not relevant when sun is at apogee (size: 1 float, 0-360 degrees)

# Visualization scale factor
var visual_scale = 1  # Adjust this to make the area more compact

# align_drone_to_route: bool - whether to rotate the drone visual to face its next waypoint (size: 1 boolean)
var align_drone_to_route: bool = true

# model_yaw_offset_degrees: float - additional yaw angle to correct the model's intrinsic forward axis if it is not -Z (size: 1 scalar in degrees)
var model_yaw_offset_degrees: float = 0.0

var logger_instance: Node = null

func _log_info(event: String, data: Dictionary = {}):
	if logger_instance:
		logger_instance.log_event_info(DebugLogger.Category.VISUALIZATION, event, data)
	else:
		DebugLogger.print_table_row_fallback("INFO", "VISUALIZATION", event, data)

func _log_warning(event: String, data: Dictionary = {}):
	if logger_instance:
		logger_instance.log_event_warning(DebugLogger.Category.VISUALIZATION, event, data)
	else:
		DebugLogger.print_table_row_fallback("WARNING", "VISUALIZATION", event, data)

func _log_error(event: String, data: Dictionary = {}):
	if logger_instance:
		logger_instance.log_event_error(DebugLogger.Category.VISUALIZATION, event, data)
	else:
		DebugLogger.print_table_row_fallback("ERROR", "VISUALIZATION", event, data)

# Drone label configuration
var show_drone_labels: bool = true  # bool: Whether to display labels above drones (default: true)
var label_offset_height: float = 50.0  # float: Vertical offset in meters above drone for label positioning (size: 1 float in meters, reduced from 200.0 for better visibility)
var label_font_size: int = 32  # int: Font size for drone labels in pixels (size: 1 int, increased from 24 for better readability)
var label_pixel_size: float = 1  # float: Pixel size for 3D text scaling - controls label size in 3D space (size: 1 float, increased from 0.001 for better visibility)
var label_billboard_mode: BaseMaterial3D.BillboardMode = BaseMaterial3D.BILLBOARD_ENABLED  # BaseMaterial3D.BillboardMode: Billboard mode - labels always face camera (enum)

# Route line configuration
var route_line_width: float = 5.0  # float: Width of route lines in meters (size: 1 float)
var route_line_opacity: float = 0.7  # float: Opacity of route lines (0.0-1.0) (size: 1 float)

# Collision marker configuration
var collision_markers: Array = []  # Array of collision marker dictionaries - persistent markers for collision locations
var show_collision_markers: bool = true  # bool: Whether to display collision markers (default: true)
var collision_marker_size: float = 10.0  # float: Size of collision markers in meters (size: 1 float)
var collision_marker_color: Color = Color(1.0, 0.65, 0.0, 0.8)  # Color: Orange/yellow color for collision markers (Color with RGBA)
var collision_marker_container: Node3D = null  # Node3D: Container node for all collision markers

func set_enabled(enable: bool):
	enabled = enable
	visible = enable

func set_camera_fov(fov_degrees: float):
	"""
	Set the camera field of view in degrees
	@param fov_degrees: float - Field of view in degrees (typically 30-120 degrees)
	"""
	# Clamp FOV to reasonable range to prevent visual distortion
	camera_fov = clamp(fov_degrees, 30.0, 150.0)
	
	# Update the camera if it exists
	if balloon_ref and balloon_ref.get_child_count() > 0:
		# Find the camera child node
		for child in balloon_ref.get_children():
			if child is Camera3D:
				var camera = child as Camera3D
				camera.fov = camera_fov
				#print("Camera FOV updated to: %s degrees" % camera_fov)
				break

func set_camera_clipping_planes(near_distance: float, far_distance: float):
	"""
	Set the camera clipping planes to handle different viewing distances
	@param near_distance: float - Near clipping plane distance in meters
	@param far_distance: float - Far clipping plane distance in meters
	"""
	# Update the stored values with reasonable limits
	camera_near_plane = clamp(near_distance, 0.01, 10.0)  # Near plane shouldn't be too close or too far
	camera_far_plane = clamp(far_distance, 100.0, 1000000.0)  # Far plane should handle large distances
	
	# Update the camera if it exists
	if balloon_ref and balloon_ref.get_child_count() > 0:
		# Find the camera child node
		for child in balloon_ref.get_children():
			if child is Camera3D:
				var camera = child as Camera3D
				camera.near = camera_near_plane
				camera.far = camera_far_plane
				#print("Camera clipping planes updated - Near: %s, Far: %s" % [camera_near_plane, camera_far_plane])
				break

func _ready():
	logger_instance = DebugLogger.get_instance()
	setup_balloon()
	setup_camera()
	setup_lighting()      # Create DirectionalLight3D first
	setup_environment()   # Then create sky environment - it will sync with the light
	setup_ground()
	setup_terrain()
	setup_collision_markers()
	
	# Set up input processing
	set_process_input(true)
	set_process(true)

func setup_camera():
	# camera: Camera3D - main camera node for the visualization system (size: one Camera3D reference)
	var camera = Camera3D.new()
	# Set camera position with scaled offset from balloon center
	camera.position = camera_offset * visual_scale  # Set the local offset, scaled
	# Set field of view using the configurable camera_fov variable
	camera.fov = camera_fov  # Use configurable field of view setting
	# Configure clipping planes to handle large distances and prevent rendering issues
	camera.near = camera_near_plane  # Set near clipping plane for close objects
	camera.far = camera_far_plane   # Set far clipping plane for distant terrain and objects
	# Reset camera rotation to look forward (default orientation looks down the -Z axis)
	camera.rotation = Vector3.ZERO  # Ensure camera looks forward, not down
	# Make this the active camera
	camera.current = true
	# Attach camera as child of balloon so it moves with the balloon
	balloon_ref.add_child(camera)    # Attach camera to the balloon

func setup_environment():
	"""
	Set up the sky environment with blue gradient background
	Creates a sky dome with proper colors for realistic aerial simulation
	NOTE: This function must be called AFTER setup_lighting() so that the 
	ProceduralSkyMaterial can sync its sun disk with the DirectionalLight3D
	The sun position is automatically controlled by the DirectionalLight3D when
	its sky_mode is set to SKY_MODE_LIGHT_AND_SKY
	"""
	#print("VisualizationSystem: Setting up sky environment...")
	
	# Create environment resource for the scene
	var environment = Environment.new()
	
	# Set background mode to sky
	environment.background_mode = Environment.BG_SKY
	
	# Create sky resource
	var sky = Sky.new()
	
	# Create procedural sky material with proper configuration
	var sky_material = ProceduralSkyMaterial.new()
	
	# Configure sky colors for realistic aerial view
	sky_material.sky_top_color = sky_color_top  # Deep blue at zenith
	sky_material.sky_horizon_color = sky_color_horizon  # Lighter blue at horizon
	sky_material.ground_bottom_color = ground_color  # Brown ground color
	sky_material.ground_horizon_color = ground_color.lightened(1)  # Slightly lighter brown at horizon
	
	# Configure sky gradient curves for proper visibility (valid ProceduralSkyMaterial properties)
	sky_material.sky_curve = 0.25  # Sky gradient curve - controls how quickly sky color changes with altitude
	sky_material.ground_curve = 0.02  # Ground gradient curve - controls ground color blending
	
	# DISABLE the built-in sun in ProceduralSkyMaterial - we want only our DirectionalLight3D
	sky_material.sun_angle_max = 15.0  # Set sun disk size to 0 to make it invisible
	sky_material.sun_curve = 0.9      # Set sun intensity to 0 to disable it completely
	
	# Configure sun position to match directional light at apogee (directly overhead)
	# In Godot 4, the ProceduralSkyMaterial automatically syncs with DirectionalLight3D
	# when the light's sky_mode is set to SKY_MODE_LIGHT_AND_SKY
	# No manual sun positioning needed - the DirectionalLight3D controls everything
	
	# Apply the sky material to the sky resource
	sky.sky_material = sky_material
	
	# Apply the sky to the environment
	environment.sky = sky
	
	# Set ambient lighting from sky
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	environment.ambient_light_energy = 0.4  # Slightly brighter ambient lighting for better visibility
	
	# Sky brightness is controlled by the sky material itself and ambient lighting
	
	# Apply environment to the scene using WorldEnvironment node (proper Godot 4 method)
	var world_environment = WorldEnvironment.new()
	world_environment.name = "WorldEnvironment"
	world_environment.environment = environment
	add_child(world_environment)
	
	#print("VisualizationSystem: Sky environment setup complete - Sky colors: top=%s, horizon=%s" % [sky_color_top, sky_color_horizon])

func setup_lighting():
	"""
	Set up directional lighting to simulate the sun at specified elevation and azimuth
	Creates realistic lighting for aerial simulation with proper shadows
	NOTE: This function must be called BEFORE setup_environment() so that the
	DirectionalLight3D can control the sun disk position in the ProceduralSkyMaterial
	"""
	if logger_instance:
		logger_instance.print_table_line("INFO", "VISUALIZATION", "setup_sun_lighting", {})
	
	# First, remove any existing DirectionalLight3D nodes to prevent conflicts
	for child in get_children():
		if child is DirectionalLight3D:
			if logger_instance:
				logger_instance.print_table_line("INFO", "VISUALIZATION", "removing_directional_light", {"child": child.name})
			child.queue_free()
	
	# Create directional light to simulate the sun
	var sun_light = DirectionalLight3D.new()
	sun_light.name = "SunLight"
	
	# Calculate sun position based on elevation and azimuth angles
	# elevation_rad: float - sun elevation in radians (size: 1 float)
	var elevation_rad = deg_to_rad(sun_elevation_degrees)
	# azimuth_rad: float - sun azimuth in radians (size: 1 float)  
	var azimuth_rad = deg_to_rad(sun_azimuth_degrees)
	
	# For apogee (90° elevation), sun is directly overhead pointing straight down
	# sun_direction: Vector3 - normalized direction vector pointing toward sun (size: 3 floats)
	var sun_direction: Vector3
	
	if sun_elevation_degrees >= 89.0:
		# Sun at apogee - directly overhead, pointing straight down
		sun_direction = Vector3(0, 1, 0)  # Pointing straight up (sun position)
	else:
		# Calculate sun direction from spherical coordinates for other elevations
		sun_direction = Vector3(
			cos(elevation_rad) * sin(azimuth_rad),  # X component
			sin(elevation_rad),                     # Y component (elevation)
			cos(elevation_rad) * cos(azimuth_rad)   # Z component
		)
	
	# Position the light high above the scene
	sun_light.position = Vector3(0, 10000, 0) * visual_scale
	
	# Orient before add_child — Node3D.look_at requires the node to be in the tree; use look_at_from_position instead
	if sun_elevation_degrees >= 89.0:
		sun_light.look_at_from_position(sun_light.position, Vector3(0, 0, 0), Vector3.FORWARD)
	else:
		var sun_target = sun_light.position - sun_direction * 1000
		sun_light.look_at_from_position(sun_light.position, sun_target, Vector3.UP)
	
	# Configure light properties for realistic sun lighting
	sun_light.light_energy = 1  # Natural sun intensity - not too bright
	sun_light.light_color = Color(1.0, 0.98, 0.9)  # Natural warm sunlight color
	
	# CRITICAL: Set sky_mode to control both scene lighting AND sky sun position
	sun_light.sky_mode = DirectionalLight3D.SKY_MODE_LIGHT_AND_SKY  # This makes the sun disk follow the light direction
	
	# Enable shadows for realistic terrain and object shading
	sun_light.shadow_enabled = true
	sun_light.directional_shadow_mode = DirectionalLight3D.SHADOW_ORTHOGONAL
	sun_light.directional_shadow_max_distance = 50000.0 * visual_scale  # Long shadow distance for aerial view
	sun_light.rotation.x = deg_to_rad(sun_elevation_degrees)
	# Add the sun light to the scene
	add_child(sun_light)
	
	if logger_instance:
		logger_instance.print_table_line("INFO", "VISUALIZATION", "sun_positioned", {"elevation": sun_elevation_degrees, "azimuth": sun_azimuth_degrees, "position": str(sun_light.position), "sky_mode": sun_light.sky_mode})

func setup_ground():
	"""
	Create a large brown ground plane to serve as the base terrain
	Provides a consistent brown surface beneath the detailed terrain data
	"""
	#print("VisualizationSystem: Setting up ground plane...")
	
	# Create a large ground plane mesh
	var ground_mesh_instance = MeshInstance3D.new()
	ground_mesh_instance.name = "GroundPlane"
	
	# Create a large plane mesh for the ground (size in meters scaled by visual_scale)
	var plane_mesh = PlaneMesh.new()
	plane_mesh.size = Vector2(2000, 2000) * visual_scale  # Very large ground plane (200km x 200km)
	plane_mesh.subdivide_width = 10 # Some subdivision for potential detail
	plane_mesh.subdivide_depth = 1000
	
	# Create brown material for the ground
	var ground_material = StandardMaterial3D.new()
	ground_material.albedo_color = ground_color  # Brown color
	ground_material.roughness = 0.8  # Rough surface like dirt/soil
	ground_material.metallic = 0.1   # Non-metallic surface
	
	# Apply material and mesh to the instance
	ground_mesh_instance.mesh = plane_mesh
	ground_mesh_instance.material_override = ground_material
	
	# Position the ground plane at ground level (Y=0)
	ground_mesh_instance.position = Vector3(0, 0, 0)
	
	# Add to the scene
	add_child(ground_mesh_instance)
	
	#print("VisualizationSystem: Ground plane setup complete")

func setup_terrain():
	"""
	Initialize the terrain GridMap system within the visualization system
	Creates GridMap and GridMapManager, loads terrain data, and scales appropriately
	"""
	#print("VisualizationSystem: Setting up terrain system...")
	
	# Create GridMap node for terrain visualization
	terrain_gridmap = GridMap.new()
	terrain_gridmap.name = "TerrainGridMap"
	
	# Load the mesh library resource
	var mesh_library = load("res://resources/Meshs/cell_library.meshlib")
	if not mesh_library:
		_log_error("terrain_mesh_library_load_failed", {"resource": "res://resources/Meshs/cell_library.meshlib"})
		return
	
	# Configure GridMap with mesh library and proper cell size
	terrain_gridmap.mesh_library = mesh_library
	# Apply visual scale to cell size - each cell represents 702m x 927m x 1m in world space
	# Height dimension is 1m per grid unit to match CSV altitude values (0-400m range)
	terrain_gridmap.cell_size = Vector3(702.0 * visual_scale, 1.0 * visual_scale, 927.0 * visual_scale)
	
	# Add GridMap to the visualization system
	add_child(terrain_gridmap)
	
	# Create and initialize GridMapManager
	gridmap_manager = GridMapManager.new()
	add_child(gridmap_manager)
	
	# Initialize the manager with our GridMap
	gridmap_manager.initialize_gridmap(terrain_gridmap)
	
	# Load terrain data and populate the GridMap
	if gridmap_manager.load_terrain_data():
		if gridmap_manager.populate_gridmap():
			if logger_instance:
				logger_instance.print_table_line("INFO", "VISUALIZATION", "terrain_initialized", {})
		else:
			_log_error("terrain_population_failed", {})
	else:
		_log_error("terrain_data_load_failed", {})

func setup_collision_markers():
	"""
	Initialize the collision marker container for persistent collision visualization
	Creates a Node3D container to hold all collision markers
	"""
	collision_marker_container = Node3D.new()
	collision_marker_container.name = "CollisionMarkers"
	add_child(collision_marker_container)
	if logger_instance:
		logger_instance.print_table_line("INFO", "VISUALIZATION", "collision_markers_initialized", {})

func setup_balloon():
	balloon_ref = CharacterBody3D.new()
	add_child(balloon_ref)
	
	# Set motion mode to floating (space-like movement)
	balloon_ref.motion_mode = CharacterBody3D.MOTION_MODE_FLOATING
	
	# Add collision shape
	var collision = CollisionShape3D.new()
	var shape = SphereShape3D.new()
	shape.radius = 5.0 * visual_scale
	collision.shape = shape
	balloon_ref.add_child(collision)
	
	# Set initial position at grid origin (0, 100, 0)
	balloon_ref.global_position = Vector3(3000, 1000, -22000) * visual_scale

func _input(event):
	# Toggle mouse capture with Escape key
	if event is InputEventKey and event.pressed and event.keycode == KEY_ESCAPE:
		if mouse_captured:
			Input.set_mouse_mode(Input.MOUSE_MODE_VISIBLE)
			mouse_captured = false
		else:
			Input.set_mouse_mode(Input.MOUSE_MODE_CAPTURED)
			mouse_captured = true
	
	# Handle mouse rotation when captured
	if mouse_captured and event is InputEventMouseMotion:
		# Rotate balloon based on mouse movement
		var rotation_y = -event.relative.x * mouse_sensitivity
		var rotation_x = -event.relative.y * mouse_sensitivity
		
		# Apply rotation to balloon - rotate around global Y axis for left/right
		balloon_ref.rotate(Vector3.UP, rotation_y)
		
		# For up/down, rotate around local X axis
		var local_x = balloon_ref.global_transform.basis.x
		balloon_ref.rotate(local_x, rotation_x)

	# Add roll control with Q and E keys
	if mouse_captured and event is InputEventKey and event.pressed:
		if event.keycode == KEY_Q:
			# Roll left
			balloon_ref.rotate(balloon_ref.global_transform.basis.z, 0.05)
		elif event.keycode == KEY_E:
			# Roll right
			balloon_ref.rotate(balloon_ref.global_transform.basis.z, -0.05)

func _process(_delta):
	pass

func _physics_process(delta):
	if balloon_ref and mouse_captured:
		# Get input direction
		var input_dir = Vector3.ZERO
		
		# WASD movement: W=forward(-Z), S=backward(+Z), A=left(-X), D=right(+X)
		if Input.is_key_pressed(KEY_W):
			input_dir.z -= 1  # Move forward (negative Z direction)
		if Input.is_key_pressed(KEY_S):
			input_dir.z += 1  # Move backward (positive Z direction)
		if Input.is_key_pressed(KEY_A):
			input_dir.x -= 1  # Move left (negative X direction)
		if Input.is_key_pressed(KEY_D):
			input_dir.x += 1  # Move right (positive X direction)
		# Vertical movement: C=up(+Y), SHIFT=down(-Y)
		if Input.is_key_pressed(KEY_C):
			input_dir.y += 1  # Move up (positive Y direction)
		if Input.is_key_pressed(KEY_SHIFT):
			input_dir.y -= 1  # Move down (negative Y direction)
			
		# Convert input direction to global space relative to balloon's orientation
		var direction = balloon_ref.global_transform.basis * input_dir
		
		# Set velocity directly instead of applying forces
		if direction.length() > 0:
			balloon_ref.velocity = direction.normalized() * move_speed * delta
		else:
			# Optional: add some dampening when no input is given
			balloon_ref.velocity = balloon_ref.velocity.lerp(Vector3.ZERO, 0.1)
		
		# Move the character body
		balloon_ref.move_and_slide()

func add_drone(drone: Drone):
	if not enabled:
		return
	
	# drone_node: Node3D - the visual representation of the drone
	var drone_node: Node3D = null
	# lrvtol_scene: PackedScene - LRVTOL model from resources
	var lrvtol_scene: PackedScene = load("res://resources/LRVTOL_UAV.glb")

	# If the model loads, instance it; otherwise use a simple box as fallback
	if lrvtol_scene:
		# instance: Node - instantiated GLB root
		var instance = lrvtol_scene.instantiate()
		if instance is Node3D:
			drone_node = instance
			# Scale down to match map visual scale
			drone_node.scale = Vector3(1, 1, 1) * visual_scale
		else:
			# Wrap non-Node3D roots under a Node3D so it can be positioned
			drone_node = Node3D.new()
			drone_node.add_child(instance)
			drone_node.scale = Vector3(1, 1, 1) * visual_scale
	else:
		# Fallback: simple colored box
		var fallback = MeshInstance3D.new()
		var box_mesh = BoxMesh.new()
		box_mesh.size = Vector3(100, 10, 100) * visual_scale
		fallback.mesh = box_mesh
		var material = StandardMaterial3D.new()
		material.albedo_color = Color(randf(), randf(), randf())
		box_mesh.material = material
		drone_node = fallback

	add_child(drone_node)
	drone_meshes[drone.drone_id] = drone_node

	# Create Label3D for displaying drone information above the drone
	if show_drone_labels:
		# label_node: Label3D - 3D text label node for displaying drone information (size: one Label3D reference)
		var label_node = Label3D.new()
		label_node.name = "DroneLabel_" + drone.drone_id  # Set unique name for debugging (str)
		
		# Configure label text - display drone ID and model type
		var label_text: String = drone.drone_id  # String: Label text showing drone ID
		if drone.model != "":
			label_text += "\n" + drone.model  # Append model type on second line if available (str)
		label_node.text = label_text  # Set the label text content (str)
		
		# Configure label appearance
		label_node.font_size = label_font_size  # Set font size in pixels (int)
		label_node.billboard = label_billboard_mode  # Enable billboard mode so label always faces camera (BaseMaterial3D.BillboardMode enum)
		label_node.modulate = Color.WHITE  # Set label color to white for visibility (Color)
		label_node.outline_modulate = Color.BLACK  # Set outline color to black for text contrast (Color)
		label_node.outline_size = 48  # Set outline size in pixels for better readability (int, increased from 8)
		label_node.pixel_size = label_pixel_size  # Set pixel size for 3D text scaling - larger value makes text bigger in 3D space (float)
		label_node.no_depth_test = true  # Disable depth testing so labels are always visible even if objects are in front (bool)
		label_node.shaded = false  # Disable shading so labels remain bright and visible (bool)
		label_node.visible = true  # Ensure label is visible (bool)
		
		# Position label above the drone (offset on Y axis)
		label_node.position = Vector3(0, label_offset_height * visual_scale, 0)  # Position label above drone (Vector3 of 3 floats)
		
		# Add label as child of drone visual node so it moves with the drone
		drone_node.add_child(label_node)  # Attach label to drone visual node
		drone_labels[drone.drone_id] = label_node  # Store label reference in dictionary for later updates (dict entry: str -> Label3D)
		
		if logger_instance:
			logger_instance.print_table_line("INFO", "VISUALIZATION", "drone_label_created", {"drone_id": drone.drone_id, "offset_y": label_offset_height * visual_scale})
	
	#print("Added visualization for drone %s" % drone.drone_id)

func remove_drone(drone: Drone):
	"""
	Remove a drone's visual representation from the visualization system
	
	Args:
		drone: The Drone object whose visualization should be removed
	"""
	if not enabled:
		return
	
	# Check if this drone has a visual representation
	var had_visualization: bool = drone_meshes.has(drone.drone_id) or drone_labels.has(drone.drone_id)  # bool: Track if drone had any visualization
	
	if drone_meshes.has(drone.drone_id):
		# drone_node: Node3D - the visual node to be removed (size: one node reference)
		var drone_node = drone_meshes[drone.drone_id]
		drone_node.queue_free()  # Remove the visual node from the scene tree (label is child, so it will be removed automatically)
		drone_meshes.erase(drone.drone_id)  # Remove the reference from the dictionary (dict entry: str -> Node3D)
	
	# Remove label reference if it exists (label is child of drone_node, so it's already freed, but clean up dictionary)
	if drone_labels.has(drone.drone_id):
		drone_labels.erase(drone.drone_id)  # Remove label reference from dictionary (dict entry: str -> Label3D)
	
	# Remove route line if it exists
	if route_lines.has(drone.drone_id):
		var route_line = route_lines[drone.drone_id]
		route_line.queue_free()  # Remove route line mesh from scene tree
		route_lines.erase(drone.drone_id)  # Remove route line reference from dictionary (dict entry: str -> MeshInstance3D)
	
	# Remove route color reference
	if route_colors.has(drone.drone_id):
		route_colors.erase(drone.drone_id)  # Remove color reference from dictionary (dict entry: str -> Color)
	
	if had_visualization and logger_instance:
		logger_instance.print_table_line("INFO", "VISUALIZATION", "drone_visualization_removed", {"drone_id": drone.drone_id})

func update_drone_position(drone: Drone):
	if not enabled:
		return
		
	if drone.drone_id in drone_meshes:
		# node: Node3D - visual node associated with this drone (size: one node reference)
		var node: Node3D = drone_meshes[drone.drone_id]

		# Update position: multiply by visual_scale to convert world meters to visualization units (size: Vector3 of 3 floats)
		node.position = drone.current_position * visual_scale
		
		# Update label text with current drone information (speed, status, etc.)
		if show_drone_labels and drone.drone_id in drone_labels:
			# label: Label3D - label node for this drone (size: one Label3D reference)
			var label: Label3D = drone_labels[drone.drone_id]
			
			# Build label text with drone ID, model, and current speed
			var label_text: String = drone.drone_id  # String: Base label text with drone ID
			if drone.model != "":
				label_text += "\n" + drone.model  # Append model type on second line (str)
			
			# Add current speed information if drone is moving
			if drone.current_speed > 0.1:  # Only show speed if drone is moving (threshold: 0.1 m/s)
				label_text += "\n%.1f m/s" % drone.current_speed  # Append speed on third line (str, formatted float)
			
			# Add status information if drone is waiting or completed
			if drone.is_waiting_at_waypoint:
				label_text += "\nWaiting"  # Append waiting status (str)
			elif drone.completed:
				label_text += "\nCompleted"  # Append completed status (str)
			
			label.text = label_text  # Update label text content (str)

		# Optionally orient the drone to face its next waypoint so its longitudinal axis follows the route
		if align_drone_to_route:
			# Skip orientation if drone is waiting (not moving) to avoid look_at errors
			# When waiting, current_position == target_position, causing look_at to fail
			var should_orient: bool = not drone.is_waiting_at_waypoint and drone.current_speed >= 0.01  # Check if should orient (bool)
			
			if should_orient:
				# target_pos_world: Vector3 - the next waypoint position in visualization units (size: 3 floats)
				var target_pos_world: Vector3 = drone.target_position * visual_scale

				# dir_to_target: Vector3 - direction vector from current node position to next waypoint (size: 3 floats)
				var dir_to_target: Vector3 = target_pos_world - node.position
				var dir_length: float = dir_to_target.length()  # Direction vector length (float)

				# Only orient when the direction vector has meaningful magnitude to avoid zero-length look_at
				# Also check that direction is not parallel to up vector (which causes look_at to fail)
				if dir_length > 0.0001:
					# Normalize direction for parallel check
					var dir_normalized: Vector3 = dir_to_target / dir_length  # Normalized direction vector (Vector3)
					
					# Check if direction is parallel to up vector (cross product will be zero)
					var cross_product: Vector3 = Vector3.UP.cross(dir_normalized)  # Cross product (Vector3)
					var is_parallel_to_up: bool = cross_product.length() < 0.0001  # Check if parallel (bool)
					
					if not is_parallel_to_up:
						# Safe to use look_at with UP vector
						node.look_at(target_pos_world, Vector3.UP)
					else:
						# Direction is parallel to UP - use a different up vector (FORWARD) to avoid look_at failure
						# This handles edge cases where drone is moving straight up/down
						node.look_at(target_pos_world, Vector3.FORWARD)

					# Apply extra yaw offset if the model forward axis needs correction relative to -Z
					if model_yaw_offset_degrees != 0.0:
						node.rotate_y(deg_to_rad(model_yaw_offset_degrees))

					# Ensure the visual forward actually faces the waypoint. If after applying the yaw offset
					# the model's forward points away (dot < 0), flip 180 degrees around Y to correct.
					# forward_world: Vector3 - world-space forward direction assuming -Z is forward (size: 3 floats)
					var forward_world: Vector3 = (node.global_transform.basis.z).normalized()
					# dir_norm: Vector3 - normalized desired direction towards the next waypoint (size: 3 floats)
					var dir_norm: Vector3 = dir_to_target.normalized()
					if forward_world.dot(dir_norm) < 0.0:
						node.rotate_y(PI)
		
		# Update route line visibility - show when drone is flying, hide when completed
		_update_route_line(drone)

func add_drone_port(dp_position: Vector3, port_id: String):
	var mesh_instance = MeshInstance3D.new()
	var box_mesh = BoxMesh.new()
	box_mesh.size = Vector3(500, 2, 500) * visual_scale

	var material = StandardMaterial3D.new()
	material.albedo_color = Color(0, 0, 0)  # Black
	box_mesh.material = material
	mesh_instance.mesh = box_mesh

	mesh_instance.position = dp_position * visual_scale
	add_child(mesh_instance)
	if logger_instance:
		logger_instance.print_table_line("INFO", "VISUALIZATION", "drone_port_added", {"port_id": port_id, "position": str(dp_position)})

func move_balloon_to_port(port_position: Vector3):
	# Optionally apply scale_factor if you use one
	balloon_ref.global_position = port_position * visual_scale
	# Optionally reset orientation or camera offset here

func add_collision_marker(marker_position: Vector3, drone1_id: String, drone2_id: String, distance: float, simulation_time: float):
	"""
	Add a persistent collision marker at the specified position
	Creates a visual marker that remains for the entire simulation
	
	Args:
		marker_position: Vector3 - World position where collision occurred (midpoint between drones)
		drone1_id: String - ID of first drone in collision
		drone2_id: String - ID of second drone in collision
		distance: float - Distance between drones when collision was detected
		simulation_time: float - Simulation time when collision occurred
	"""
	if not enabled or not show_collision_markers:
		return
	
	if not collision_marker_container:
		_log_warning("collision_marker_container_uninitialized", {})
		return
	
	# Create marker mesh - use a sphere for visibility
	var marker_mesh = MeshInstance3D.new()
	var sphere_mesh = SphereMesh.new()
	sphere_mesh.radius = collision_marker_size * 0.5 * visual_scale  # Half size for radius
	sphere_mesh.height = collision_marker_size * visual_scale
	marker_mesh.mesh = sphere_mesh
	
	# Create material with emissive property for visibility
	var material = StandardMaterial3D.new()
	material.albedo_color = collision_marker_color
	material.emission_enabled = true
	material.emission = collision_marker_color
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED  # Unshaded for consistent visibility
	sphere_mesh.material = material
	
	# Position marker at collision location (scaled for visualization)
	marker_mesh.position = marker_position * visual_scale
	marker_mesh.name = "CollisionMarker_%s_%s_%.1f" % [drone1_id, drone2_id, simulation_time]
	
	# Add label showing collision info (optional)
	if show_drone_labels:
		var label = Label3D.new()
		label.text = "Collision\n%s & %s\n%.1fm" % [drone1_id, drone2_id, distance]
		label.font_size = 16
		label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
		label.modulate = Color.WHITE
		label.outline_modulate = Color.BLACK
		label.outline_size = 16
		label.pixel_size = 0.5
		label.position = Vector3(0, collision_marker_size * visual_scale * 0.75, 0)
		marker_mesh.add_child(label)
	
	# Add marker to container
	collision_marker_container.add_child(marker_mesh)
	
	# Store marker metadata
	var marker_data = {
		"node": marker_mesh,
		"position": marker_position,
		"drone1_id": drone1_id,
		"drone2_id": drone2_id,
		"distance": distance,
		"simulation_time": simulation_time
	}
	collision_markers.append(marker_data)
	
	if logger_instance:
		logger_instance.print_table_line("INFO", "VISUALIZATION", "collision_marker_added", {"position": str(marker_position), "drone1": drone1_id, "drone2": drone2_id, "distance": distance})

func clear_collision_markers():
	"""
	Remove all collision markers from the visualization
	Clears both the visual nodes and the metadata array
	"""
	if collision_marker_container:
		for child in collision_marker_container.get_children():
			child.queue_free()
	collision_markers.clear()
	if logger_instance:
		logger_instance.print_table_line("INFO", "VISUALIZATION", "collision_markers_cleared", {})

func set_show_collision_markers(should_show: bool):
	"""
	Toggle visibility of collision markers
	
	Args:
		should_show: bool - Whether to show collision markers
	"""
	show_collision_markers = should_show
	if collision_marker_container:
		collision_marker_container.visible = should_show

func get_collision_marker_count() -> int:
	"""
	Get the current number of collision markers
	
	Returns:
		int - Number of collision markers
	"""
	return collision_markers.size()

func get_terrain_altitude_at_position(world_pos: Vector3) -> float:
	"""
	Get terrain altitude at a specific world position
	@param world_pos: Vector3 - World position to query (in world coordinates)
	@return float - Altitude value at that position, or -1 if terrain not ready
	"""
	if gridmap_manager:
		return gridmap_manager.get_terrain_altitude_at_position(world_pos)
	return -1.0

func get_terrain_info() -> Dictionary:
	"""
	Get terrain system information for debugging/display purposes
	@return Dictionary - Terrain information or empty dict if not ready
	"""
	if gridmap_manager:
		return gridmap_manager.get_grid_info()
	return {}

func is_terrain_ready() -> bool:
	"""
	Check if the terrain system is fully initialized and ready for use
	@return bool - True if terrain is ready, false otherwise
	"""
	return terrain_gridmap != null and gridmap_manager != null

func _generate_drone_color(drone_id: String) -> Color:
	"""
	Generate a deterministic random color for a drone based on its ID
	Ensures same drone always gets same color, but different drones get different colors
	
	Args:
		drone_id: String - Unique drone identifier
	
	Returns:
		Color - Random color for this drone (deterministic based on ID)
	"""
	# Use hash of drone_id to generate deterministic random values
	var hash_value = drone_id.hash()  # int: Hash value of drone ID
	var rng = RandomNumberGenerator.new()
	rng.seed = hash_value  # Set seed based on hash for deterministic randomness
	
	# Generate bright, saturated colors for better visibility
	var hue = rng.randf()  # Random hue (0.0-1.0)
	var saturation = 0.7 + rng.randf() * 0.3  # Saturation between 0.7-1.0 for vibrant colors
	var brightness = 0.8 + rng.randf() * 0.2  # Brightness between 0.8-1.0 for visibility
	
	# Convert HSV to RGB
	var color = Color.from_hsv(hue, saturation, brightness, route_line_opacity)
	return color

func _create_route_line_mesh(waypoints: Array, color: Color) -> MeshInstance3D:
	"""
	Create an efficient route line mesh connecting waypoints using ArrayMesh
	Creates a tube-like mesh using quads for better visibility and performance
	
	Args:
		waypoints: Array - Array of waypoint dictionaries with "position" Vector3 fields
		color: Color - Color for the route line
	
	Returns:
		MeshInstance3D - Mesh instance containing the route line
	"""
	if waypoints.size() < 2:
		return null  # Need at least 2 waypoints to draw a line
	
	# Create mesh instance
	var mesh_instance = MeshInstance3D.new()
	var array_mesh = ArrayMesh.new()
	
	# Prepare arrays for mesh data
	var vertices = PackedVector3Array()
	var normals = PackedVector3Array()
	var uvs = PackedVector2Array()
	var indices = PackedInt32Array()
	
	# Extract waypoint positions
	var positions = []
	for waypoint in waypoints:
		if waypoint is Dictionary and waypoint.has("position"):
			var pos = waypoint.position as Vector3
			positions.append(pos * visual_scale)
	
	if positions.size() < 2:
		return null
	
	# Create tube segments between waypoints
	var half_width = route_line_width * visual_scale * 0.5
	
	for i in range(positions.size() - 1):
		var start_pos = positions[i]
		var end_pos = positions[i + 1]
		var direction = (end_pos - start_pos)
		var segment_length = direction.length()
		
		if segment_length < 0.001:
			continue  # Skip zero-length segments
		
		direction = direction.normalized()
		
		# Calculate perpendicular vectors for tube cross-section
		# Use a robust method to find perpendicular vectors
		var up = Vector3.UP
		var right = direction.cross(up)
		
		# If direction is parallel to UP, use FORWARD instead
		if right.length() < 0.001:
			up = Vector3.FORWARD
			right = direction.cross(up)
		
		right = right.normalized()
		var perp_up = right.cross(direction).normalized()
		
		# Create quad vertices for this segment (4 vertices per quad)
		# Create a flat ribbon perpendicular to the direction
		var v0 = start_pos - right * half_width
		var v1 = start_pos + right * half_width
		var v2 = end_pos + right * half_width
		var v3 = end_pos - right * half_width
		
		# Add vertices
		var base_idx = vertices.size()
		vertices.append(v0)
		vertices.append(v1)
		vertices.append(v2)
		vertices.append(v3)
		
		# Add normals (pointing outward)
		var normal = perp_up
		normals.append(normal)
		normals.append(normal)
		normals.append(normal)
		normals.append(normal)
		
		# Add UVs
		uvs.append(Vector2(0, 0))
		uvs.append(Vector2(1, 0))
		uvs.append(Vector2(1, 1))
		uvs.append(Vector2(0, 1))
		
		# Add indices for quad (two triangles)
		indices.append(base_idx + 0)
		indices.append(base_idx + 1)
		indices.append(base_idx + 2)
		indices.append(base_idx + 0)
		indices.append(base_idx + 2)
		indices.append(base_idx + 3)
	
	# Create surface from arrays
	var arrays = []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = vertices
	arrays[Mesh.ARRAY_NORMAL] = normals
	arrays[Mesh.ARRAY_TEX_UV] = uvs
	arrays[Mesh.ARRAY_INDEX] = indices
	
	# Add surface to mesh
	array_mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	mesh_instance.mesh = array_mesh
	
	# Create material for the route line
	var material = StandardMaterial3D.new()
	material.albedo_color = color
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED  # Unshaded for better performance
	material.flags_unshaded = true
	material.no_depth_test = false  # Enable depth testing for proper 3D rendering
	material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA  # Enable alpha transparency
	material.albedo_color.a = route_line_opacity  # Set opacity
	material.cull_mode = BaseMaterial3D.CULL_DISABLED  # Disable culling so line is visible from all angles
	
	mesh_instance.material_override = material
	
	return mesh_instance

func _update_route_line(drone: Drone):
	"""
	Update route line visibility based on drone state
	Shows route line when drone is flying, hides when completed
	
	Args:
		drone: Drone - The drone object to update route line for
	"""
	# Check if drone has a route and is ready to fly
	var should_show_route = (
		not drone.completed and 
		not drone.waiting_for_route_response and 
		drone.route.size() >= 2
	)
	
	if should_show_route:
		# Route should be visible - create if it doesn't exist
		if not route_lines.has(drone.drone_id):
			# Generate or retrieve color for this drone
			if not route_colors.has(drone.drone_id):
				route_colors[drone.drone_id] = _generate_drone_color(drone.drone_id)
			
			var route_color = route_colors[drone.drone_id]
			
			# Create route line mesh
			var route_line = _create_route_line_mesh(drone.route, route_color)
			if route_line:
				route_line.name = "RouteLine_" + drone.drone_id
				add_child(route_line)
				route_lines[drone.drone_id] = route_line
	else:
		# Route should be hidden - remove if it exists
		if route_lines.has(drone.drone_id):
			var route_line = route_lines[drone.drone_id]
			route_line.queue_free()
			route_lines.erase(drone.drone_id)
