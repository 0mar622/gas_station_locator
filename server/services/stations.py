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
