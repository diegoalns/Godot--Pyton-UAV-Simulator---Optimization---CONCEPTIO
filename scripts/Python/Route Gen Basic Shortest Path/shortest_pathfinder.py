"""
Shortest path planner module.

This replaces the previous conflict-aware implementation with a simple weighted shortest
path strategy using NetworkX built-ins.
"""

import networkx as nx
from typing import Dict, List, Optional, Tuple


def _edge_distance(graph: nx.Graph, node_a: str, node_b: str) -> float:
    """Return edge distance in meters."""
    if graph.has_edge(node_a, node_b):
        return float(graph[node_a][node_b].get("weight", 0.0))

    # Fallback distance from node coordinates if no edge weight is present.
    pos1 = graph.nodes[node_a]["pos"]
    pos2 = graph.nodes[node_b]["pos"]
    dx = pos2[0] - pos1[0]
    dy = pos2[1] - pos1[1]
    dz = pos2[2] - pos1[2]
    return float((dx**2 + dy**2 + dz**2) ** 0.5)


def _build_overfly_times(
    graph: nx.Graph,
    path_nodes: List[str],
    start_time: float,
    speed: float,
) -> List[float]:
    """Build per-node overfly times from path geometry and speed."""
    overfly_times = [start_time]
    current_time = start_time

    for i in range(len(path_nodes) - 1):
        edge_weight = _edge_distance(graph, path_nodes[i], path_nodes[i + 1])
        traversal_time = edge_weight / speed if speed > 0 else 0.0
        current_time += traversal_time
        overfly_times.append(current_time)

    return overfly_times


def _find_one_way_path_nodes(
    graph: nx.Graph,
    start_node: str,
    goal_node: str,
) -> Optional[List[str]]:
    """Find weighted shortest path nodes using NetworkX."""
    try:
        path_nodes = nx.shortest_path(
            graph,
            source=start_node,
            target=goal_node,
            weight="weight",
        )
        return [str(node) for node in path_nodes]
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None


def find_path(
    graph: nx.Graph,
    start_node: str,
    goal_node: str,
    start_time: float,
    speed: float,
    registry: Dict,  # Kept for API compatibility; intentionally unused.
    conflict_threshold: float = 20.0,  # Kept for API compatibility; unused.
    max_search_iterations: int = 10,  # Kept for API compatibility; unused.
    round_trip: bool = True,
    wait_time_at_destination: float = 60.0,
) -> Optional[Tuple[List[str], List[float]]]:
    """
    Compatibility wrapper that now performs simple weighted shortest path search.

    Returns:
        (path_nodes, overfly_times) or None when no path is available.
    """
    _ = registry
    _ = conflict_threshold
    _ = max_search_iterations

    outbound_nodes = _find_one_way_path_nodes(graph, start_node, goal_node)
    if outbound_nodes is None or len(outbound_nodes) == 0:
        return None

    outbound_times = _build_overfly_times(graph, outbound_nodes, start_time, speed)

    if not round_trip:
        return outbound_nodes, outbound_times

    wait_end_time = outbound_times[-1] + wait_time_at_destination
    return_nodes = _find_one_way_path_nodes(graph, goal_node, start_node)
    if return_nodes is None or len(return_nodes) == 0:
        return None

    return_times = _build_overfly_times(graph, return_nodes, wait_end_time, speed)

    complete_path_nodes = outbound_nodes.copy()
    complete_path_nodes.append(goal_node)  # Duplicate destination to represent wait.
    complete_path_nodes.extend(return_nodes[1:])

    complete_overfly_times = outbound_times.copy()
    complete_overfly_times.append(wait_end_time)
    complete_overfly_times.extend(return_times[1:])

    if len(complete_path_nodes) != len(complete_overfly_times):
        raise ValueError(
            f"Path nodes ({len(complete_path_nodes)}) and overfly times "
            f"({len(complete_overfly_times)}) length mismatch"
        )

    return complete_path_nodes, complete_overfly_times

