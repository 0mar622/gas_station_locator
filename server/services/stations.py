"""Find nearby gas stations."""

from math import asin, cos, radians, sin, sqrt

from .getFirebase import get_stations_by_fuel


def _value(field):
    return next(iter(field.values()))


def _distance_miles(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    lat_delta = lat2 - lat1
    lon_delta = lon2 - lon1
    value = sin(lat_delta / 2) ** 2 + cos(lat1) * cos(lat2) * sin(lon_delta / 2) ** 2
    return 3959 * 2 * asin(sqrt(value))


def get_nearby_stations(latitude, longitude, fuel_type, radius_miles=10, max_price=None):
    latitude = float(latitude)
    longitude = float(longitude)
    radius_miles = float(radius_miles)
    max_price = float(max_price) if max_price is not None else None

    if not fuel_type or radius_miles <= 0 or (max_price is not None and max_price < 0):
        raise ValueError("Invalid station filters")

    nearby = []
    for document in get_stations_by_fuel(fuel_type):
        station = {name: _value(value) for name, value in document["fields"].items()}
        distance = _distance_miles(
            latitude,
            longitude,
            float(station["latitude"]),
            float(station["longitude"]),
        )
        if distance <= radius_miles and (max_price is None or float(station["price"]) <= max_price):
            station["distance_miles"] = round(distance, 2)
            nearby.append(station)

    return sorted(nearby, key=lambda station: station["distance_miles"])


def _point_to_segment_distance_and_fraction(latitude, longitude, start, end):
    """Return local distance from a point to a route segment and its fraction."""
    start_lon, start_lat = start
    end_lon, end_lat = end
    scale_x = radians(1) * 3959 * cos(radians(latitude))
    scale_y = radians(1) * 3959
    start_x = (start_lon - longitude) * scale_x
    start_y = (start_lat - latitude) * scale_y
    end_x = (end_lon - longitude) * scale_x
    end_y = (end_lat - latitude) * scale_y
    delta_x = end_x - start_x
    delta_y = end_y - start_y
    segment_squared = delta_x * delta_x + delta_y * delta_y
    if segment_squared == 0:
        fraction = 0.0
    else:
        fraction = max(
            0.0,
            min(1.0, -(start_x * delta_x + start_y * delta_y) / segment_squared),
        )
    nearest_x = start_x + fraction * delta_x
    nearest_y = start_y + fraction * delta_y
    return sqrt(nearest_x * nearest_x + nearest_y * nearest_y), fraction


def get_stations_near_route(
    route_coordinates,
    fuel_type,
    radius_miles=5,
    max_price=None,
    estimated_range_miles=None,
):
    """Return matching stations within a corridor around a GeoJSON route line."""
    radius_miles = float(radius_miles)
    max_price = float(max_price) if max_price is not None else None
    if not fuel_type or not 0 < radius_miles < float("inf"):
        raise ValueError("Invalid route station filters")
    if max_price is not None and not 0 <= max_price < float("inf"):
        raise ValueError("max_price must be a finite nonnegative number")
    if estimated_range_miles is not None and (
        not 0 <= estimated_range_miles < float("inf")
    ):
        raise ValueError("estimated_range_miles must be finite and nonnegative")
    if len(route_coordinates) < 2:
        raise ValueError("Route must have at least two coordinates")

    segments = []
    route_progress = 0.0
    for start, end in zip(route_coordinates, route_coordinates[1:]):
        segment_length = _distance_miles(start[1], start[0], end[1], end[0])
        segments.append((start, end, route_progress, segment_length))
        route_progress += segment_length

    nearby = []
    for document in get_stations_by_fuel(fuel_type):
        station = {name: _value(value) for name, value in document["fields"].items()}
        latitude = float(station["latitude"])
        longitude = float(station["longitude"])
        price = float(station["price"])
        if max_price is not None and price > max_price:
            continue

        closest_distance = float("inf")
        closest_progress = 0.0
        for start, end, progress_before, segment_length in segments:
            distance, fraction = _point_to_segment_distance_and_fraction(
                latitude,
                longitude,
                start,
                end,
            )
            if distance < closest_distance:
                closest_distance = distance
                closest_progress = progress_before + fraction * segment_length

        if closest_distance > radius_miles:
            continue
        station["distance_to_route_miles"] = round(closest_distance, 2)
        station["route_progress_miles"] = round(closest_progress, 2)
        if estimated_range_miles is not None:
            station["within_estimated_range"] = closest_progress <= estimated_range_miles
        nearby.append(station)

    return sorted(nearby, key=lambda station: station["route_progress_miles"])
