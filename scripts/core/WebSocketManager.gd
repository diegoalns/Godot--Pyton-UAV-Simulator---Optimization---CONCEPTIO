extends Node

# Get DebugLogger singleton instance helper
# Use logger_instance instead of DebugLogger directly to avoid class_name conflict
var logger_instance: Node = null

# Signal emitted when the WebSocket connection is successfully established
signal connected
# Signal emitted when the WebSocket connection is closed or lost
signal disconnected
# Signal emitted when data is received from the WebSocket server
signal data_received(data)

# Instance of the low-level WebSocketPeer, used for managing the WebSocket connection
var ws_peer = WebSocketPeer.new()
var default_url = "ws://localhost:8765"
var reconnect_timer = null
var is_connected = false

func _ready():
	# Autoloads run while the editor is open; avoid WebSocket I/O and extra physics work there.
	if Engine.is_editor_hint():
		set_physics_process(false)
		return

	var env_ws_url = OS.get_environment("GA_WEBSOCKET_URL")
	if env_ws_url != "":
		default_url = env_ws_url

	# Get DebugLogger singleton instance (autoload singleton)
	logger_instance = DebugLogger.get_instance()
	if logger_instance == null:
		push_error("AppDebugLogger autoload not found (scripts/core/DebugLogger.gd). Check project.godot autoloads.")
	
	if logger_instance:
		logger_instance.log_info(DebugLogger.Category.WEBSOCKET, "initializing", {"url": default_url})
	
	# Create reconnect timer
	reconnect_timer = Timer.new()
	reconnect_timer.one_shot = true
	reconnect_timer.wait_time = 3.0
	reconnect_timer.timeout.connect(_on_reconnect_timer_timeout)
	add_child(reconnect_timer)
	connect_to_server(default_url)

# Initiates a connection to the WebSocket server at the given URL
func connect_to_server(url):
	var err = ws_peer.connect_to_url(url)
	if err != OK:
		if logger_instance:
			logger_instance.log_error(DebugLogger.Category.WEBSOCKET, "Connection failed (Error: %d)" % err, {"error_code": err, "url": url})
		schedule_reconnect()
		
# Called every physics frame (100Hz) to poll WebSocket for new events and data
# Moved from _process() to _physics_process() to match simulation rate and prevent message delays
func _physics_process(_delta):
	if Engine.is_editor_hint():
		return
	ws_peer.poll()  # Poll WebSocket connection for new events (float: delta time in seconds)
	
	# Check connection state - WebSocketPeer state enum (int)
	var state = ws_peer.get_ready_state()  # Get current WebSocket connection state (int)
	#print("WebSocket state: ", state)
	
	if state == WebSocketPeer.STATE_OPEN:
		# Connection is open and ready for communication
		if not is_connected:
			# First time connection established - emit signal and update status
			if logger_instance:
				logger_instance.log_info(DebugLogger.Category.WEBSOCKET, "connection_established", {"url": default_url})
			is_connected = true  # Update connection flag (bool)
			emit_signal("connected")  # Emit connection signal for other systems
	elif state == WebSocketPeer.STATE_CLOSED:
		# Connection closed or lost - attempt reconnection
		if is_connected:
			# Connection was previously open but now closed
			if logger_instance:
				logger_instance.log_warning(DebugLogger.Category.WEBSOCKET, "connection_lost", {"url": default_url})
			is_connected = false  # Update connection flag (bool)
			emit_signal("disconnected")  # Emit disconnection signal for other systems
			schedule_reconnect()  # Schedule automatic reconnection attempt
	
	# Process all available messages from WebSocket server
	# Loop through all queued packets to ensure no messages are missed
	while ws_peer.get_available_packet_count() > 0:
		var packet = ws_peer.get_packet()  # Get next available packet (PackedByteArray)
		emit_signal("data_received", packet)  # Emit signal with packet data for route handlers
		#print("Received data: ", packet.get_string_from_utf8())

func schedule_reconnect():
	# Silently schedule reconnect - no output needed
	reconnect_timer.start()

func _on_reconnect_timer_timeout():
	# Silently attempt reconnect - no output needed
	connect_to_server(default_url)

func send_message(message):
	if is_connected:
		ws_peer.send_text(message)
		return true
	else:
		if logger_instance:
			logger_instance.log_warning(DebugLogger.Category.WEBSOCKET, "Cannot send message - WebSocket not connected to server")
		return false
