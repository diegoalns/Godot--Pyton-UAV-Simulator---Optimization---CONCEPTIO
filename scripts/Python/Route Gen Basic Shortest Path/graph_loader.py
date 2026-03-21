"""
Graph loader with concise structured logging.
"""

from pathlib import Path
import pickle
import networkx as nx
from sim_logger import log_event


def _extract_graph(loaded_data):
    """
    Extract NetworkX graph object from supported pickle payload shapes.
    """
    if isinstance(loaded_data, dict):
        if "graph" in loaded_data:
            return loaded_data["graph"], "dict.graph", sorted(loaded_data.keys())
        if "G" in loaded_data:
            return loaded_data["G"], "dict.G", sorted(loaded_data.keys())
        for key, value in loaded_data.items():
            if hasattr(value, "number_of_nodes"):
                return value, "dict.%s" % key, sorted(loaded_data.keys())
        raise ValueError("No NetworkX graph found in dictionary payload.")
    return loaded_data, "direct_object", []


def load_graph_from_pickle(pickle_path=None):
    """
    Load and validate graph data used by pathfinding.
    """
    if pickle_path is None:
        pickle_path = Path(__file__).parent / "regular_lattice_graph.pkl"
    else:
        pickle_path = Path(pickle_path)

    log_event(
        "INFO",
        "GRAPH_LOADER",
        "graph_load_started",
        file_path=str(pickle_path),
    )

    with open(pickle_path, "rb") as f:
        loaded_data = pickle.load(f)

    airspace_graph, graph_source, dict_keys = _extract_graph(loaded_data)

    if not isinstance(airspace_graph, (nx.Graph, nx.DiGraph, nx.MultiGraph, nx.MultiDiGraph)):
        log_event(
            "ERROR",
            "GRAPH_LOADER",
            "graph_invalid_type",
            loaded_type=type(airspace_graph).__name__,
            source=graph_source,
        )
        raise ValueError("Loaded object is not a valid NetworkX graph type.")

    num_nodes = airspace_graph.number_of_nodes()
    num_edges = airspace_graph.number_of_edges()
    if num_nodes == 0:
        log_event("ERROR", "GRAPH_LOADER", "graph_empty", node_count=0, edge_count=num_edges)
        raise ValueError("Loaded graph is empty (0 nodes).")
    if num_edges == 0:
        log_event("ERROR", "GRAPH_LOADER", "graph_has_no_edges", node_count=num_nodes, edge_count=0)
        raise ValueError("Loaded graph has no edges (0 edges).")

    log_event(
        "INFO",
        "GRAPH_LOADER",
        "graph_loaded",
        loaded_type=type(loaded_data).__name__,
        graph_type=type(airspace_graph).__name__,
        source=graph_source,
        dict_keys=dict_keys,
        node_count=num_nodes,
        edge_count=num_edges,
    )

    sample_node = list(airspace_graph.nodes())[0]
    node_data = airspace_graph.nodes[sample_node]
    created_pos_for_nodes = 0

    if "pos" not in node_data:
        if "lat" in node_data and "lon" in node_data and "altitude" in node_data:
            for node in airspace_graph.nodes():
                node_attrs = airspace_graph.nodes[node]
                airspace_graph.nodes[node]["pos"] = (
                    node_attrs["lat"],
                    node_attrs["lon"],
                    node_attrs["altitude"],
                )
                created_pos_for_nodes += 1
        else:
            available_attrs = sorted(list(node_data.keys())[:8])
            log_event(
                "ERROR",
                "GRAPH_LOADER",
                "node_position_attributes_missing",
                sample_node=str(sample_node),
                available_attributes=available_attrs,
            )
            raise ValueError("Node missing required position attributes.")

    num_samples = min(10, num_nodes)
    for node in list(airspace_graph.nodes())[:num_samples]:
        pos = airspace_graph.nodes[node]["pos"]
        if not isinstance(pos, (tuple, list)) or len(pos) != 3:
            log_event(
                "ERROR",
                "GRAPH_LOADER",
                "node_pos_invalid",
                node=str(node),
                pos_type=type(pos).__name__,
                pos_len=(len(pos) if isinstance(pos, (tuple, list)) else None),
            )
            raise ValueError("Node 'pos' must be a tuple/list with 3 values (lat, lon, alt).")

    num_edge_samples = min(10, num_edges)
    sample_edges = list(airspace_graph.edges())[:num_edge_samples]
    missing_weights = any("weight" not in airspace_graph.edges[u, v] for u, v in sample_edges)

    log_event(
        "INFO",
        "GRAPH_LOADER",
        "graph_validation_passed",
        created_pos_for_nodes=created_pos_for_nodes,
        sampled_nodes=num_samples,
        sampled_edges=num_edge_samples,
        missing_edge_weight_in_sample=missing_weights,
    )

    connectivity = {
        "graph_type": type(airspace_graph).__name__,
        "weakly_connected": None,
        "strongly_connected": None,
        "weakly_connected_components": None,
        "strongly_connected_components": None,
        "connected_components": None,
    }

    if isinstance(airspace_graph, nx.Graph) and not isinstance(airspace_graph, nx.DiGraph):
        is_connected = nx.is_connected(airspace_graph)
        connectivity["connected_components"] = (
            1 if is_connected else nx.number_connected_components(airspace_graph)
        )
        if not is_connected:
            log_event(
                "WARNING",
                "GRAPH_LOADER",
                "graph_connectivity_warning",
                mode="undirected",
                connected_components=connectivity["connected_components"],
            )
    elif isinstance(airspace_graph, nx.DiGraph):
        weakly_connected = nx.is_weakly_connected(airspace_graph)
        connectivity["weakly_connected"] = weakly_connected
        if weakly_connected:
            strongly_connected = nx.is_strongly_connected(airspace_graph)
            connectivity["strongly_connected"] = strongly_connected
            if not strongly_connected:
                connectivity["strongly_connected_components"] = nx.number_strongly_connected_components(
                    airspace_graph
                )
        else:
            connectivity["weakly_connected_components"] = nx.number_weakly_connected_components(
                airspace_graph
            )
            log_event(
                "WARNING",
                "GRAPH_LOADER",
                "graph_connectivity_warning",
                mode="directed",
                weakly_connected_components=connectivity["weakly_connected_components"],
            )

    log_event(
        "INFO",
        "GRAPH_LOADER",
        "graph_load_completed",
        node_count=num_nodes,
        edge_count=num_edges,
        connectivity=connectivity,
    )

    return airspace_graph

