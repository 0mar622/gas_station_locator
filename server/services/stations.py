"""Find nearby gas stations."""

from math import asin, cos, isfinite, radians, sin, sqrt

from .getFirebase import get_stations_by_fuel


LEGACY_PRICE_FIELDS = {
    "regular": "regular_price",
    "midgrade": "midgrade_price",
    "premium": "premium_price",
    "diesel": "diesel_price",
}


def _value(field):
    key, value = next(iter(field.items()))
    if key == "mapValue":
        return {name: _value(item) for name, item in value.get("fields", {}).items()}
    if key == "arrayValue":
        return [_value(item) for item in value.get("values", [])]
    return value


def normalize_station(document, requested_fuel_type=None):
    """Normalize canonical seeded records and legacy per-fuel price records."""
    fields = {
        name: _value(value)
        for name, value in document.get("fields", {}).items()
    }
    fuel_type = str(fields.get("fuel_type", requested_fuel_type or "")).lower()
    if not fuel_type:
        return None

    price = fields.get("price")
    if price is None:
        price = fields.get(LEGACY_PRICE_FIELDS.get(fuel_type, ""))
    if price is None:
        return None

    try:
        latitude = float(fields["latitude"])
        longitude = float(fields["longitude"])
        price = float(price)
    except (KeyError, TypeError, ValueError):
        return None
    if not all(map(isfinite, (latitude, longitude, price))):
        return None

    station = {
        **fields,
        "id": fields.get("id") or document.get("name", "").rsplit("/", 1)[-1],
        "fuel_type": fuel_type,
        "latitude": latitude,
        "longitude": longitude,
        "price": price,
    }
    return station


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
        station = normalize_station(document, fuel_type)
        if station is None:
            continue
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


def closest_route_projection(
    latitude,
    longitude,
    route_coordinates,
    route_distance_miles=None,
):
    """Return distance, progress, and snapped coordinate for a route point."""
    best = (float("inf"), 0.0, None)
    route_progress = 0.0
    geometry_distance = sum(
        _distance_miles(start[1], start[0], end[1], end[0])
        for start, end in zip(route_coordinates, route_coordinates[1:])
    )
    progress_scale = (
        route_distance_miles / geometry_distance
        if route_distance_miles is not None and geometry_distance > 0
        else 1.0
    )
    for start, end in zip(route_coordinates, route_coordinates[1:]):
        segment_length = _distance_miles(start[1], start[0], end[1], end[0])
        distance, fraction = _point_to_segment_distance_and_fraction(
            latitude,
            longitude,
            start,
            end,
        )
        progress = (route_progress + fraction * segment_length) * progress_scale
        snapped = [
            start[0] + fraction * (end[0] - start[0]),
            start[1] + fraction * (end[1] - start[1]),
        ]
        if distance < best[0]:
            best = (distance, progress, snapped)
        route_progress += segment_length
    return best


def get_stations_near_route(
    route_coordinates,
    fuel_type,
    radius_miles=5,
    max_price=None,
    estimated_range_miles=None,
    route_distance_miles=None,
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

    nearby = []
    for document in get_stations_by_fuel(fuel_type):
        station = normalize_station(document, fuel_type)
        if station is None:
            continue
        latitude = station["latitude"]
        longitude = station["longitude"]
        price = station["price"]
        if max_price is not None and price > max_price:
            continue

        closest_distance, closest_progress, projection = closest_route_projection(
            latitude,
            longitude,
            route_coordinates,
            route_distance_miles,
        )

        if closest_distance > radius_miles:
            continue
        station["distance_to_route_miles"] = round(closest_distance, 2)
        station["route_progress_miles"] = round(closest_progress, 2)
        station["route_projection"] = projection
        if estimated_range_miles is not None:
            station["within_estimated_range"] = closest_progress <= estimated_range_miles
        nearby.append(station)

    return sorted(nearby, key=lambda station: station["route_progress_miles"])
