"""
3D Lattice Graph Visualizer with Air Corridor Binary Edge Selection

This script loads a 3D lattice graph from a pickle file and implements a binary variable
system for visualization. Each variable represents one air corridor with a directional pair
in a layer (forward heading group vs opposite heading group):

- Corridor type X: edges where nodes have the same grid_x (movement along y)
- Corridor type Y: edges where nodes have the same grid_y (movement along x)

For each corridor, edges are grouped by direction (heading). A binary value selects:
- 0: forward direction set for that variable
- 1: opposite direction set for that variable

This follows the same binary codification pattern as the other selection files.
Vertical edges are always displayed.
"""

import numpy as np
import Visualize_Binary_Edge_Selection as binary_visualizer

# --- Configuration ---

PICKLE_FILENAME = "./Experiments/Ex1-ShtPath-GA/regular_lattice_graph.pkl"

# Binary Selection Configuration
USE_RANDOM_BINARY = True
RANDOM_SEED = 160
BINARY_SET = None

# Output Configuration
HTML_FILENAME = "lattice_graph_air_corridor_binary_selection.html"


def normalize_heading(heading):
    """Normalize heading to [0, 360)."""
    return heading % 360.0


def rounded_heading(heading):
    """Round heading to one decimal to avoid floating-point mismatch."""
    return round(normalize_heading(heading), 1)


def opposite_heading(heading):
    """Return opposite heading (180 degrees apart), rounded."""
    return rounded_heading(heading + 180.0)


def identify_air_corridor_edge_groups(G):
    """
    Identify air-corridor edge groups by layer + (same x or same y) + direction.

    Returns:
        tuple: (group_dict, variable_to_group_list)
            - group_dict: raw dictionary of directional groups
            - variable_to_group_list: list of (group_key, forward_edges, reverse_edges)
              where one variable corresponds to one corridor with its two direction sets.
    """
    print("\nIdentifying air corridor groups by layer/x/y and direction...")

    directional_groups = {}

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

        # Same grid_x corridor (movement along y)
        if ux == vx and uy != vy:
            corridor_axis = "x"
            fixed_index = ux
        # Same grid_y corridor (movement along x)
        elif uy == vy and ux != vx:
            corridor_axis = "y"
            fixed_index = uy
        else:
            # Skip non-axis-aligned or degenerate horizontal edges
            continue

        heading = rounded_heading(data.get("heading", 0.0))
        group_key = (u_layer, corridor_axis, fixed_index, heading)

        if group_key not in directional_groups:
            directional_groups[group_key] = []
        directional_groups[group_key].append((u, v))

    # Deterministic edge order inside each directional group
    for key in directional_groups:
        directional_groups[key] = sorted(directional_groups[key])

    variable_to_group_list = []
    processed = set()

    sorted_keys = sorted(directional_groups.keys())
    for key in sorted_keys:
        if key in processed:
            continue

        layer, axis, fixed_index, heading = key
        reverse_key = (layer, axis, fixed_index, opposite_heading(heading))

        forward_edges = directional_groups.get(key, [])
        reverse_edges = directional_groups.get(reverse_key, [])

        variable_to_group_list.append((key, forward_edges, reverse_edges))

        processed.add(key)
        if reverse_key in directional_groups:
            processed.add(reverse_key)

    print(f"   Directional groups found: {len(directional_groups)}")
    print(f"   Air corridor variables created: {len(variable_to_group_list)}")

    # Report by layer and corridor type
    layer_axis_counts = {}
    for key, _, _ in variable_to_group_list:
        layer, axis, fixed_index, heading = key
        layer_axis_counts.setdefault((layer, axis), 0)
        layer_axis_counts[(layer, axis)] += 1

    if layer_axis_counts:
        print("   Variables by layer/corridor type:")
        for (layer, axis), count in sorted(layer_axis_counts.items()):
            corridor_name = "same grid_x" if axis == "x" else "same grid_y"
            print(f"      Layer {layer}, {corridor_name}: {count}")

    # Show examples
    if variable_to_group_list:
        print("   Example variables (first 5):")
        for i, (key, forward_edges, reverse_edges) in enumerate(variable_to_group_list[:5]):
            layer, axis, fixed_index, heading = key
            print(
                f"      Variable {i}: layer={layer}, axis={axis}, fixed_index={fixed_index}, "
                f"heading={heading:.1f}°, forward_edges={len(forward_edges)}, reverse_edges={len(reverse_edges)}"
            )

    return directional_groups, variable_to_group_list


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
    binary_visualizer.visualize_3d_graph(G, edges_to_display, layer_altitudes_ft, num_layers)

    print("\n" + "=" * 70)
    print("VISUALIZATION COMPLETE")
    print("=" * 70)
    print(f"Output file: {HTML_FILENAME}")
    print(f"Binary set used: {binary_set.tolist()[:20]}..." if len(binary_set) > 20 else f"Binary set used: {binary_set.tolist()}")
    print("=" * 70)
