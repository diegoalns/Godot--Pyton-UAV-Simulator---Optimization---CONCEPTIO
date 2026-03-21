"""
Shared edge-grouping utilities for GA experiment edge-orientation variables.

This module intentionally mirrors the contiguous air-corridor segment grouping
used by Visualize_Air_Corridor_Binary_Edge_Selection_updated.py so GA and
visualization can use the same variable definition without direct file coupling.
"""

from __future__ import annotations


def identify_air_corridor_edge_groups(G):
    """
    Identify air-corridor variables by:
    - layer
    - corridor type (same grid_x or same grid_y)
    - contiguous segment ID
    - direction sign (forward/reverse)

    Returns:
        tuple: (group_dict, variable_to_group_list)
            - group_dict: dict keyed by (layer, axis, fixed_index, segment_id)
              with {"forward": [...], "reverse": [...]} edge lists.
            - variable_to_group_list: sorted list of
              (group_key, forward_edges, reverse_edges)
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

        # Same grid_x corridor (movement along y): forward if y increases.
        if ux == vx and uy != vy:
            corridor_axis = "x"
            fixed_index = ux
            direction_is_forward = vy > uy
        # Same grid_y corridor (movement along x): forward if x increases.
        elif uy == vy and ux != vx:
            corridor_axis = "y"
            fixed_index = uy
            direction_is_forward = vx > ux
        else:
            # Skip non-axis-aligned or degenerate horizontal edges.
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

    # Build contiguous segment IDs per base corridor key using undirected connectivity.
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

    # Deterministic edge order inside each direction set.
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

    # Report by layer and corridor type.
    layer_axis_counts = {}
    for key, _, _ in variable_to_group_list:
        layer, axis, _fixed_index, _segment_id = key
        layer_axis_counts.setdefault((layer, axis), 0)
        layer_axis_counts[(layer, axis)] += 1

    if layer_axis_counts:
        print("   Variables by layer/corridor type:")
        for (layer, axis), count in sorted(layer_axis_counts.items()):
            corridor_name = "same grid_x" if axis == "x" else "same grid_y"
            print(f"      Layer {layer}, {corridor_name}: {count}")

    # Report segmentation summary.
    segmented_corridors = sum(1 for _, seg_count in base_segment_counts.items() if seg_count > 1)
    total_base_corridors = len(base_segment_counts)
    print(f"   Base corridors: {total_base_corridors}")
    print(f"   Corridors split into multiple segments: {segmented_corridors}")

    # Show examples.
    if variable_to_group_list:
        print("   Example variables (first 5):")
        for i, (key, forward_edges, reverse_edges) in enumerate(variable_to_group_list[:5]):
            layer, axis, fixed_index, segment_id = key
            print(
                f"      Variable {i}: layer={layer}, axis={axis}, fixed_index={fixed_index}, segment={segment_id}, "
                f"forward_edges={len(forward_edges)}, reverse_edges={len(reverse_edges)}"
            )

    return corridor_groups, variable_to_group_list

