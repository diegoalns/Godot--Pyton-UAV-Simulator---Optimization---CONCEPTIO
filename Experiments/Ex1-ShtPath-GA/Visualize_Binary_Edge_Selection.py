"""
3D Lattice Graph Visualizer with Binary Edge Selection

This script loads a 3D lattice graph from a pickle file and implements a binary variable
system for visualization. Each variable represents a pair of directed arcs between two nodes,
and a binary value determines which arc from each pair is displayed.

Key Features:
- Loads graph from pickle file
- Identifies all horizontal edge pairs (bidirectional pairs)
- Creates variables: one variable per edge pair
- Binary selection: random binary set determines which arc to display from each pair
- Vertical edges always displayed (bidirectional)
- Interactive 3D Plotly visualization with direction arrows
- Color coding: Green nodes = available, Red nodes = unavailable

Configuration:
- Set USE_RANDOM_BINARY to True for random binary set, False to use provided binary set
- Set BINARY_SET to specify custom binary values (list of 0s and 1s)
- Set RANDOM_SEED for reproducible random binary sets
"""

import pandas as pd
import numpy as np
import networkx as nx
import plotly.graph_objects as go
from math import sqrt
import pickle
import webbrowser
from datetime import datetime

# --- Configuration ---

# Input file
PICKLE_FILENAME = "regular_lattice_graph.pkl"

# Binary Selection Configuration
USE_RANDOM_BINARY = True  # Boolean: If True, generate random binary set. If False, use BINARY_SET below
RANDOM_SEED = 80  # Integer: Random seed for reproducible random binary sets (used if USE_RANDOM_BINARY is True)
BINARY_SET = None  # List of integers (0s and 1s): Custom binary set to use (only used if USE_RANDOM_BINARY is False)
                    # If None and USE_RANDOM_BINARY is False, will be generated automatically

# Visualization Parameters
LAYERS_TO_DISPLAY = [0, 1, 2, 3, 4]  # List of integers: Which layers to show initially
NODE_SIZE = 5  # Integer: Size of node markers in pixels
HORIZONTAL_LINE_WIDTH = 3.5  # Float: Width of horizontal edge lines
VERTICAL_LINE_WIDTH = 2.5  # Float: Width of vertical edge lines

# Output Configuration
HTML_FILENAME = "lattice_graph_binary_selection.html"  # String: Output HTML filename

# Direction styling for horizontal edges (based on heading buckets)
DIRECTION_STYLE = {
    0: {"label": "Northbound (0°)", "color": "#1f77b4"},
    90: {"label": "Eastbound (90°)", "color": "#ff7f0e"},
    180: {"label": "Southbound (180°)", "color": "#2ca02c"},
    270: {"label": "Westbound (270°)", "color": "#9467bd"},
}

# --- Helper Functions ---

def load_graph_from_pickle(filename):
    """
    Load the graph and metadata from a pickle file.
    
    Args:
        filename: Path to the pickle file (string)
    
    Returns:
        tuple: (graph, metadata) where graph is a NetworkX DiGraph and metadata is a dict
    """
    print(f"Loading graph from {filename}...")
    try:
        with open(filename, 'rb') as f:  # Open file in binary read mode
            data = pickle.load(f)  # Load pickle data (dict with 'graph' and 'metadata' keys)
        
        graph = data['graph']  # NetworkX DiGraph object
        metadata = data.get('metadata', {})  # Dictionary: metadata about the graph (may be empty)
        
        print(f"   ✓ Graph loaded successfully")
        print(f"   ✓ Nodes: {graph.number_of_nodes()}")
        print(f"   ✓ Edges: {graph.number_of_edges()}")
        if metadata:
            print(f"   ✓ Grid dimensions: {metadata.get('grid_dimensions', 'N/A')}")
            print(f"   ✓ Created: {metadata.get('created_at', 'N/A')}")
        
        return graph, metadata  # Return tuple of graph and metadata
        
    except FileNotFoundError:
        print(f"   ✗ ERROR: File '{filename}' not found")
        raise
    except Exception as e:
        print(f"   ✗ ERROR loading graph: {e}")
        raise

def identify_edge_pairs(G):
    """
    Identify all horizontal edge pairs (bidirectional pairs) in the graph.
    
    Each pair consists of two directed arcs: (u, v) and (v, u) connecting the same two nodes.
    This function groups these pairs and creates a mapping from variable index to edge pair.
    
    Args:
        G: NetworkX DiGraph with horizontal edges (NetworkX DiGraph object)
    
    Returns:
        tuple: (edge_pairs_dict, variable_to_pair_list) where:
            - edge_pairs_dict: Dictionary mapping pair_key (tuple) to list of edges [(u1,v1), (u2,v2)]
            - variable_to_pair_list: List of tuples, each containing (pair_key, edge1, edge2)
    """
    print("\nIdentifying horizontal edge pairs...")
    
    # Dictionary to store edge pairs: key is canonical pair (sorted node IDs), value is list of edges
    edge_pairs_dict = {}  # Dictionary: key is tuple(sorted([u, v])), value is list of tuples (u, v)
    
    # Iterate through all horizontal edges
    for u, v, data in G.edges(data=True):  # u: source node (string), v: target node (string), data: edge attributes (dict)
        if data.get('layer_type') == 'Horizontal':  # Boolean check: only process horizontal edges
            # Create canonical pair key (sorted node IDs) to identify bidirectional pairs
            pair_key = tuple(sorted([u, v]))  # Tuple of two strings: sorted node IDs
            
            if pair_key not in edge_pairs_dict:
                # First edge of this pair encountered - initialize list
                edge_pairs_dict[pair_key] = []  # Initialize empty list for this pair
            
            # Add this edge to the pair
            edge_pairs_dict[pair_key].append((u, v))  # Append tuple (source, target) to list
    
    # Create variable mapping: each variable corresponds to one edge pair
    variable_to_pair_list = []  # List of tuples: (pair_key, edge1, edge2) for each variable
    pair_count = 0  # Integer: counter for number of pairs found
    
    for pair_key, edges in edge_pairs_dict.items():  # Iterate through all edge pairs
        if len(edges) == 2:
            # Perfect bidirectional pair: two edges (u, v) and (v, u)
            variable_to_pair_list.append((pair_key, edges[0], edges[1]))  # Store pair with both edges
            pair_count += 1
        elif len(edges) == 1:
            # Unidirectional edge (only one direction exists)
            # Create a variable with one edge and None for the reverse
            variable_to_pair_list.append((pair_key, edges[0], None))  # Store with None for missing reverse
            pair_count += 1
        else:
            # Multiple edges between same pair (shouldn't happen in regular lattice)
            print(f"   WARNING: Pair {pair_key} has {len(edges)} edges (expected 1 or 2)")
            # Take first two edges
            variable_to_pair_list.append((pair_key, edges[0], edges[1] if len(edges) > 1 else None))
            pair_count += 1
    
    print(f"   Found {pair_count} edge pair variables")
    print(f"   Total horizontal edges: {sum(len(edges) for edges in edge_pairs_dict.values())}")
    
    return edge_pairs_dict, variable_to_pair_list  # Return both dictionaries

def generate_binary_set(num_variables, use_random=True, seed=None, custom_set=None):
    """
    Generate or use a binary set for edge selection.
    
    Args:
        num_variables: Number of variables (edge pairs) (integer)
        use_random: Boolean flag - If True, generate random binary set. If False, use custom_set
        seed: Integer - Random seed for reproducible random generation (used if use_random is True)
        custom_set: List of integers (0s and 1s) - Custom binary set to use (only if use_random is False)
    
    Returns:
        numpy.ndarray: Array of binary values (0s and 1s) with shape (num_variables,)
    """
    print(f"\nGenerating binary set for {num_variables} variables...")
    
    if use_random:
        # Generate random binary set
        if seed is not None:
            np.random.seed(seed)  # Set random seed for reproducibility
            print(f"   Using random seed: {seed}")
        
        binary_set = np.random.randint(0, 2, size=num_variables)  # numpy array: random 0s and 1s
        print(f"   Generated random binary set")
    else:
        # Use custom binary set
        if custom_set is not None:
            if len(custom_set) != num_variables:
                print(f"   WARNING: Custom binary set length ({len(custom_set)}) != num_variables ({num_variables})")
                print(f"   Padding or truncating to match...")
                # Pad with zeros or truncate
                if len(custom_set) < num_variables:
                    custom_set = list(custom_set) + [0] * (num_variables - len(custom_set))
                else:
                    custom_set = custom_set[:num_variables]
            
            binary_set = np.array(custom_set, dtype=int)  # Convert to numpy array of integers
            print(f"   Using custom binary set")
        else:
            # Generate default binary set (all zeros)
            binary_set = np.zeros(num_variables, dtype=int)  # numpy array: all zeros
            print(f"   No custom set provided, using all zeros")
    
    # Print statistics
    num_zeros = np.sum(binary_set == 0)  # Integer: count of zeros
    num_ones = np.sum(binary_set == 1)  # Integer: count of ones
    print(f"   Binary set statistics: {num_zeros} zeros, {num_ones} ones")
    print(f"   First 10 values: {binary_set[:10].tolist()}")
    
    return binary_set  # Return numpy array of binary values

def select_edges_from_binary(variable_to_pair_list, binary_set):
    """
    Select which edges to display based on binary set.
    
    For each variable (edge pair), the binary value determines which arc to display:
    - 0: Display first arc (edge1)
    - 1: Display second arc (edge2)
    
    Args:
        variable_to_pair_list: List of tuples (pair_key, edge1, edge2) - one per variable
        binary_set: numpy.ndarray of binary values (0s and 1s) - one per variable
    
    Returns:
        set: Set of edges (tuples (u, v)) to display
    """
    print("\nSelecting edges based on binary set...")
    
    edges_to_display = set()  # Set of tuples (u, v): edges that will be displayed
    
    for var_idx, (pair_key, edge1, edge2) in enumerate(variable_to_pair_list):  # Iterate through all variables
        binary_value = binary_set[var_idx]  # Integer: binary value (0 or 1) for this variable
        
        if binary_value == 0:
            # Display first arc (edge1)
            if edge1 is not None:
                edges_to_display.add(edge1)  # Add edge1 tuple to display set
        elif binary_value == 1:
            # Display second arc (edge2)
            if edge2 is not None:
                edges_to_display.add(edge2)  # Add edge2 tuple to display set
        else:
            print(f"   WARNING: Invalid binary value {binary_value} at variable {var_idx}")
    
    print(f"   Selected {len(edges_to_display)} edges to display")
    
    return edges_to_display  # Return set of edges to display

def get_layer_altitudes_from_graph(G):
    """
    Extract layer altitudes from graph nodes.
    
    Args:
        G: NetworkX DiGraph with node altitude_ft attribute (NetworkX DiGraph object)
    
    Returns:
        list: List of floats - altitudes in feet for each layer (indexed by layer number)
    """
    layer_altitudes = {}  # Dictionary: key is layer number (int), value is altitude in feet (float)
    for node_id, data in G.nodes(data=True):  # Iterate through all nodes
        layer = data.get('layer', 0)  # Integer: layer number (default 0)
        altitude_ft = data.get('altitude_ft', 0)  # Float: altitude in feet (default 0)
        if layer not in layer_altitudes:  # Check if we've seen this layer before
            layer_altitudes[layer] = altitude_ft  # Store altitude for this layer
    
    # Convert to list, sorted by layer number
    max_layer = max(layer_altitudes.keys()) if layer_altitudes else 0  # Integer: maximum layer number
    altitudes = [layer_altitudes.get(i, 0) for i in range(max_layer + 1)]  # List of floats: altitudes for each layer
    return altitudes  # Return list of altitudes

def get_num_layers_from_graph(G):
    """
    Get the number of layers from the graph.
    
    Args:
        G: NetworkX DiGraph with node layer attribute (NetworkX DiGraph object)
    
    Returns:
        int: Number of layers (integer)
    """
    max_layer = max(data.get('layer', 0) for _, data in G.nodes(data=True))  # Integer: maximum layer number
    return max_layer + 1  # Return number of layers (layers are 0-indexed)


def get_direction_bucket(heading):
    """
    Convert a heading value into the nearest cardinal bucket: 0, 90, 180, or 270.
    """
    normalized = heading % 360.0
    cardinal_headings = [0, 90, 180, 270]
    return min(
        cardinal_headings,
        key=lambda cardinal: min(abs(normalized - cardinal), 360.0 - abs(normalized - cardinal))
    )

# --- Visualization ---

def visualize_3d_graph(G, edges_to_display, layer_altitudes_ft, num_layers):
    """
    Create interactive 3D Plotly visualization of the graph with selected edges.
    
    This function visualizes only the edges specified in edges_to_display, while
    vertical edges are always displayed. Uses the same visualization method as
    Visualize_Lattice_Graph.py.
    
    Args:
        G: NetworkX DiGraph to visualize (NetworkX DiGraph object)
        edges_to_display: Set of tuples (u, v) - edges that should be displayed
        layer_altitudes_ft: List of floats - altitudes in feet for each layer
        num_layers: Integer - number of layers in the graph
    """
    print("\nGenerating interactive 3D Plotly visualization...")
    
    # Create DataFrame from nodes
    nodes_df = pd.DataFrame.from_dict(dict(G.nodes(data=True)), orient='index')  # pandas DataFrame: node data
    
    print(f"   Total nodes: {len(nodes_df)}")
    print(f"   Total edges in graph: {G.number_of_edges()}")
    print(f"   Edges to display: {len(edges_to_display)}")
    
    # --- Node traces by layer ---
    node_traces = []  # List of Plotly Scatter3d traces: one per layer
    nodes_df['color'] = nodes_df['available'].apply(lambda x: 'green' if x else 'red')  # pandas Series: color for each node
    
    for layer in range(num_layers):  # Iterate through all layers
        layer_nodes = nodes_df[nodes_df['layer'] == layer].copy()  # pandas DataFrame: nodes in this layer
        altitude_ft = layer_altitudes_ft[layer] if layer < len(layer_altitudes_ft) else 0  # Float: altitude in feet
        
        node_trace = go.Scatter3d(  # Create 3D scatter plot trace for nodes
            x=layer_nodes['lon'],  # pandas Series: longitude coordinates
            y=layer_nodes['lat'],  # pandas Series: latitude coordinates
            z=layer_nodes['altitude'],  # pandas Series: altitude coordinates in meters
            mode='markers',  # String: display mode (markers only, no lines)
            name=f'L{layer} Nodes ({altitude_ft}ft)',  # String: trace name for legend
            legendgroup=f'nodes_layer{layer}',  # String: group name for legend grouping
            marker=dict(  # Dictionary: marker properties
                symbol='circle',  # String: marker symbol shape
                size=NODE_SIZE,  # Integer: marker size in pixels
                color=layer_nodes['color'],  # pandas Series: marker colors
                opacity=0.6  # Float: marker opacity (0-1)
            ),
            hovertemplate='<b>Node:</b> %{text}<br>' +  # String: HTML template for hover tooltip
                          '<b>Grid Position:</b> (X%{customdata[0]}, Y%{customdata[1]})<br>' +
                          '<b>Layer:</b> %{customdata[2]}<br>' +
                          '<b>Lat/Lon:</b> (%{y:.6f}, %{x:.6f})<br>' +
                          '<b>Altitude:</b> %{z:.1f}m (%{customdata[5]:.0f}ft)<br>' +
                          '<b>Available:</b> %{customdata[6]}<br>' +
                          '<b>FAA Ceiling:</b> %{customdata[7]:.0f}ft<br>' +
                          '<b>Max Obstacle:</b> %{customdata[8]:.0f}ft<extra></extra>',
            text=layer_nodes['label'],  # pandas Series: text labels for nodes
            customdata=layer_nodes[['grid_x', 'grid_y', 'layer', 'lat', 'lon', 
                                   'altitude_ft', 'available', 'faa_ceiling_ft', 'max_obstacle_ft']],  # pandas DataFrame: custom data for hover
            visible=True if layer in LAYERS_TO_DISPLAY else 'legendonly'  # Boolean or string: visibility state
        )
        node_traces.append(node_trace)  # Add trace to list
        print(f"   Layer {layer}: {len(layer_nodes)} nodes")
    
    # --- Edge traces ---
    edge_traces = []  # List of Plotly traces: edges and direction arrows
    
    # Collect cone data for direction arrows by heading bucket
    cone_data_by_layer_dir = {
        layer: {
            heading: {'x': [], 'y': [], 'z': [], 'u': [], 'v': [], 'w': [], 'text': []}
            for heading in DIRECTION_STYLE
        }
        for layer in range(num_layers)
    }
    direction_legend_shown = set()
    
    # Horizontal edges by layer (only display selected edges)
    print("   Creating edge traces...")
    for layer in range(num_layers):  # Iterate through all layers
        h_by_dir = {
            heading: {'x': [], 'y': [], 'z': [], 'info': [], 'count': 0}
            for heading in DIRECTION_STYLE
        }
        
        for u, v, data in G.edges(data=True):  # Iterate through all edges in graph
            if data.get('layer_type') == 'Horizontal':  # Boolean check: only process horizontal edges
                u_layer = G.nodes[u]['layer']  # Integer: layer of source node
                
                if u_layer == layer:  # Check if edge belongs to this layer
                    # Check if this edge should be displayed
                    if (u, v) in edges_to_display:  # Boolean check: is edge in display set?
                        u_data = G.nodes[u]  # Dictionary: source node attributes
                        v_data = G.nodes[v]  # Dictionary: target node attributes
                        
                        heading = data.get('heading', 0)  # Float: geographic heading in degrees
                        direction_bucket = get_direction_bucket(heading)
                        style = DIRECTION_STYLE[direction_bucket]
                        length = data.get('length', 0)  # Float: edge length in meters
                        info = (
                            f"{u} → {v} | Heading: {heading:.1f}° | "
                            f"Direction: {style['label']} | Length: {length:.1f}m"
                        )
                        h_by_dir[direction_bucket]['x'].extend([u_data['lon'], v_data['lon'], None])
                        h_by_dir[direction_bucket]['y'].extend([u_data['lat'], v_data['lat'], None])
                        h_by_dir[direction_bucket]['z'].extend([u_data['altitude'], v_data['altitude'], None])
                        h_by_dir[direction_bucket]['info'].extend([info, info, ''])
                        h_by_dir[direction_bucket]['count'] += 1
                        
                        # Add cone marker at endpoint showing direction
                        # Place cone 80% along the edge towards the endpoint
                        cone_pos_x = u_data['lon'] + 0.8 * (v_data['lon'] - u_data['lon'])  # Float: cone x position
                        cone_pos_y = u_data['lat'] + 0.8 * (v_data['lat'] - u_data['lat'])  # Float: cone y position
                        cone_pos_z = u_data['altitude'] + 0.8 * (v_data['altitude'] - u_data['altitude'])  # Float: cone z position
                        
                        # Direction vector (normalized)
                        dx = v_data['lon'] - u_data['lon']  # Float: x component of direction vector
                        dy = v_data['lat'] - u_data['lat']  # Float: y component of direction vector
                        dz = v_data['altitude'] - u_data['altitude']  # Float: z component of direction vector
                        norm = sqrt(dx**2 + dy**2 + dz**2)  # Float: magnitude of direction vector
                        if norm > 0:  # Check to avoid division by zero
                            dx, dy, dz = dx/norm, dy/norm, dz/norm  # Normalize direction vector (unit vector)
                        
                        # Store cone data for this layer
                        cone_data_by_layer_dir[layer][direction_bucket]['x'].append(cone_pos_x)
                        cone_data_by_layer_dir[layer][direction_bucket]['y'].append(cone_pos_y)
                        cone_data_by_layer_dir[layer][direction_bucket]['z'].append(cone_pos_z)
                        cone_data_by_layer_dir[layer][direction_bucket]['u'].append(dx * 0.002)
                        cone_data_by_layer_dir[layer][direction_bucket]['v'].append(dy * 0.002)
                        cone_data_by_layer_dir[layer][direction_bucket]['w'].append(dz * 0.002)
                        cone_data_by_layer_dir[layer][direction_bucket]['text'].append(f"{u} → {v}")
        
        altitude_ft = layer_altitudes_ft[layer] if layer < len(layer_altitudes_ft) else 0
        layer_horizontal_count = 0
        layer_arrow_count = 0

        for direction_bucket, style in DIRECTION_STYLE.items():
            direction_coords = h_by_dir[direction_bucket]
            direction_cones = cone_data_by_layer_dir[layer][direction_bucket]

            if direction_coords['x']:
                show_direction_legend = style['label'] not in direction_legend_shown
                edge_traces.append(go.Scatter3d(
                    x=direction_coords['x'],
                    y=direction_coords['y'],
                    z=direction_coords['z'],
                    mode='lines',
                    name=style['label'],
                    legendgroup=f"dir_{direction_bucket}",
                    showlegend=show_direction_legend,
                    line=dict(color=style['color'], width=HORIZONTAL_LINE_WIDTH),
                    text=direction_coords['info'],
                    hovertemplate='<b>Horizontal Edge</b><br>%{text}<extra></extra>',
                    opacity=0.45,
                    visible=True if layer in LAYERS_TO_DISPLAY else 'legendonly'
                ))
                if show_direction_legend:
                    direction_legend_shown.add(style['label'])

                layer_horizontal_count += direction_coords['count']

            if direction_cones['x']:
                edge_traces.append(go.Cone(
                    x=direction_cones['x'],
                    y=direction_cones['y'],
                    z=direction_cones['z'],
                    u=direction_cones['u'],
                    v=direction_cones['v'],
                    w=direction_cones['w'],
                    name=f"L{layer} {style['label']} Arrows ({altitude_ft}ft)",
                    legendgroup=f'arrows_layer{layer}_{direction_bucket}',
                    showlegend=False,
                    showscale=False,
                    colorscale=[[0, style['color']], [1, style['color']]],
                    sizemode='absolute',
                    sizeref=0.00015,
                    text=direction_cones['text'],
                    hovertemplate='<b>Direction Arrow</b><br>%{text}<extra></extra>',
                    visible=True if layer in LAYERS_TO_DISPLAY else 'legendonly',
                    opacity=0.7
                ))
                layer_arrow_count += len(direction_cones['x'])

        if layer_horizontal_count > 0:
            print(f"      Layer {layer}: {layer_horizontal_count} horizontal edges (color-coded by direction)")
        if layer_arrow_count > 0:
            print(f"      Layer {layer}: {layer_arrow_count} direction arrows")
    
    # Vertical edges (always displayed)
    v_coords = {'x': [], 'y': [], 'z': []}  # Dictionary: coordinate lists for vertical edge lines
    v_info = []  # List of strings: hover text for vertical edges
    v_count = 0  # Integer: counter for vertical edges
    
    for u, v, data in G.edges(data=True):  # Iterate through all edges in graph
        if data.get('layer_type') == 'Vertical':  # Boolean check: only process vertical edges
            u_data = G.nodes[u]  # Dictionary: source node attributes
            v_data = G.nodes[v]  # Dictionary: target node attributes
            
            # Only show upward edges (to avoid duplicates in visualization)
            if u_data['layer'] < v_data['layer']:  # Boolean check: source layer is below target layer
                v_coords['x'].extend([u_data['lon'], v_data['lon'], None])  # Add x coordinates
                v_coords['y'].extend([u_data['lat'], v_data['lat'], None])  # Add y coordinates
                v_coords['z'].extend([u_data['altitude'], v_data['altitude'], None])  # Add z coordinates
                
                length = data.get('length', 0)  # Float: edge length in meters
                info = f"{u} ↕ {v} | Length: {length:.1f}m"  # String: hover text
                v_info.extend([info, info, ''])  # Add hover text (three times)
                v_count += 1  # Increment counter
    
    if v_coords['x']:  # Check if there are any vertical edges to display
        edge_traces.append(go.Scatter3d(  # Create 3D scatter plot trace for vertical edges
            x=v_coords['x'],  # List: x coordinates
            y=v_coords['y'],  # List: y coordinates
            z=v_coords['z'],  # List: z coordinates
            mode='lines',  # String: display mode (lines only)
            name=f'Vertical Edges',  # String: trace name for legend
            line=dict(color='red', width=VERTICAL_LINE_WIDTH),  # Dictionary: line properties
            text=v_info,  # List of strings: hover text
            hovertemplate='<b>Vertical Edge</b><br>%{text}<extra></extra>',  # String: HTML template for hover
            opacity=0.5  # Float: line opacity
        ))
        print(f"      Vertical: {v_count} edges (showing upward only)")
    
    # Create figure
    fig = go.Figure(data=edge_traces + node_traces)  # Plotly Figure: combine all traces
    
    fig.update_layout(  # Update figure layout properties
        scene=dict(  # Dictionary: 3D scene properties
            xaxis_title='Longitude (degrees)',  # String: x-axis label
            yaxis_title='Latitude (degrees)',  # String: y-axis label
            zaxis_title='Altitude (Meters)',  # String: z-axis label
            bgcolor='#f0f0f0',  # String: background color (light gray)
            aspectmode='manual',  # String: aspect ratio mode (manual control)
            aspectratio=dict(x=1, y=1, z=0.02),  # Dictionary: aspect ratios (adjusted for lat/lon coordinates)
            camera=dict(eye=dict(x=1.5, y=1.5, z=1.2))  # Dictionary: camera position
        ),
        title=f'3D Lattice Graph: {G.number_of_nodes()} nodes, {len(edges_to_display)} horizontal edges displayed | Binary Selection',  # String: plot title
        height=900,  # Integer: plot height in pixels
        showlegend=True,  # Boolean: show legend
        annotations=[
            dict(
                x=0.01,
                y=0.99,
                xref='paper',
                yref='paper',
                xanchor='left',
                yanchor='top',
                showarrow=False,
                align='left',
                bgcolor='rgba(255,255,255,0.85)',
                bordercolor='rgba(0,0,0,0.2)',
                borderwidth=1,
                font=dict(size=12),
                text=(
                    "<b>Horizontal direction colors</b><br>"
                    "<span style='color:#1f77b4'>■</span> Northbound (0°)<br>"
                    "<span style='color:#ff7f0e'>■</span> Eastbound (90°)<br>"
                    "<span style='color:#2ca02c'>■</span> Southbound (180°)<br>"
                    "<span style='color:#9467bd'>■</span> Westbound (270°)"
                ),
            )
        ]
    )
    
    # Save HTML
    fig.write_html(HTML_FILENAME, auto_open=False)  # Save figure to HTML file
    print(f"\nVisualization saved to {HTML_FILENAME}")
    
    # Open in browser
    try:
        webbrowser.open_new_tab(HTML_FILENAME)  # Open HTML file in default web browser
        print(f"Opened {HTML_FILENAME} in web browser")
    except Exception as e:
        print(f"Could not open browser automatically: {e}")

# --- Main Execution ---

if __name__ == '__main__':
    print("="*70)
    print("3D LATTICE GRAPH VISUALIZER WITH BINARY EDGE SELECTION")
    print("="*70)
    
    # Display configuration
    print(f"\nConfiguration:")
    print(f"  Binary selection: {'Random' if USE_RANDOM_BINARY else 'Custom'}")
    if USE_RANDOM_BINARY:
        print(f"  Random seed: {RANDOM_SEED}")
    print(f"  Input file: {PICKLE_FILENAME}")
    print(f"  Output file: {HTML_FILENAME}")
    
    # 1. Load graph from pickle file
    G, metadata = load_graph_from_pickle(PICKLE_FILENAME)
    
    # 2. Identify edge pairs (variables)
    edge_pairs_dict, variable_to_pair_list = identify_edge_pairs(G)
    num_variables = len(variable_to_pair_list)  # Integer: number of variables (edge pairs)
    
    # 3. Generate binary set
    binary_set = generate_binary_set(
        num_variables, 
        use_random=USE_RANDOM_BINARY, 
        seed=RANDOM_SEED if USE_RANDOM_BINARY else None,
        custom_set=BINARY_SET
    )
    
    # 4. Select edges based on binary set
    edges_to_display = select_edges_from_binary(variable_to_pair_list, binary_set)
    
    # 5. Extract layer information from graph
    layer_altitudes_ft = get_layer_altitudes_from_graph(G)
    num_layers = get_num_layers_from_graph(G)
    
    print(f"\nGraph Statistics:")
    print(f"  Total nodes: {G.number_of_nodes()}")
    print(f"  Total horizontal edges in graph: {sum(1 for _, _, d in G.edges(data=True) if d.get('layer_type') == 'Horizontal')}")
    print(f"  Edge pair variables: {num_variables}")
    print(f"  Edges displayed: {len(edges_to_display)}")
    print(f"  Number of layers: {num_layers}")
    
    # 6. Visualize graph with selected edges
    visualize_3d_graph(G, edges_to_display, layer_altitudes_ft, num_layers)
    
    print("\n" + "="*70)
    print("VISUALIZATION COMPLETE")
    print("="*70)
    print(f"Output file: {HTML_FILENAME}")
    print(f"Binary set used: {binary_set.tolist()[:20]}..." if len(binary_set) > 20 else f"Binary set used: {binary_set.tolist()}")
    print("="*70)

