"""Build a route preview and find compatible stations along it."""

import math
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from .stations import get_stations_near_route

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HEIGIT_ORS_BASE_URL = "https://api.heigit.org"
DEFAULT_ROUTE_RADIUS_MILES = 5.0
SUPPORTED_FUEL_TYPES = {"regular", "midgrade", "premium", "diesel"}
FUEL_ALIASES = {"unleaded": "regular", "gasoline": "regular", "petrol": "regular"}
load_dotenv(PROJECT_ROOT / ".env")


class RouteConfigurationError(Exception):
    """Raised when the route provider is not configured."""


class AddressNotFoundError(Exception):
    """Raised when ORS cannot resolve an address."""


class RouteNotFoundError(Exception):
    """Raised when ORS cannot produce a driving route."""


def _required_text(data, field):
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required and must be text.")
    return value.strip()


def _finite_number(data, field, *, minimum=None, exclusive_minimum=False):
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number.")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{field} must be finite.")
    if minimum is not None and (
        value <= minimum if exclusive_minimum else value < minimum
    ):
        comparison = "greater than" if exclusive_minimum else "at least"
        raise ValueError(f"{field} must be {comparison} {minimum}.")
    return value


def _validate_trip(data):
    if not isinstance(data, dict):
        raise ValueError("Send a JSON object with trip details.")

    origin = _required_text(data, "starting_location")
    destination = _required_text(data, "destination")
    raw_fuel_type = _required_text(data, "fuel_type").casefold()
    fuel_type = FUEL_ALIASES.get(raw_fuel_type, raw_fuel_type)
    if fuel_type not in SUPPORTED_FUEL_TYPES:
        raise ValueError("fuel_type must be regular, midgrade, premium, or diesel.")

    current_fuel_gallons = _finite_number(data, "current_fuel_gallons", minimum=0)
    vehicle_mpg = _finite_number(
        data,
        "vehicle_mpg",
        minimum=0,
        exclusive_minimum=True,
    )
    radius_miles = _finite_number(
        {"radius_miles": data.get("radius_miles", DEFAULT_ROUTE_RADIUS_MILES)},
        "radius_miles",
        minimum=0,
        exclusive_minimum=True,
    )
    max_price = None
    if data.get("max_price") is not None:
        max_price = _finite_number(data, "max_price", minimum=0)

    return {
        "starting_location": origin,
        "destination": destination,
        "fuel_type": fuel_type,
        "current_fuel_gallons": current_fuel_gallons,
        "vehicle_mpg": vehicle_mpg,
        "radius_miles": radius_miles,
        "max_price": max_price,
    }


def _geocode(session, address, api_key):
    response = session.get(
        f"{HEIGIT_ORS_BASE_URL}/pelias/v1/search",
        params={"text": address, "size": 1, "boundary.country": "USA"},
        headers={"Authorization": api_key},
        timeout=(5, 20),
    )
    response.raise_for_status()
    try:
        features = response.json().get("features", [])
    except (AttributeError, ValueError) as exc:
        raise requests.RequestException("ORS returned an invalid geocoding response") from exc
    if not features:
        raise AddressNotFoundError(f"Could not find an address match for: {address}")

    try:
        feature = features[0]
        geometry = feature["geometry"]
        coordinates = geometry["coordinates"]
        if len(coordinates) < 2:
            raise ValueError("missing coordinates")
        longitude, latitude = map(float, coordinates[:2])
        label = feature.get("properties", {}).get("label", address)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise requests.RequestException("ORS geocoding response has invalid coordinates") from exc
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        raise requests.RequestException("ORS geocoding response has invalid coordinates")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise requests.RequestException("ORS geocoding response coordinates are out of bounds")
    return {"label": label, "latitude": latitude, "longitude": longitude}


def _get_route(session, origin, destination, api_key):
    response = session.post(
        f"{HEIGIT_ORS_BASE_URL}/openrouteservice/v2/directions/driving-car/geojson",
        json={
            "coordinates": [
                [origin["longitude"], origin["latitude"]],
                [destination["longitude"], destination["latitude"]],
            ],
            "instructions": False,
        },
        headers={"Authorization": api_key, "Content-Type": "application/json"},
        timeout=(5, 30),
    )
    response.raise_for_status()
    try:
        route = response.json()
        if not route.get("features"):
            raise RouteNotFoundError("ORS could not find a driving route for these addresses.")
        feature = route["features"][0]
        if not isinstance(feature, dict):
            raise TypeError("route feature is not an object")
        coordinates = feature["geometry"]["coordinates"]
        if feature["geometry"].get("type") != "LineString":
            raise ValueError("route geometry is not a LineString")
        summary = feature["properties"]["summary"]
        distance_meters = float(summary["distance"])
        duration_seconds = float(summary["duration"])
        if len(coordinates) < 2:
            raise ValueError("route has fewer than two coordinates")
        for point in coordinates:
            longitude, latitude = map(float, point[:2])
            if (
                not math.isfinite(latitude)
                or not math.isfinite(longitude)
                or not -90 <= latitude <= 90
                or not -180 <= longitude <= 180
            ):
                raise ValueError("route has an invalid coordinate")
    except RouteNotFoundError:
        raise
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise requests.RequestException("ORS returned an invalid route response") from exc
    if not math.isfinite(distance_meters) or not math.isfinite(duration_seconds):
        raise requests.RequestException("ORS route response is missing valid route geometry")
    return route, distance_meters, duration_seconds, coordinates


def plan_trip(data):
    """Return a route preview and nearby stations without saving a trip."""
    trip = _validate_trip(data)
    api_key = os.getenv("HEIGIT_API_KEY")
    if not api_key:
        raise RouteConfigurationError("HEIGIT_API_KEY is not configured")

    with requests.Session() as session:
        origin = _geocode(session, trip["starting_location"], api_key)
        destination = _geocode(session, trip["destination"], api_key)
        route, distance_meters, duration_seconds, coordinates = _get_route(
            session,
            origin,
            destination,
            api_key,
        )

    estimated_range_miles = trip["current_fuel_gallons"] * trip["vehicle_mpg"]
    stations = get_stations_near_route(
        coordinates,
        trip["fuel_type"],
        radius_miles=trip["radius_miles"],
        max_price=trip["max_price"],
        estimated_range_miles=estimated_range_miles,
    )
    return {
        "route": route,
        "origin": origin,
        "destination": destination,
        "distance_miles": round(distance_meters / 1609.344, 2),
        "duration_minutes": round(duration_seconds / 60, 1),
        "estimated_range_miles": round(estimated_range_miles, 2),
        "radius_miles": trip["radius_miles"],
        "price_note": "Station prices are synthetic EIA-based estimates, not live pump prices.",
        "stations": stations,
    }
