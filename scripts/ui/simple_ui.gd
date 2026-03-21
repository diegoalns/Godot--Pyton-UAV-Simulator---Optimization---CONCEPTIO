class_name SimpleUI
extends Control

signal start_requested
signal pause_requested
signal speed_changed(multiplier: float)
signal headless_mode_changed(enable: bool)
signal port_selected(port_id: String)

@onready var start_button = Button.new()
@onready var speed_slider = HSlider.new()
@onready var status_label = Label.new()
@onready var headless_checkbox = CheckBox.new()
@onready var port_selector = OptionButton.new()
@onready var time_label = Label.new()
@onready var active_drones_panel: ActiveDronesPanel = null  # Panel for displaying active drones (ActiveDronesPanel)

var is_running = false
var headless_mode: bool = false

func _ready():
	setup_ui()
	self.anchor_left = 0.0
	self.anchor_right = 1.0
	self.anchor_top = 0.0
	self.anchor_bottom = 1.0
	self.offset_left = 0
	self.offset_right = 0
	self.offset_top = 0
	self.offset_bottom = 0

func setup_ui():
	# Create Active Drones Panel on the left side
	active_drones_panel = ActiveDronesPanel.new()
	add_child(active_drones_panel)  # Add panel to UI
	
	# Layout for control buttons (original position - top left)
	var vbox = VBoxContainer.new()
	vbox.size_flags_vertical = Control.SIZE_EXPAND_FILL
	vbox.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	add_child(vbox)  # Add control container to UI
	
	# Headless mode toggle
	headless_checkbox.text = "Headless Mode"
	headless_checkbox.toggled.connect(_on_headless_toggled)
	vbox.add_child(headless_checkbox)
	
	# Start/Pause button
	start_button.text = "Start"
	start_button.pressed.connect(_on_start_pressed)
	vbox.add_child(start_button)
	
	# Speed control
	var speed_label = Label.new()
	speed_label.text = "Speed: "
	vbox.add_child(speed_label)
	
	speed_slider.min_value = 0.5
	speed_slider.max_value = 5.0
	speed_slider.value = 1.0
	speed_slider.value_changed.connect(_on_speed_changed)
	vbox.add_child(speed_slider)
	
	# Port selector
	vbox.add_child(port_selector)
	port_selector.item_selected.connect(_on_port_selected)
	
	# Status
	status_label.text = "Ready"
	vbox.add_child(status_label)
	
	# Time label (top right) - original position
	time_label.text = "Sim: 0.00s | Real: 0.00s"
	time_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	time_label.anchor_left = 0
	time_label.anchor_right = 1.0
	time_label.anchor_top = 0.0
	time_label.anchor_bottom = 0.0
	time_label.offset_right = -10
	time_label.offset_top = 10
	add_child(time_label)

func _on_start_pressed():
	is_running = !is_running
	if is_running:
		start_button.text = "Pause"
		emit_signal("start_requested")
	else:
		start_button.text = "Start"
		emit_signal("pause_requested")

func _on_speed_changed(value: float):
	emit_signal("speed_changed", value)

func update_status(text: String):
	status_label.text = text
	
func _on_headless_toggled(pressed: bool):
	headless_mode = pressed
	emit_signal("headless_mode_changed", pressed)

func set_drone_ports(port_ids: Array):
	port_selector.clear()
	for port_id in port_ids:
		port_selector.add_item(port_id)

func _on_port_selected(index: int):
	var port_id = port_selector.get_item_text(index)
	emit_signal("port_selected", port_id)

func update_time(sim_time: float, real_time: float):
	time_label.text = "Sim: %.2fs | Real: %.2fs" % [sim_time, real_time]

func set_drone_manager(manager: DroneManager):
	"""
	Set the DroneManager reference for the active drones panel
	
	Args:
		manager: DroneManager - Reference to the DroneManager instance
	"""
	if active_drones_panel != null:
		active_drones_panel.set_drone_manager(manager)  # Pass DroneManager to panel (void)
