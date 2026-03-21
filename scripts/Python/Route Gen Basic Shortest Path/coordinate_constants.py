"""
Shared coordinate conversion constants for the UAV Simulator.

This module contains all coordinate system parameters used across the project
to ensure consistency and eliminate duplication.

All coordinates use the same reference origin point and conversion factors.
"""

import math

# Coordinate system reference point (NYC area)
ORIGIN_LAT_DEGREES = 40.55417343
ORIGIN_LON_DEGREES = -73.99583928

# Conversion factors from degrees to meters
METERS_PER_DEGREE_LAT = 111320  # Approximate meters per degree latitude
# Adjust longitude conversion for latitude (longitude degrees get smaller toward poles)
METERS_PER_DEGREE_LON = 111320 * math.cos(math.radians(ORIGIN_LAT_DEGREES))  # ~84,613 m/deg at 40.5°N

# Legacy constant for backward compatibility (use METERS_PER_DEGREE_LAT instead)
METERS_PER_DEGREE = METERS_PER_DEGREE_LAT

# Geographic bounds for the simulation area (in degrees)
MIN_LAT_DEGREE = 40.55417343
MAX_LAT_DEGREE = 40.8875
MIN_LON_DEGREE = -73.99583928
MAX_LON_DEGREE = -73.5958

# Altitude bounds
MIN_ALT_FEET = 50
MAX_ALT_FEET = 400

# Convert altitude from feet to meters
MIN_ALT_METERS = MIN_ALT_FEET * 0.3048
MAX_ALT_METERS = MAX_ALT_FEET * 0.3048

# Grid dimensions for airspace graph
N_LAT = 100
N_LON = 100
N_ALT = 3

def get_coordinate_bounds_meters():
    """
    Get the coordinate bounds converted to meters from the origin point.
    
    Returns:
        dict: Dictionary with min/max values for x, y, z coordinates in meters
    """
    # Convert geographic bounds to meters relative to origin
    # Use latitude-adjusted conversion for accurate East-West distances
    min_lat_meters = (MIN_LAT_DEGREE - ORIGIN_LAT_DEGREES) * METERS_PER_DEGREE_LAT
    max_lat_meters = (MAX_LAT_DEGREE - ORIGIN_LAT_DEGREES) * METERS_PER_DEGREE_LAT
    min_lon_meters = (MIN_LON_DEGREE - ORIGIN_LON_DEGREES) * METERS_PER_DEGREE_LON
    max_lon_meters = (MAX_LON_DEGREE - ORIGIN_LON_DEGREES) * METERS_PER_DEGREE_LON
    
    return {
        'x_min': min_lon_meters,
        'x_max': max_lon_meters,
        'y_min': MIN_ALT_METERS,
        'y_max': MAX_ALT_METERS,
        'z_min': min_lat_meters,
        'z_max': max_lat_meters
    }

def degrees_to_meters(lat_degrees, lon_degrees):
    """
    Convert latitude/longitude degrees to meters relative to origin.
    
    Args:
        lat_degrees: Latitude in degrees
        lon_degrees: Longitude in degrees
    
    Returns:
        tuple: (x_meters, z_meters) relative to origin
    """
    # Use latitude-adjusted conversion factor for longitude (East-West distances)
    x_meters = (lon_degrees - ORIGIN_LON_DEGREES) * METERS_PER_DEGREE_LON
    z_meters = (lat_degrees - ORIGIN_LAT_DEGREES) * METERS_PER_DEGREE_LAT
    return x_meters, z_meters