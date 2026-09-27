from unittest.mock import patch

import pytest

from server.app import app
from server.services import trip_tracking


@pytest.fixture
def trip():
    return {
        "starting_location": "2500 Carlos Bee, Hayward CA",
        "destination": "Oakland, CA",
        "fuel_type": "Regular",
        "current_fuel_gallons": 5.4,
        "tank_capacity_gallons": 14,
        "vehicle_mpg": 30.2,
    }


@pytest.fixture
def plan():
    return {
        "route": {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-122.08, 37.67], [-122.27, 37.80]],
                },
                "properties": {"summary": {"distance": 20000, "duration": 1800}},
            }],
        },
        "origin": {"label": "Hayward", "latitude": 37.67, "longitude": -122.08},
        "destination": {"label": "Oakland", "latitude": 37.80, "longitude": -122.27},
        "distance_miles": 12.43,
        "duration_minutes": 30,
    }


def test_start_trip_persists_route_and_returns_access_token(trip, plan):
    recommendations = [{"id": "near", "price": 4.50, "driving_distance_miles": 3.2}]
    with (
        patch("server.services.trip_tracking.plan_trip", return_value=plan),
        patch("server.services.trip_tracking.recommend_safe_stations", return_value=recommendations),
        patch(
            "server.services.trip_tracking.create_active_trip",
            side_effect=lambda state: ({**state, "trip_id": "new-trip", "_update_time": "now"}, "secret-token"),
        ) as create,
    ):
        response = app.test_client().post("/trip/start", json=trip)

    assert response.status_code == 201
    body = response.get_json()
    assert body["trip_id"] == "new-trip"
    assert body["access_token"] == "secret-token"
    assert body["stations"] == recommendations
    assert body["fuel_remaining_gallons"] == 5.4
    assert create.call_args.args[0]["route"] == plan["route"]
    assert create.call_args.args[0]["route_distance_miles"] == 12.43


def test_start_trip_accepts_percent_fuel_and_normalizes_to_gallons(trip, plan):
    trip.pop("current_fuel_gallons")
    trip["current_fuel_percent"] = 50
    with (
        patch("server.services.trip_tracking.plan_trip", return_value=plan),
        patch("server.services.trip_tracking.recommend_safe_stations", return_value=[]),
        patch(
            "server.services.trip_tracking.create_active_trip",
            side_effect=lambda state: ({**state, "trip_id": "new-trip", "_update_time": "now"}, "token"),
        ) as create,
    ):
        response = app.test_client().post("/trip/start", json=trip)

    assert response.status_code == 201
    assert create.call_args.args[0]["current_fuel_gallons"] == 7
    assert response.get_json()["safe_range_miles"] == pytest.approx((7 - 14 * 0.1) * 30.2)
    assert response.get_json()["station_status"] == "no_safe_station"
    assert "No station is reachable" in response.get_json()["warning"]


@pytest.mark.parametrize("changes", [
    {"tank_capacity_gallons": 0},
    {"current_fuel_gallons": 15},
    {"current_fuel_percent": 50},
    {"tank_capacity_gallons": None},
    {"vehicle_mpg": 0},
])
def test_start_trip_rejects_invalid_fuel_inputs_without_writing(trip, changes):
    with patch("server.services.trip_tracking.create_active_trip") as create:
        response = app.test_client().post("/trip/start", json={**trip, **changes})
    assert response.status_code == 400
    create.assert_not_called()


def _progress_state():
    return {
        "trip_id": "trip-1",
        "_update_time": "version-1",
        "trip_token_hash": "",
        "status": "active",
        "fuel_type": "regular",
        "vehicle_mpg": 20.0,
        "tank_capacity_gallons": 12.0,
        "current_fuel_gallons": 6.0,
        "route": {},
        "route_coordinates": [[0.0, 0.0], [1.0, 0.0]],
        "route_distance_miles": 69.0,
        "route_duration_minutes": 90.0,
        "route_progress_miles": 0.0,
        "distance_traveled_miles": 0.0,
        "current_location": {"latitude": 0.0, "longitude": 0.0},
        "last_update_location": {"latitude": 0.0, "longitude": 0.0},
        "last_update_at": "2026-01-01T00:00:00+00:00",
        "last_update_id": "start",
        "last_rank_refresh_miles": 0.0,
        "recommendation_origin_progress_miles": 0.0,
        "station_recommendations": [],
        "station_status": "no_safe_station",
        "off_route_count": 0,
        "arrival_count": 0,
        "destination_coordinates": {"latitude": 1.0, "longitude": 0.0},
    }


def test_progress_estimates_fuel_and_persists_state():
    state = _progress_state()
    payload = {
        "update_id": "u1",
        "observed_at": "2026-01-01T00:01:00Z",
        "latitude": 0.0,
        "longitude": 0.1,
        "accuracy_meters": 5,
    }
    with (
        patch("server.services.trip_tracking.load_active_trip", return_value=state),
        patch("server.services.trip_tracking.save_trip_update", side_effect=lambda _id, updated: updated),
        patch("server.services.trip_tracking._refresh_recommendations"),
    ):
        result = trip_tracking.update_active_trip("trip-1", "token", payload)

    assert result["update_status"] == "accepted"
    assert result["distance_traveled_miles"] == pytest.approx(6.91, abs=0.05)
    assert result["fuel_remaining_gallons"] == pytest.approx(6 - result["distance_traveled_miles"] / 20, abs=0.01)


def test_duplicate_and_stale_progress_updates_are_ignored():
    state = _progress_state()
    state["last_update_id"] = "same"
    state["last_update_at"] = "2026-01-01T00:02:00+00:00"
    payload = {
        "update_id": "same",
        "observed_at": "2026-01-01T00:01:00Z",
        "latitude": 0.0,
        "longitude": 0.1,
        "accuracy_meters": 5,
        "gallons_added": 2,
    }
    with patch("server.services.trip_tracking.load_active_trip", return_value=state):
        result = trip_tracking.update_active_trip("trip-1", "token", payload)
    assert result["update_status"] == "duplicate"
    assert result["fuel_remaining_gallons"] == 6

    payload["update_id"] = "older"
    with patch("server.services.trip_tracking.load_active_trip", return_value=state):
        result = trip_tracking.update_active_trip("trip-1", "token", payload)
    assert result["update_status"] == "stale"
    assert result["fuel_remaining_gallons"] == 6


def test_refuel_is_applied_but_cannot_overfill_tank():
    state = _progress_state()
    payload = {
        "update_id": "refuel",
        "observed_at": "2026-01-01T00:01:00Z",
        "latitude": 0.0,
        "longitude": 0.0,
        "accuracy_meters": 100,
        "gallons_added": 3,
    }
    with (
        patch("server.services.trip_tracking.load_active_trip", return_value=state),
        patch("server.services.trip_tracking.save_trip_update", side_effect=lambda _id, updated: updated),
        patch("server.services.trip_tracking._refresh_recommendations"),
    ):
        result = trip_tracking.update_active_trip("trip-1", "token", payload)
    assert result["fuel_remaining_gallons"] == 9

    payload["gallons_added"] = 7
    payload["update_id"] = "second-refuel"
    payload["observed_at"] = "2026-01-01T00:02:00Z"
    with patch("server.services.trip_tracking.load_active_trip", return_value=state):
        with pytest.raises(ValueError, match="tank capacity"):
            trip_tracking.update_active_trip("trip-1", "token", payload)


def test_read_trip_requires_bearer_token():
    response = app.test_client().get("/trip/trip-1")
    assert response.status_code == 401


def test_read_trip_rejects_invalid_token():
    from server.services.trip import TripAuthorizationError

    with patch("server.app.get_active_trip", side_effect=TripAuthorizationError("Invalid token")):
        response = app.test_client().get(
            "/trip/trip-1",
            headers={"Authorization": "Bearer wrong"},
        )
    assert response.status_code == 401


def test_old_save_only_endpoint_is_removed():
    response = app.test_client().post("/trip", json={})
    assert response.status_code == 404


def test_route_completion_requires_two_close_accurate_updates():
    state = _progress_state()
    state["route_coordinates"] = [[0.0, 0.0], [1.0, 0.0]]
    state["destination_coordinates"] = {"latitude": 0.0, "longitude": 1.0}
    state["route_progress_miles"] = 68.9
    state["distance_traveled_miles"] = 68.9
    state["current_location"] = {"latitude": 0.0, "longitude": 0.999}
    state["last_update_location"] = dict(state["current_location"])
    state["last_update_at"] = "2026-01-01T00:00:00+00:00"
    state["route_distance_miles"] = 69.0
    payload = {
        "update_id": "arrive-1",
        "observed_at": "2026-01-01T00:01:00Z",
        "latitude": 0.0,
        "longitude": 1.0,
        "accuracy_meters": 5,
    }
    with (
        patch("server.services.trip_tracking.load_active_trip", return_value=state),
        patch("server.services.trip_tracking.save_trip_update", side_effect=lambda _id, updated: updated),
        patch("server.services.trip_tracking._refresh_recommendations"),
    ):
        first = trip_tracking.update_active_trip("trip-1", "token", payload)
        state.update(first)
        state["_update_time"] = "version-2"
        payload["update_id"] = "arrive-2"
        payload["observed_at"] = "2026-01-01T00:02:00Z"
        second = trip_tracking.update_active_trip("trip-1", "token", payload)
    assert first["status"] == "active"
    assert second["status"] == "completed"


def test_two_accurate_off_route_updates_trigger_reroute(monkeypatch):
    monkeypatch.setenv("HEIGIT_API_KEY", "test-key")
    state = _progress_state()
    state["last_update_at"] = "2026-01-01T00:00:00+00:00"
    payload = {
        "update_id": "off-1",
        "observed_at": "2026-01-01T00:01:00Z",
        "latitude": 0.02,
        "longitude": 0.1,
        "accuracy_meters": 5,
    }
    route = {"type": "FeatureCollection", "features": []}
    with (
        patch("server.services.trip_tracking.load_active_trip", side_effect=lambda *_: state),
        patch("server.services.trip_tracking.save_trip_update", side_effect=lambda _id, updated: updated),
        patch(
            "server.services.trip_tracking._reroute_from",
            return_value=(route, 12.0, 15.0, [[0.1, 0.02], [0.2, 0.02]]),
        ) as reroute,
        patch("server.services.trip_tracking._refresh_recommendations"),
    ):
        first = trip_tracking.update_active_trip("trip-1", "token", payload)
        payload["update_id"] = "off-2"
        payload["observed_at"] = "2026-01-01T00:02:00Z"
        payload["longitude"] = 0.2
        second = trip_tracking.update_active_trip("trip-1", "token", payload)

    assert first["station_status"] == "off_route"
    assert reroute.call_count == 1
    assert second["route"] == route
    assert second["route_miles_remaining"] == 12
