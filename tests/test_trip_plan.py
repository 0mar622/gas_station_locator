from unittest.mock import MagicMock, patch

import pytest
from requests.exceptions import RequestException

from server.app import app
from server.services import routing, stations


@pytest.fixture
def trip():
    return {
        "starting_location": "Hayward, CA",
        "destination": "Oakland, CA",
        "fuel_type": "Regular",
        "current_fuel_gallons": 5.4,
        "vehicle_mpg": 30.2,
    }


@pytest.fixture
def ors_session():
    session = MagicMock()
    session.__enter__.return_value = session
    geocode_origin = MagicMock()
    geocode_origin.json.return_value = {
        "features": [{
            "geometry": {"coordinates": [-122.08, 37.67]},
            "properties": {"label": "Hayward, California"},
        }]
    }
    geocode_destination = MagicMock()
    geocode_destination.json.return_value = {
        "features": [{
            "geometry": {"coordinates": [-122.27, 37.80]},
            "properties": {"label": "Oakland, California"},
        }]
    }
    route_response = MagicMock()
    route_response.json.return_value = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[-122.08, 37.67], [-122.17, 37.73], [-122.27, 37.80]],
            },
            "properties": {"summary": {"distance": 20000, "duration": 1800}},
        }],
    }
    session.get.side_effect = [geocode_origin, geocode_destination]
    session.post.return_value = route_response
    return session


def test_plan_endpoint_returns_geojson_route_and_station_markers(
    trip, ors_session, monkeypatch
):
    monkeypatch.setenv("HEIGIT_API_KEY", "test-heigit-key")
    matching_stations = [{
        "id": "node_123_regular",
        "name": "Test Fuel",
        "latitude": 37.7,
        "longitude": -122.15,
        "price": 4.5,
        "fuel_type": "regular",
        "distance_to_route_miles": 0.2,
        "route_progress_miles": 3.0,
        "within_estimated_range": True,
    }]
    with (
        patch("server.services.routing.requests.Session", return_value=ors_session),
        patch(
            "server.services.routing.get_stations_near_route",
            return_value=matching_stations,
        ) as station_query,
    ):
        response = app.test_client().post("/trip/plan", json=trip)

    assert response.status_code == 200
    body = response.get_json()
    assert body["route"]["features"][0]["geometry"]["type"] == "LineString"
    assert body["distance_miles"] == 12.43
    assert body["duration_minutes"] == 30
    assert body["estimated_range_miles"] == 163.08
    assert body["radius_miles"] == 5
    assert body["stations"] == matching_stations
    assert "synthetic" in body["price_note"].lower()
    assert [call.kwargs["params"]["text"] for call in ors_session.get.call_args_list] == [
        "Hayward, CA",
        "Oakland, CA",
    ]
    assert all(
        call.args[0] == "https://api.heigit.org/pelias/v1/search"
        for call in ors_session.get.call_args_list
    )
    ors_session.post.assert_called_once()
    assert (
        ors_session.post.call_args.args[0]
        == "https://api.heigit.org/openrouteservice/v2/directions/driving-car/geojson"
    )
    route_request = ors_session.post.call_args.kwargs["json"]
    assert route_request["coordinates"] == [[-122.08, 37.67], [-122.27, 37.8]]
    station_query.assert_called_once_with(
        [[-122.08, 37.67], [-122.17, 37.73], [-122.27, 37.8]],
        "regular",
        radius_miles=5,
        max_price=None,
        estimated_range_miles=163.08,
    )


def test_plan_endpoint_passes_radius_and_price_filters(trip, ors_session, monkeypatch):
    monkeypatch.setenv("HEIGIT_API_KEY", "test-heigit-key")
    with (
        patch("server.services.routing.requests.Session", return_value=ors_session),
        patch("server.services.routing.get_stations_near_route", return_value=[]) as query,
    ):
        response = app.test_client().post(
            "/trip/plan",
            json={**trip, "radius_miles": 8, "max_price": 5.25},
        )

    assert response.status_code == 200
    assert query.call_args.kwargs["radius_miles"] == 8
    assert query.call_args.kwargs["max_price"] == 5.25


@pytest.mark.parametrize(
    "changes",
    [
        {"radius_miles": 0},
        {"radius_miles": float("nan")},
        {"max_price": -1},
        {"fuel_type": "e85"},
        {"vehicle_mpg": 0},
    ],
)
def test_plan_endpoint_rejects_invalid_input_before_network(trip, changes):
    with patch("server.services.routing.requests.Session") as session_factory:
        response = app.test_client().post("/trip/plan", json={**trip, **changes})

    assert response.status_code == 400
    session_factory.assert_not_called()


def test_plan_endpoint_returns_422_when_address_cannot_be_resolved(
    trip, monkeypatch
):
    monkeypatch.setenv("HEIGIT_API_KEY", "test-heigit-key")
    with patch(
        "server.services.routing._geocode",
        side_effect=routing.AddressNotFoundError("No address match"),
    ):
        response = app.test_client().post("/trip/plan", json=trip)

    assert response.status_code == 422
    assert "No address match" in response.get_json()["error"]


def test_plan_endpoint_returns_422_when_no_route_is_found(
    trip, ors_session, monkeypatch
):
    monkeypatch.setenv("HEIGIT_API_KEY", "test-heigit-key")
    ors_session.post.return_value.json.return_value = {"features": []}
    with patch("server.services.routing.requests.Session", return_value=ors_session):
        response = app.test_client().post("/trip/plan", json=trip)

    assert response.status_code == 422
    assert "could not find a driving route" in response.get_json()["error"].lower()


def test_plan_endpoint_returns_502_when_route_provider_fails(trip, monkeypatch):
    monkeypatch.setenv("HEIGIT_API_KEY", "test-heigit-key")
    with patch(
        "server.services.routing._geocode",
        side_effect=RequestException("provider unavailable"),
    ):
        response = app.test_client().post("/trip/plan", json=trip)

    assert response.status_code == 502


def test_plan_endpoint_requires_heigit_key(trip, monkeypatch):
    monkeypatch.delenv("HEIGIT_API_KEY", raising=False)
    response = app.test_client().post("/trip/plan", json=trip)

    assert response.status_code == 503


def test_plan_endpoint_returns_empty_station_list(trip, ors_session, monkeypatch):
    monkeypatch.setenv("HEIGIT_API_KEY", "test-heigit-key")
    with (
        patch("server.services.routing.requests.Session", return_value=ors_session),
        patch("server.services.routing.get_stations_near_route", return_value=[]),
    ):
        response = app.test_client().post("/trip/plan", json=trip)

    assert response.status_code == 200
    assert response.get_json()["stations"] == []


def test_plan_endpoint_reports_station_backend_failure(trip, ors_session, monkeypatch):
    monkeypatch.setenv("HEIGIT_API_KEY", "test-heigit-key")
    with (
        patch("server.services.routing.requests.Session", return_value=ors_session),
        patch(
            "server.services.routing.get_stations_near_route",
            side_effect=RequestException("Firestore unavailable"),
        ),
    ):
        response = app.test_client().post("/trip/plan", json=trip)

    assert response.status_code == 502


def _station_document(station_id, latitude, longitude, price):
    return {
        "fields": {
            "id": {"stringValue": station_id},
            "name": {"stringValue": station_id},
            "fuel_type": {"stringValue": "regular"},
            "latitude": {"doubleValue": latitude},
            "longitude": {"doubleValue": longitude},
            "price": {"doubleValue": price},
        }
    }


def test_route_station_search_filters_corridor_price_and_annotates_range():
    route = [[0, 0], [0.1, 0]]
    documents = [
        _station_document("on-route", 0.005, 0.05, 4.5),
        _station_document("outside-corridor", 0.03, 0.05, 4.0),
        _station_document("over-budget", 0.005, 0.07, 5.5),
    ]
    with patch(
        "server.services.stations.get_stations_by_fuel",
        return_value=documents,
    ) as query:
        results = stations.get_stations_near_route(
            route,
            "Regular",
            radius_miles=1,
            max_price=5,
            estimated_range_miles=4,
        )

    assert [station["id"] for station in results] == ["on-route"]
    assert results[0]["distance_to_route_miles"] < 1
    assert results[0]["route_progress_miles"] == pytest.approx(3.45, abs=0.1)
    assert results[0]["within_estimated_range"] is True
    query.assert_called_once_with("Regular")


def test_route_station_search_marks_beyond_range_without_excluding():
    with patch(
        "server.services.stations.get_stations_by_fuel",
        return_value=[_station_document("later", 0.005, 0.05, 4.5)],
    ):
        results = stations.get_stations_near_route(
            [[0, 0], [0.1, 0]],
            "regular",
            radius_miles=1,
            estimated_range_miles=2,
        )

    assert len(results) == 1
    assert results[0]["within_estimated_range"] is False
