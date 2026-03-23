import asyncio
import websockets
import json
import sys
import time  # Import time module for measuring pathfinding duration
import os
from pathlib import Path
import numpy as np
import networkx as nx
from coordinate_constants import *
from graph_loader import load_graph_from_pickle
from shortest_pathfinder import find_path
from sim_logger import (
    log_event,
    log_route_received_csv,
    reset_route_received_csv,
)
sys.path.append(str(Path(__file__).parent))

# Define helper functions for position mapping
def slant_range(p1, p2):
    """Calculates the 3D distance between two points in meters."""
    dx = p2[0] - p1[0]  # X distance in meterswhats
    dy = p2[1] - p1[1]  # Y distance in meters
    dz = p2[2] - p1[2]  # Z distance in meters
    return np.sqrt(dx**2 + dy**2 + dz**2)

def find_closest_node(graph, target_position):
    """
    Find the closest available node in the graph to the given 3D position.
    
    Args:
        graph: NetworkX graph with nodes having 'pos' attributes
        target_position: dict with lat, lon, alt coordinates
    
    Returns:
        tuple: The closest node identifier or None if no available nodes
    """
    if isinstance(target_position, dict):
        # Handle coordinate format: lon, lat, alt → lat, lon, alt for graph coordinates
        if 'lon' in target_position and 'lat' in target_position and 'alt' in target_position:
            target_pos = (target_position['lat'], target_position['lon'], target_position['alt'])
        else:
            target_pos = (target_position['x'], target_position['y'], target_position['z'])
    else:
        target_pos = tuple(target_position)
    
    min_distance = float('inf')
    closest_node = None
    
    for node in graph.nodes():
        # Only consider available nodes
        if not graph.nodes[node].get('available', True):
            continue
            
        node_pos = graph.nodes[node]['pos']
        distance = slant_range(target_pos, node_pos)
        
        if distance < min_distance:
            min_distance = distance
            closest_node = node
    
    return closest_node


# Load graph from optional environment override (used by GA integration).
graph_pickle_override = os.getenv("GRAPH_PICKLE_PATH", "").strip()
airspace_graph = load_graph_from_pickle(graph_pickle_override if graph_pickle_override else None)

# ============================================================================
# DRONE REGISTRY - Tracks active drones with their routes and overfly times
# ============================================================================
# Dictionary structure: {drone_id: {"route_nodes": [node1, node2, ...], 
#                                    "overfly_times": [t1, t2, ...], 
#                                    "start_time": float}}
# Each entry stores the sequence of graph nodes the drone will traverse and
# the simulation time when it will overfly each node
active_drones_registry = {}  # Dictionary mapping drone_id (str) to route data (dict)


def log_ws_info(event: str, **fields):
    log_event("INFO", "WEBSOCKET", event, **fields)


def log_ws_error(event: str, **fields):
    log_event("ERROR", "WEBSOCKET", event, **fields)


def log_ws_warning(event: str, **fields):
    log_event("WARNING", "WEBSOCKET", event, **fields)


def log_pathfinding(event: str, **fields):
    log_event("INFO", "PATHFINDING", event, **fields)

def cleanup_registry(current_simulation_time: float):
    """
    Remove drones from registry whose last node overfly time is less than current simulation time.
    This indicates the drone has completed its route.
    
    Args:
        current_simulation_time: float - Current simulation time in seconds from Godot
    """
    drones_to_remove = []  # List of drone IDs to remove from registry (list of str)
    
    # Iterate through all registered drones to check completion status
    for drone_id, route_data in active_drones_registry.items():
        overfly_times = route_data.get("overfly_times", [])  # List of overfly times (list of float)
        
        # Check if drone has completed route (last overfly time < current time)
        if len(overfly_times) > 0:
            last_overfly_time = overfly_times[-1]  # Last overfly time (float, seconds)
            if last_overfly_time < current_simulation_time:
                drones_to_remove.append(drone_id)  # Mark for removal (str)
    
    # Remove completed drones from registry (silently, no logging)
    for drone_id in drones_to_remove:
        active_drones_registry.pop(drone_id, None)  # Remove drone from registry
    
    return len(drones_to_remove)  # Return count of removed drones (int)

def calculate_overfly_times(path_nodes: list, start_time: float, speed: float, graph):
    """
    Calculate simulation times when drone will overfly each node in the path.
    Uses edge weights (distances) and drone speed to compute arrival times.
    
    Args:
        path_nodes: List of node IDs representing the route (list of str)
        start_time: Simulation time when route starts (float, seconds)
        speed: Drone speed in m/s (float)
        graph: NetworkX graph with edge weights (NetworkX Graph)
    
    Returns:
        List of overfly times corresponding to each node (list of float, seconds)
    """
    overfly_times = [start_time]  # Initialize with start time (list of float)
    current_time = start_time  # Track cumulative time (float, seconds)
    
    # Calculate time to traverse each edge in the path
    for i in range(len(path_nodes) - 1):
        current_node = path_nodes[i]  # Current node ID (str)
        next_node = path_nodes[i + 1]  # Next node ID (str)
        
        # Get edge weight (distance in meters) from graph
        if graph.has_edge(current_node, next_node):
            edge_weight = graph[current_node][next_node].get('weight', 0.0)  # Edge weight in meters (float)
        else:
            # Fallback: calculate distance from node positions if edge doesn't exist
            pos1 = graph.nodes[current_node]['pos']  # Position tuple (lat, lon, alt) (tuple of float)
            pos2 = graph.nodes[next_node]['pos']  # Position tuple (lat, lon, alt) (tuple of float)
            edge_weight = slant_range(pos1, pos2)  # 3D distance in meters (float)
        
        # Calculate traversal time: distance / speed (time in seconds)
        traversal_time = edge_weight / speed if speed > 0 else 0.0  # Time to traverse edge (float, seconds)
        current_time += traversal_time  # Add to cumulative time (float, seconds)
        overfly_times.append(current_time)  # Store overfly time for next node (float, seconds)
    
    return overfly_times  # Return list of overfly times (list of float)

def print_registry_status(current_simulation_time: float):
    """
    Registry status function (no longer prints - kept for compatibility).
    
    Args:
        current_simulation_time: Current simulation time for reference (float, seconds)
    """
    # Function kept for compatibility but no longer prints anything
    pass

# WebSocket server to handle drone creation messages and respond accordingly
async def websocket_handler(websocket):
    """
    Handle WebSocket client connections and route requests.
    Processes incoming messages from Godot simulation and responds with routes.
    
    Args:
        websocket: WebSocket connection object from websockets library
    """
    client_address = websocket.remote_address if hasattr(websocket, 'remote_address') else "unknown"
    log_ws_info(
        "client_connected",
        client_address=str(client_address),
        status="ready_to_receive_route_requests",
    )
    
    try:
        async for message in websocket:
            
            try:
                # Parse the JSON message
                data = json.loads(message)
                
                # Check for drone creation messages
                if data.get("type") == "request_route":
                    # Record system clock timestamp when request is received
                    request_received_system_clock_time = time.time()  # float: System clock time when request is received (seconds since epoch)
                    
                    drone_id = data.get("drone_id")
                    model = data.get("model")
                    start_pos = data.get("start_position")
                    end_pos = data.get("end_position")
                    max_speed = data.get("max_speed")
                    
                    # Get simulation time from Godot for registry cleanup (float, seconds)
                    simulation_time = float(data.get("simulation_time", 0.0))
                    # Route planning anchor should be ETD from flight plan.
                    # Fallback to current simulation time for backward compatibility.
                    route_start_time = float(data.get("etd_seconds", simulation_time))
                    log_pathfinding(
                        "route_request_timing_anchor",
                        plan_id=drone_id,
                        simulation_time=round(simulation_time, 6),
                        etd_seconds=round(route_start_time, 6),
                        route_start_time=round(route_start_time, 6),
                    )
                    
                    log_ws_info(
                        "route_request_received",
                        plan_id=drone_id,
                        request_received_system_clock_time=round(request_received_system_clock_time, 6),
                    )
                    
                    # Get node IDs if provided (efficient O(1) lookup)
                    start_node_id = data.get("start_node_id")
                    end_node_id = data.get("end_node_id")
                    
                    # Registry cleanup: Remove completed drones before processing new request
                    cleanup_registry(simulation_time)  # Remove completed drones from registry
                    
                    # Determine start and end nodes - prioritize Node IDs for speed
                    start_node = None
                    end_node = None
                    
                    # METHOD 1: Use Node IDs if provided (FAST - O(1) hash lookup)
                    if start_node_id and end_node_id:
                        # Direct graph lookup - instant O(1) operation
                        if airspace_graph.has_node(start_node_id):
                            start_node = start_node_id
                        if airspace_graph.has_node(end_node_id):
                            end_node = end_node_id
                    
                    # METHOD 2: Fallback to coordinate mapping if Node IDs not available (SLOW - O(n) search)
                    if start_node is None or end_node is None:
                        if start_node is None:
                            start_node = find_closest_node(airspace_graph, start_pos)
                        if end_node is None:
                            end_node = find_closest_node(airspace_graph, end_pos)
                    
                    # Check if we successfully found both nodes
                    if start_node is None or end_node is None:
                        # Early error - record timing and send response
                        response_sent_system_clock_time = time.time()  # float: System clock time when error response is sent (seconds since epoch)
                        total_processing_time = response_sent_system_clock_time - request_received_system_clock_time  # float: Total server processing time in seconds
                        
                        log_pathfinding(
                            "route_request_rejected_invalid_nodes",
                            plan_id=drone_id,
                            pathfinding_duration=None,
                            response_sent_system_clock_time=round(response_sent_system_clock_time, 6),
                            total_processing_time=round(total_processing_time, 6),
                        )
                        
                        # Send error response with timing metadata
                        response = {
                            "type": "route_response",
                            "drone_id": drone_id,
                            "status": "error",
                            "message": "Could not find valid graph nodes for start or end position",
                            "server_request_received_time": request_received_system_clock_time,  # float: System clock time when server received request (seconds)
                            "server_response_sent_time": response_sent_system_clock_time,  # float: System clock time when server sent response (seconds)
                            "pathfinding_duration": 0.0  # float: No pathfinding performed (0.0 seconds)
                        }
                        await websocket.send(json.dumps(response))
                        continue

                    try:
                        # PATHFINDING: Find weighted shortest path with NetworkX
                        # Record start time for pathfinding process (system clock time in seconds)
                        pathfinding_start_time = time.time()  # float: System clock time when pathfinding starts (seconds)
                        
                        # Use full Godot max_speed for route timing and returned waypoint speeds
                        waypoint_speed = max_speed  # Waypoint speed in m/s (float)
                        
                        # Run shortest-path algorithm with 3-second timeout (system clock time)
                        pathfinding_timeout = 3.0  # Timeout duration in seconds (float)
                        try:
                            # Run pathfinding in thread pool with timeout
                            path_result = await asyncio.wait_for(
                                asyncio.to_thread(
                                    find_path,
                                    graph=airspace_graph,  # NetworkX graph with edge weights (nx.Graph)
                                    start_node=start_node,  # Starting node ID (str)
                                    goal_node=end_node,  # Goal node ID (str)
                                    start_time=route_start_time,  # Planner starts at ETD (float, seconds)
                                    speed=waypoint_speed,  # Drone speed for temporal calculations (float, m/s)
                                    registry=active_drones_registry,  # Kept for compatibility (dict)
                                    conflict_threshold=20.0,  # Kept for compatibility (float, seconds)
                                    max_search_iterations=10,  # Kept for compatibility (int)
                                    round_trip=True,  # Plan complete round trip route (bool)
                                    wait_time_at_destination=60.0  # Wait 60 seconds at destination before return (float, seconds)
                                ),
                                timeout=pathfinding_timeout  # Timeout after 3 seconds (float, seconds)
                            )
                        except asyncio.TimeoutError:
                            # Pathfinding exceeded 3-second timeout
                            pathfinding_end_time = time.time()  # float: System clock time when timeout occurred (seconds)
                            pathfinding_duration = pathfinding_end_time - pathfinding_start_time  # float: Pathfinding duration before timeout (seconds)
                            
                            # Record system clock timestamp when timeout error response is sent
                            response_sent_system_clock_time = time.time()  # float: System clock time when timeout error response is sent (seconds since epoch)
                            total_processing_time = response_sent_system_clock_time - request_received_system_clock_time  # float: Total server processing time in seconds
                            
                            log_pathfinding(
                                "pathfinding_timeout",
                                plan_id=drone_id,
                                pathfinding_duration=round(pathfinding_duration, 6),
                                response_sent_system_clock_time=round(response_sent_system_clock_time, 6),
                                total_processing_time=round(total_processing_time, 6),
                            )
                            
                            # Send timeout error response with timing metadata
                            response = {
                                "type": "route_response",
                                "drone_id": drone_id,
                                "status": "timeout",
                                "message": f"No route found within {pathfinding_timeout} seconds",
                                "server_request_received_time": request_received_system_clock_time,  # float: System clock time when server received request (seconds)
                                "server_response_sent_time": response_sent_system_clock_time,  # float: System clock time when server sent response (seconds)
                                "pathfinding_duration": pathfinding_duration  # float: Pathfinding processing time before timeout (seconds)
                            }
                            await websocket.send(json.dumps(response))
                            continue
                        
                        # Check if planner found a path
                        if path_result is None:
                            # No path found - record timing
                            pathfinding_end_time = time.time()  # float: System clock time when pathfinding completed with no path (seconds)
                            pathfinding_duration = pathfinding_end_time - pathfinding_start_time  # float: Pathfinding duration in seconds
                            
                            # Record system clock timestamp when error response is sent
                            response_sent_system_clock_time = time.time()  # float: System clock time when error response is sent (seconds since epoch)
                            total_processing_time = response_sent_system_clock_time - request_received_system_clock_time  # float: Total server processing time in seconds
                            
                            log_pathfinding(
                                "pathfinding_no_path",
                                plan_id=drone_id,
                                pathfinding_duration=round(pathfinding_duration, 6),
                                response_sent_system_clock_time=round(response_sent_system_clock_time, 6),
                                total_processing_time=round(total_processing_time, 6),
                            )
                            
                            # Send error response with timing metadata
                            response = {
                                "type": "route_response",
                                "drone_id": drone_id,
                                "status": "no_path",
                                "message": "No path found in graph between start and end positions",
                                "server_request_received_time": request_received_system_clock_time,  # float: System clock time when server received request (seconds)
                                "server_response_sent_time": response_sent_system_clock_time,  # float: System clock time when server sent response (seconds)
                                "pathfinding_duration": pathfinding_duration  # float: Pathfinding processing time in seconds
                            }
                            await websocket.send(json.dumps(response))
                            continue
                        
                        # Record end time for pathfinding process (system clock time in seconds)
                        pathfinding_end_time = time.time()  # float: System clock time when pathfinding completes (seconds)
                        pathfinding_duration = pathfinding_end_time - pathfinding_start_time  # float: Pathfinding duration in seconds
                        
                        # Unpack pathfinder result: path nodes and overfly times
                        path_nodes, overfly_times = path_result  # path_nodes: list of str, overfly_times: list of float
                        
                        # Convert path nodes to geographic coordinates (lat, lon, altitude)
                        route = []  # List of waypoint dictionaries to send to Godot
                        for i, node in enumerate(path_nodes):
                            # Get node position: tuple of (lat, lon, alt) where lat/lon are in degrees, alt in meters
                            node_pos = airspace_graph.nodes[node]['pos']  # (lat, lon, alt)
                            
                            # Determine waypoint description based on position in route
                            is_destination = (node == end_node)  # Check if this is destination node (bool)
                            next_node = path_nodes[i + 1] if i + 1 < len(path_nodes) else None  # Next node ID (str or None)
                            is_wait_waypoint = (is_destination and next_node == end_node and i + 1 < len(overfly_times))  # Check if this is wait waypoint (bool)
                            
                            if i == 0:
                                waypoint_desc = f"Origin (waypoint {i+1})"  # Origin waypoint description (str)
                            elif is_wait_waypoint:
                                wait_duration = overfly_times[i + 1] - overfly_times[i] if i + 1 < len(overfly_times) else 60.0  # Wait duration in seconds (float)
                                waypoint_desc = f"Destination - Wait {wait_duration:.0f}s (waypoint {i+1})"  # Wait waypoint description (str)
                            elif is_destination:
                                waypoint_desc = f"Destination (waypoint {i+1})"  # Destination waypoint description (str)
                            elif i == len(path_nodes) - 1:
                                waypoint_desc = f"Return to origin (waypoint {i+1})"  # Final waypoint description (str)
                            elif node == start_node and i > len(path_nodes) / 2:
                                waypoint_desc = f"Return to origin (waypoint {i+1})"  # Return origin waypoint description (str)
                            elif i < len(path_nodes) / 2:
                                waypoint_desc = f"Outbound waypoint {i+1}"  # Outbound waypoint description (str)
                            else:
                                waypoint_desc = f"Return waypoint {i+1}"  # Return waypoint description (str)
                            
                            # Create waypoint with geographic coordinates
                            waypoint = {
                                "lat": node_pos[0],         # Latitude in decimal degrees (float)
                                "lon": node_pos[1],         # Longitude in decimal degrees (float)
                                "altitude": node_pos[2],    # Altitude in meters (float)
                                "speed": waypoint_speed,    # Waypoint speed: same as drone max speed (float, m/s)
                                "description": waypoint_desc  # Human-readable waypoint label (string)
                            }
                            route.append(waypoint)
                        
                        # REGISTRY STORAGE: Save route and overfly times to registry
                        active_drones_registry[drone_id] = {
                            "route_nodes": path_nodes,           # List of node IDs (list of str)
                            "overfly_times": overfly_times,       # List of overfly times (list of float)
                            "start_time": route_start_time        # Route start time (float, seconds, ETD-based)
                        }

                        # Record system clock timestamp when response is sent
                        response_sent_system_clock_time = time.time()  # float: System clock time when response is sent (seconds since epoch)
                        total_processing_time = response_sent_system_clock_time - request_received_system_clock_time  # float: Total server processing time in seconds

                        # CSV OUTPUT: Persist per-waypoint planned route timing from Python.
                        # NOTE: total_processing_time must be computed before this call.
                        log_route_received_csv(
                            plan_id=drone_id,
                            start_node_id=start_node,
                            end_node_id=end_node,
                            path_nodes=path_nodes,
                            overfly_times=overfly_times,
                            start_time_sim=route_start_time,
                            waypoint_speed_mps=waypoint_speed,
                            pathfinding_duration_s=pathfinding_duration,
                            total_processing_time_s=total_processing_time,
                        )
                        
                        log_pathfinding(
                            "pathfinding_success",
                            plan_id=drone_id,
                            pathfinding_duration=round(pathfinding_duration, 6),
                            response_sent_system_clock_time=round(response_sent_system_clock_time, 6),
                            total_processing_time=round(total_processing_time, 6),
                            waypoint_count=len(route),
                        )
                        
                    except Exception as e:
                        # Handle any unexpected errors during pathfinding
                        # Record end time even if pathfinding failed (system clock time in seconds)
                        pathfinding_end_time = time.time()  # float: System clock time when pathfinding error occurred (seconds)
                        pathfinding_duration = pathfinding_end_time - pathfinding_start_time  # float: Pathfinding duration before error (seconds)
                        
                        # Record system clock timestamp when error response is sent
                        response_sent_system_clock_time = time.time()  # float: System clock time when error response is sent (seconds since epoch)
                        total_processing_time = response_sent_system_clock_time - request_received_system_clock_time  # float: Total server processing time in seconds
                        
                        log_pathfinding(
                            "pathfinding_error",
                            plan_id=drone_id,
                            pathfinding_duration=round(pathfinding_duration, 6),
                            response_sent_system_clock_time=round(response_sent_system_clock_time, 6),
                            total_processing_time=round(total_processing_time, 6),
                            error_type=type(e).__name__,
                            error_message=str(e),
                        )
                        
                        # Send error response with timing metadata
                        response = {
                            "type": "route_response",
                            "drone_id": drone_id,
                            "status": "error",
                            "message": f"Pathfinding error: {str(e)}",
                            "server_request_received_time": request_received_system_clock_time,  # float: System clock time when server received request (seconds)
                            "server_response_sent_time": response_sent_system_clock_time,  # float: System clock time when server sent response (seconds)
                            "pathfinding_duration": pathfinding_duration  # float: Pathfinding processing time in seconds
                        }
                        await websocket.send(json.dumps(response))
                        continue


                    # Hybrid timing: Record system clock timestamp when response is sent (if not already recorded in try block)
                    if 'response_sent_system_clock_time' not in locals():
                        response_sent_system_clock_time = time.time()  # float: System clock time when response is sent (seconds since epoch)
                    
                    # Send acknowledgment with route - include timing metadata for client correlation
                    response = {
                        "type": "route_response",
                        "drone_id": drone_id,
                        "status": "success",
                        "route": route,
                        # Hybrid timing: Include server-side timestamps for end-to-end correlation
                        "server_request_received_time": request_received_system_clock_time,  # float: System clock time when server received request (seconds)
                        "server_response_sent_time": response_sent_system_clock_time,  # float: System clock time when server sent response (seconds)
                        "pathfinding_duration": pathfinding_duration if 'pathfinding_duration' in locals() else 0.0  # float: Pathfinding processing time in seconds
                    }
                    await websocket.send(json.dumps(response))
                elif data.get("type") == "drone_completed":
                    # Handle drone completion message from Godot
                    drone_id = data.get("drone_id")
                    
                    if drone_id in active_drones_registry:
                        # Remove completed drone from registry.
                        active_drones_registry.pop(drone_id)
                else:
                    # Echo other messages
                    await websocket.send(f"Echo: {message}")
            except json.JSONDecodeError:
                # Keep visibility when malformed payloads arrive.
                sample = str(message).replace("\n", "\\n")[:200]
                log_ws_warning(
                    "received_non_json_message",
                    message_length=len(str(message)),
                    message_sample=sample,
                )
                continue
                
    except websockets.ConnectionClosed:
        log_ws_info("client_disconnected")
    except Exception as e:
        log_ws_error(
            "websocket_handler_error",
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise  # Re-raise to close the connection

# Start the server on configurable host/port (defaults to localhost:8765).
async def start_server():
    """
    Start the WebSocket server on configured host/port.
    Handles server startup, prints status messages, and runs indefinitely.
    
    Raises:
        OSError: If the port is already in use or other network errors occur
        Exception: Any other errors during server startup
    """
    server_host = os.getenv("WS_SERVER_HOST", "localhost").strip() or "localhost"
    server_port_env = os.getenv("WS_SERVER_PORT", "8765").strip()
    try:
        server_port = int(server_port_env)
    except ValueError:
        raise ValueError(f"Invalid WS_SERVER_PORT value: {server_port_env!r}")
    
    try:
        # Ensure per-run CSV behavior matches Godot logs: clear file at startup.
        reset_route_received_csv()
        log_ws_info(
            "server_starting",
            server_address=f"ws://{server_host}:{server_port}",
            status="initializing",
        )
        
        # Start the WebSocket server - this may raise OSError if port is in use
        async with websockets.serve(websocket_handler, server_host, server_port):
            log_ws_info(
                "server_running",
                server_address=f"ws://{server_host}:{server_port}",
                status="running",
                waiting_for="godot_connections",
            )
            
            # Run forever - wait indefinitely for connections
            await asyncio.Future()  # Run forever (blocks until cancelled)
            
    except OSError as e:
        log_ws_error(
            "server_startup_failed",
            error_type="OSError",
            error_message=str(e),
            server_port=server_port,
            possible_causes=[
                "port_in_use",
                "insufficient_permissions",
                "network_interface_issue",
            ],
        )
        raise  # Re-raise to exit with error code
        
    except Exception as e:
        log_ws_error(
            "server_startup_failed",
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise  # Re-raise to exit with error code


if __name__ == "__main__":
    """
    Main entry point for the WebSocket server.
    Runs the async server and handles any uncaught exceptions.
    """
    try:
        # Run the async server - this will block until cancelled or error occurs
        asyncio.run(start_server())
    except KeyboardInterrupt:
        log_event(
            "WARNING",
            "WEBSOCKET",
            "server_shutdown_requested",
            reason="keyboard_interrupt",
        )
    except Exception as e:
        import traceback
        log_event(
            "ERROR",
            "WEBSOCKET",
            "server_fatal_error",
            error_type=type(e).__name__,
            error_message=str(e),
            traceback=traceback.format_exc(),
        )
        sys.exit(1)  # Exit with error code
    