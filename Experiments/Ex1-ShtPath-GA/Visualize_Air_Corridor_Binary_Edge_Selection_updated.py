"""
3D Lattice Graph Visualizer with Air Corridor Binary Edge Selection

This script loads a 3D lattice graph from a pickle file and implements a binary variable
system for visualization. Each variable represents one air corridor with a directional pair
in a layer (forward grid direction vs reverse grid direction):

- Corridor type X: edges where nodes have the same grid_x (movement along y)
- Corridor type Y: edges where nodes have the same grid_y (movement along x)

For each corridor, edges are grouped by grid direction sign. A binary value selects:
- 0: forward direction set for that variable
- 1: opposite direction set for that variable

This follows the same binary codification pattern as the other selection files.
Vertical edges are always displayed.
"""

import Visualize_Binary_Edge_Selection_updated as binary_visualizer

# --- Configuration ---

PICKLE_FILENAME = "regular_lattice_graph.pkl"

# Binary Selection Configuration
USE_RANDOM_BINARY = True
RANDOM_SEED = 14
BINARY_SET = None

# Output Configuration
HTML_FILENAME = "lattice_graph_air_corridor_binary_selection.html"

def identify_air_corridor_edge_groups(G):
    """
    Identify air-corridor variables by layer + (same x or same y) + contiguous segment + grid direction sign.

    Returns:
        tuple: (group_dict, variable_to_group_list)
            - group_dict: raw dictionary of corridor groups with forward/reverse edge lists
            - variable_to_group_list: list of (group_key, forward_edges, reverse_edges)
              where one variable corresponds to one contiguous corridor segment with its two direction sets.
    """
    print("\nIdentifying air corridor groups by layer/x/y, contiguous segment, and grid direction...")

    edge_records = []  # (u, v, base_key, direction_is_forward)
    base_adjacency = {}  # base_key -> dict(node -> set(neighbor_nodes))

    for u, v, data in G.edges(data=True):
        if data.get("layer_type") != "Horizontal":
            continue

        u_data = G.nodes[u]
        v_data = G.nodes[v]

        u_layer = u_data.get("layer", 0)
        v_layer = v_data.get("layer", 0)
        if u_layer != v_layer:
            continue

        ux, uy = u_data.get("grid_x"), u_data.get("grid_y")
        vx, vy = v_data.get("grid_x"), v_data.get("grid_y")

        # Same grid_x corridor (movement along y): forward if y increases
        if ux == vx and uy != vy:
            corridor_axis = "x"
            fixed_index = ux
            direction_is_forward = vy > uy
        # Same grid_y corridor (movement along x): forward if x increases
        elif uy == vy and ux != vx:
            corridor_axis = "y"
            fixed_index = uy
            direction_is_forward = vx > ux
        else:
            # Skip non-axis-aligned or degenerate horizontal edges
            continue

        base_key = (u_layer, corridor_axis, fixed_index)
        edge_records.append((u, v, base_key, direction_is_forward))

        if base_key not in base_adjacency:
            base_adjacency[base_key] = {}
        if u not in base_adjacency[base_key]:
            base_adjacency[base_key][u] = set()
        if v not in base_adjacency[base_key]:
            base_adjacency[base_key][v] = set()
        base_adjacency[base_key][u].add(v)
        base_adjacency[base_key][v].add(u)

    # Build contiguous segment IDs per base corridor key using undirected connectivity
    base_node_to_segment = {}  # base_key -> dict(node -> segment_id)
    base_segment_counts = {}  # base_key -> number of segments
    for base_key, adjacency in base_adjacency.items():
        node_to_segment = {}
        segment_id = 0
        for start_node in sorted(adjacency.keys()):
            if start_node in node_to_segment:
                continue
            stack = [start_node]
            node_to_segment[start_node] = segment_id
            while stack:
                node = stack.pop()
                for nbr in adjacency[node]:
                    if nbr not in node_to_segment:
                        node_to_segment[nbr] = segment_id
                        stack.append(nbr)
            segment_id += 1
        base_node_to_segment[base_key] = node_to_segment
        base_segment_counts[base_key] = segment_id

    corridor_groups = {}
    for u, v, base_key, direction_is_forward in edge_records:
        segment_id = base_node_to_segment[base_key][u]
        layer, axis, fixed_index = base_key
        group_key = (layer, axis, fixed_index, segment_id)

        if group_key not in corridor_groups:
            corridor_groups[group_key] = {"forward": [], "reverse": []}
        if direction_is_forward:
            corridor_groups[group_key]["forward"].append((u, v))
        else:
            corridor_groups[group_key]["reverse"].append((u, v))

    # Deterministic edge order inside each direction set
    for key in corridor_groups:
        corridor_groups[key]["forward"] = sorted(corridor_groups[key]["forward"])
        corridor_groups[key]["reverse"] = sorted(corridor_groups[key]["reverse"])

    variable_to_group_list = []
    for key in sorted(corridor_groups.keys()):
        forward_edges = corridor_groups[key]["forward"]
        reverse_edges = corridor_groups[key]["reverse"]
        variable_to_group_list.append((key, forward_edges, reverse_edges))

    print(f"   Corridor groups found: {len(corridor_groups)}")
    print(f"   Air corridor variables created: {len(variable_to_group_list)}")

    # Report by layer and corridor type
    layer_axis_counts = {}
    for key, _, _ in variable_to_group_list:
        layer, axis, fixed_index, segment_id = key
        layer_axis_counts.setdefault((layer, axis), 0)
        layer_axis_counts[(layer, axis)] += 1

    if layer_axis_counts:
        print("   Variables by layer/corridor type:")
        for (layer, axis), count in sorted(layer_axis_counts.items()):
            corridor_name = "same grid_x" if axis == "x" else "same grid_y"
            print(f"      Layer {layer}, {corridor_name}: {count}")

    # Report segmentation summary
    segmented_corridors = sum(1 for _, seg_count in base_segment_counts.items() if seg_count > 1)
    total_base_corridors = len(base_segment_counts)
    print(f"   Base corridors: {total_base_corridors}")
    print(f"   Corridors split into multiple segments: {segmented_corridors}")

    # Show examples
    if variable_to_group_list:
        print("   Example variables (first 5):")
        for i, (key, forward_edges, reverse_edges) in enumerate(variable_to_group_list[:5]):
            layer, axis, fixed_index, segment_id = key
            print(
                f"      Variable {i}: layer={layer}, axis={axis}, fixed_index={fixed_index}, segment={segment_id}, "
                f"forward_edges={len(forward_edges)}, reverse_edges={len(reverse_edges)}"
            )

    return corridor_groups, variable_to_group_list


def select_edges_from_binary(variable_to_group_list, binary_set):
    """
    Select edges to display from binary set.

    - 0: select forward direction group
    - 1: select reverse direction group
    """
    print("\nSelecting edges based on binary set...")

    edges_to_display = set()
    forward_selected = 0
    reverse_selected = 0

    for var_idx, (group_key, forward_edges, reverse_edges) in enumerate(variable_to_group_list):
        binary_value = binary_set[var_idx]

        if binary_value == 0:
            forward_selected += 1
            for edge in forward_edges:
                edges_to_display.add(edge)
        elif binary_value == 1:
            reverse_selected += 1
            for edge in reverse_edges:
                edges_to_display.add(edge)
        else:
            print(f"   WARNING: Invalid binary value {binary_value} at variable {var_idx}")

    print(f"   Variables selecting forward groups: {forward_selected}")
    print(f"   Variables selecting reverse groups: {reverse_selected}")
    print(f"   Selected {len(edges_to_display)} unique edges to display")

    return edges_to_display

def build_edge_group_labels(variable_to_group_list):
    """
    Build an edge-to-group label mapping for visualization hover text.

    Label format:
        G{index} | L{layer}-{axis}{fixed_index}-S{segment_id}
    """
    edge_group_labels = {}

    for var_idx, (group_key, forward_edges, reverse_edges) in enumerate(variable_to_group_list):
        layer, axis, fixed_index, segment_id = group_key
        label = f"G{var_idx} | L{layer}-{axis}{fixed_index}-S{segment_id}"
        for edge in forward_edges + reverse_edges:
            edge_group_labels[edge] = label

    return edge_group_labels


if __name__ == "__main__":
    print("=" * 70)
    print("3D LATTICE GRAPH VISUALIZER WITH AIR CORRIDOR BINARY EDGE SELECTION")
    print("=" * 70)

    print("\nConfiguration:")
    print(f"  Binary selection: {'Random' if USE_RANDOM_BINARY else 'Custom'}")
    if USE_RANDOM_BINARY:
        print(f"  Random seed: {RANDOM_SEED}")
    print(f"  Input file: {PICKLE_FILENAME}")
    print(f"  Output file: {HTML_FILENAME}")

    # 1. Load graph
    G, metadata = binary_visualizer.load_graph_from_pickle(PICKLE_FILENAME)

    # 2. Identify air corridor variables
    group_dict, variable_to_group_list = identify_air_corridor_edge_groups(G)
    num_variables = len(variable_to_group_list)

    # 3. Generate binary set
    binary_set = binary_visualizer.generate_binary_set(
        num_variables,
        use_random=USE_RANDOM_BINARY,
        seed=RANDOM_SEED if USE_RANDOM_BINARY else None,
        custom_set=BINARY_SET,
    )

    # 4. Select edges
    edges_to_display = select_edges_from_binary(variable_to_group_list, binary_set)
    edge_group_labels = build_edge_group_labels(variable_to_group_list)

    # 5. Extract layer info
    layer_altitudes_ft = binary_visualizer.get_layer_altitudes_from_graph(G)
    num_layers = binary_visualizer.get_num_layers_from_graph(G)

    print("\nGraph Statistics:")
    print(f"  Total nodes: {G.number_of_nodes()}")
    print(f"  Total horizontal edges in graph: {sum(1 for _, _, d in G.edges(data=True) if d.get('layer_type') == 'Horizontal')}")
    print(f"  Air corridor variables: {num_variables}")
    print(f"  Edges displayed: {len(edges_to_display)}")
    print(f"  Number of layers: {num_layers}")

    # 6. Visualize using same method as other files
    binary_visualizer.HTML_FILENAME = HTML_FILENAME
    binary_visualizer.visualize_3d_graph(
        G,
        edges_to_display,
        layer_altitudes_ft,
        num_layers,
        edge_group_labels=edge_group_labels
    )

    print("\n" + "=" * 70)
    print("VISUALIZATION COMPLETE")
    print("=" * 70)
    print(f"Output file: {HTML_FILENAME}")
    print(f"Binary set used: {binary_set.tolist()[:20]}..." if len(binary_set) > 20 else f"Binary set used: {binary_set.tolist()}")
    print("=" * 70)
