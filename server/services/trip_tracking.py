"""Create and update persisted fuel-aware trips."""

import math
import os
from datetime import datetime, timezone

import requests
from requests.exceptions import RequestException

from .routing import (
    RouteConfigurationError,
    _get_matrix_distances,
    _get_route,
    plan_trip,
    recommend_safe_stations,
    validate_active_trip,
)
from .stations import _distance_miles, closest_route_projection
from .trip import (
    TripConflictError,
    create_active_trip,
    load_active_trip,
    save_trip_update,
)

FUEL_RESERVE_FRACTION = 0.10
MAX_GPS_ACCURACY_METERS = 50.0
OFF_ROUTE_MILES = 0.5
STATION_REFRESH_MILES = 0.5
ARRIVAL_RADIUS_MILES = 0.1
METERS_PER_MILE = 1609.344


def _finite_number(data, field, *, minimum=0):
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number.")
    value = float(value)
    if not math.isfinite(value) or value < minimum:
        raise ValueError(f"{field} must be finite and at least {minimum}.")
    return value


def _parse_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("observed_at is required as an ISO 8601 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("observed_at must be an ISO 8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise ValueError("observed_at must include a timezone.")
    return parsed.astimezone(timezone.utc).isoformat()


def _remaining_trip_values(state):
    progress = float(state.get("route_progress_miles", 0.0))
    remaining_miles = max(0.0, float(state["route_distance_miles"]) - progress)
    mpg = float(state["vehicle_mpg"])
    current_gallons = float(state["current_fuel_gallons"])
    reserve_gallons = float(state["tank_capacity_gallons"]) * FUEL_RESERVE_FRACTION
    required_gallons = remaining_miles / mpg
    additional_gallons = max(0.0, required_gallons + reserve_gallons - current_gallons)
    stations = state.get("station_recommendations", [])
    price = stations[0]["price"] if stations else None
    return {
        "route_miles_remaining": round(remaining_miles, 2),
        "fuel_needed_gallons": round(required_gallons, 2),
        "fuel_remaining_gallons": round(current_gallons, 2),
        "estimated_range_miles": round(current_gallons * mpg, 2),
        "safe_range_miles": round(max(0.0, current_gallons - reserve_gallons) * mpg, 2),
        "additional_gallons_needed": round(additional_gallons, 2),
        "estimated_trip_consumption_cost_usd": (
            round(required_gallons * price, 2) if price is not None else None
        ),
        "estimated_additional_purchase_cost_usd": (
            round(additional_gallons * price, 2) if price is not None else None
        ),
        "cost_price_assumption": (
            "Uses the next recommended station price as a proxy for all remaining fuel."
            if price is not None
            else "Unavailable until a reachable station price is found."
        ),
    }


def _public_state(state):
    result = {
        "trip_id": state["trip_id"],
        "status": state.get("status", "active"),
        "route": state.get("route"),
        "origin": state.get("origin"),
        "destination": state.get("destination_label"),
        "fuel_type": state.get("fuel_type"),
        "vehicle_mpg": state.get("vehicle_mpg"),
        "tank_capacity_gallons": state.get("tank_capacity_gallons"),
        "distance_traveled_miles": round(float(state.get("distance_traveled_miles", 0)), 2),
        "station_status": state.get("station_status", "unavailable"),
        "stations": state.get("station_recommendations", []),
        "current_location": state.get("current_location"),
        "last_update_at": state.get("last_update_at"),
        "warning": state.get("warning"),
        "price_note": "Station prices are synthetic EIA-based estimates, not live pump prices.",
    }
    result.update(_remaining_trip_values(state))
    return result


def start_active_trip(data):
    trip = validate_active_trip(data)
    plan = plan_trip(trip)
    coordinates = plan["route"]["features"][0]["geometry"]["coordinates"]
    origin = plan["origin"]
    destination = plan["destination"]
    recommendations = recommend_safe_stations(
        coordinates,
        trip["fuel_type"],
        origin,
        0.0,
        trip["current_fuel_gallons"],
        trip["tank_capacity_gallons"],
        trip["vehicle_mpg"],
        radius_miles=trip["radius_miles"],
        max_price=trip["max_price"],
        route_distance_miles=plan["distance_miles"],
    )
    now = datetime.now(timezone.utc).isoformat()
    state = {
        "status": "active",
        "starting_location": trip["starting_location"],
        "destination_label": destination["label"],
        "origin": origin,
        "destination_coordinates": {
            "latitude": destination["latitude"],
            "longitude": destination["longitude"],
        },
        "fuel_type": trip["fuel_type"],
        "vehicle_mpg": trip["vehicle_mpg"],
        "tank_capacity_gallons": trip["tank_capacity_gallons"],
        "current_fuel_gallons": trip["current_fuel_gallons"],
        "route": plan["route"],
        "route_coordinates": coordinates,
        "route_distance_miles": plan["distance_miles"],
        "route_duration_minutes": plan["duration_minutes"],
        "route_progress_miles": 0.0,
        "last_counted_route_progress_miles": 0.0,
        "distance_traveled_miles": 0.0,
        "current_location": {
            "latitude": origin["latitude"],
            "longitude": origin["longitude"],
        },
        "last_update_location": {
            "latitude": origin["latitude"],
            "longitude": origin["longitude"],
        },
        "last_update_at": now,
        "last_update_id": "trip-start",
        "last_rank_refresh_miles": 0.0,
        "recommendation_origin_progress_miles": 0.0,
        "station_recommendations": recommendations,
        "station_status": "recommended" if recommendations else "no_safe_station",
        "off_route_count": 0,
        "arrival_count": 0,
        "radius_miles": trip["radius_miles"],
        "max_price": trip["max_price"],
        "updated_at": now,
    }
    if not recommendations:
        state["warning"] = "No station is reachable while keeping the 10% fuel reserve."
    document, token = create_active_trip(state)
    result = _public_state(document)
    result["access_token"] = token
    result["status"] = "created"
    return result


def _refresh_recommendations(state):
    recommendations = recommend_safe_stations(
        state["route_coordinates"],
        state["fuel_type"],
        state["current_location"],
        state["route_progress_miles"],
        state["current_fuel_gallons"],
        state["tank_capacity_gallons"],
        state["vehicle_mpg"],
        radius_miles=state["radius_miles"],
        max_price=state.get("max_price"),
        route_distance_miles=state["route_distance_miles"],
    )
    state["station_recommendations"] = recommendations
    state["station_status"] = "recommended" if recommendations else "no_safe_station"
    state["last_rank_refresh_miles"] = state["distance_traveled_miles"]
    state["recommendation_origin_progress_miles"] = state["route_progress_miles"]
    if recommendations:
        state.pop("warning", None)
    else:
        state["warning"] = "No station is reachable while keeping the 10% fuel reserve."


def _adjust_cached_recommendations(state):
    progress_delta = max(
        0.0,
        state["route_progress_miles"] - state["recommendation_origin_progress_miles"],
    )
    safe_range = max(
        0.0,
        state["current_fuel_gallons"] - state["tank_capacity_gallons"] * FUEL_RESERVE_FRACTION,
    ) * state["vehicle_mpg"]
    stations = []
    for station in state.get("station_recommendations", []):
        updated = dict(station)
        updated["driving_distance_miles"] = round(
            max(0.0, station["driving_distance_miles"] - progress_delta),
            2,
        )
        if updated["driving_distance_miles"] <= safe_range:
            stations.append(updated)
    state["station_recommendations"] = stations
    state["station_status"] = "recommended" if stations else "no_safe_station"
    if stations:
        state.pop("warning", None)
    else:
        state["warning"] = "No station is reachable while keeping the 10% fuel reserve."


def _reroute_from(current_location, destination, api_key):
    with requests.Session() as session:
        route, distance_meters, duration_seconds, coordinates = _get_route(
            session,
            current_location,
            destination,
            api_key,
        )
    return route, distance_meters / METERS_PER_MILE, duration_seconds / 60, coordinates


def update_active_trip(trip_id, token, data):
    if not isinstance(data, dict):
        raise ValueError("Send a JSON object with GPS progress.")
    update_id = data.get("update_id")
    if not isinstance(update_id, str) or not update_id.strip():
        raise ValueError("update_id is required.")
    latitude = _finite_number(data, "latitude", minimum=-90)
    longitude = _finite_number(data, "longitude", minimum=-180)
    if latitude > 90 or longitude > 180:
        raise ValueError("GPS coordinates are out of bounds.")
    accuracy = _finite_number(data, "accuracy_meters")
    observed_at = _parse_timestamp(data.get("observed_at"))
    gallons_added = _finite_number(data, "gallons_added") if data.get("gallons_added") is not None else 0.0

    state = load_active_trip(trip_id, token)
    if state.get("status") == "completed":
        raise ValueError("This trip is already completed.")
    if state.get("last_update_id") == update_id:
        return {**_public_state(state), "update_status": "duplicate"}
    if observed_at <= state.get("last_update_at", ""):
        return {**_public_state(state), "update_status": "stale"}

    old_fuel = float(state["current_fuel_gallons"])

    current_location = {"latitude": latitude, "longitude": longitude}
    accurate = accuracy <= MAX_GPS_ACCURACY_METERS
    moved_miles = 0.0
    rerouted = False
    returned_to_route = False
    if accurate:
        distance_from_route, progress, _ = closest_route_projection(
            latitude,
            longitude,
            state["route_coordinates"],
            state["route_distance_miles"],
        )
        previous_location = state["last_update_location"]
        if distance_from_route <= OFF_ROUTE_MILES:
            returned_to_route = state.get("station_status") in {
                "off_route",
                "route_unavailable",
                "unavailable",
            }
            progress_delta = abs(
                progress - float(state.get("last_counted_route_progress_miles", 0.0))
            )
            movement_threshold = max(0.02, 2 * accuracy / METERS_PER_MILE)
            if progress_delta >= movement_threshold:
                moved_miles = progress_delta
                state["last_counted_route_progress_miles"] = progress
            state["route_progress_miles"] = progress
            state["off_route_count"] = 0
        else:
            displacement = _distance_miles(
                previous_location["latitude"],
                previous_location["longitude"],
                latitude,
                longitude,
            )
            movement_threshold = max(0.02, 2 * accuracy / METERS_PER_MILE)
            if displacement >= movement_threshold:
                moved_miles = displacement
            state["off_route_count"] = int(state.get("off_route_count", 0)) + 1
            state["warning"] = "Off the planned route; recalculating after another accurate update."
            state["station_recommendations"] = []
            state["station_status"] = "off_route"

        state["last_update_location"] = current_location
        state["current_location"] = current_location
        state["distance_traveled_miles"] = float(state["distance_traveled_miles"]) + moved_miles
        state["current_fuel_gallons"] = max(
            0.0,
            old_fuel - moved_miles / float(state["vehicle_mpg"]),
        )
        if state["off_route_count"] >= 2:
            api_key = os.getenv("HEIGIT_API_KEY")
            if not api_key:
                raise RouteConfigurationError("HEIGIT_API_KEY is not configured")
            destination = {
                "latitude": state["destination_coordinates"]["latitude"],
                "longitude": state["destination_coordinates"]["longitude"],
            }
            try:
                route, distance, duration, coordinates = _reroute_from(
                    current_location,
                    destination,
                    api_key,
                )
            except RequestException:
                state["station_status"] = "route_unavailable"
                state["station_recommendations"] = []
                state["warning"] = "The route could not be refreshed; safe stations are unavailable."
            else:
                state.update({
                    "route": route,
                    "route_coordinates": coordinates,
                    "route_distance_miles": round(distance, 2),
                    "route_duration_minutes": round(duration, 1),
                    "route_progress_miles": 0.0,
                    "last_counted_route_progress_miles": 0.0,
                    "off_route_count": 0,
                    "warning": None,
                })
                rerouted = True
    else:
        state["warning"] = "GPS update ignored for distance tracking because accuracy exceeds 50 meters."

    if state["current_fuel_gallons"] + gallons_added > float(state["tank_capacity_gallons"]) + 1e-9:
        raise ValueError("gallons_added would exceed tank capacity.")
    state["current_fuel_gallons"] += gallons_added
    if gallons_added:
        state["last_refuel_gallons"] = gallons_added
    state["last_update_id"] = update_id
    state["last_update_at"] = observed_at
    state["updated_at"] = datetime.now(timezone.utc).isoformat()

    destination = state["destination_coordinates"]
    if accurate and _distance_miles(
        latitude,
        longitude,
        destination["latitude"],
        destination["longitude"],
    ) <= ARRIVAL_RADIUS_MILES:
        state["arrival_count"] = int(state.get("arrival_count", 0)) + 1
        if state["arrival_count"] >= 2:
            state["status"] = "completed"
    elif accurate:
        state["arrival_count"] = 0

    refresh = (
        gallons_added > 0
        or rerouted
        or returned_to_route
        or state["distance_traveled_miles"] - float(state["last_rank_refresh_miles"])
        >= STATION_REFRESH_MILES
    )
    can_rank = (
        state.get("station_status") not in {"off_route", "route_unavailable"}
        or rerouted
        or returned_to_route
    )
    if refresh and state["status"] != "completed" and can_rank:
        try:
            _refresh_recommendations(state)
        except RequestException:
            state["station_recommendations"] = []
            state["station_status"] = "unavailable"
            state["warning"] = "Station recommendations are temporarily unavailable."
    elif not refresh and accurate and state.get("station_status") not in {"off_route", "route_unavailable"}:
        _adjust_cached_recommendations(state)
    if not accurate:
        state["warning"] = "GPS update ignored for distance tracking because accuracy exceeds 50 meters."

    try:
        saved = save_trip_update(trip_id, state)
    except TripConflictError:
        raise
    return {**_public_state(saved), "update_status": "accepted"}


def get_active_trip(trip_id, token):
    return _public_state(load_active_trip(trip_id, token))
