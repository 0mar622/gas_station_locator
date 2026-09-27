from unittest.mock import patch

from server.app import app


def test_nearby_stations_filters_by_distance():
    documents = [
        {"fields": {
            "id": {"stringValue": "near"},
            "name": {"stringValue": "Nearby Gas"},
            "fuel_type": {"stringValue": "regular"},
            "latitude": {"doubleValue": 37.67},
            "longitude": {"doubleValue": -122.08},
            "price": {"doubleValue": 4.99},
        }},
        {"fields": {
            "id": {"stringValue": "far"},
            "name": {"stringValue": "Far Gas"},
            "fuel_type": {"stringValue": "regular"},
            "latitude": {"doubleValue": 38.5},
            "longitude": {"doubleValue": -122.08},
            "price": {"doubleValue": 4.50},
        }},
    ]

    with patch("server.services.stations.get_stations_by_fuel", return_value=documents) as query:
        response = app.test_client().get(
            "/stations/nearby?latitude=37.6688&longitude=-122.0808"
            "&fuel_type=Regular&radius_miles=10"
        )

    assert response.status_code == 200
    assert [station["id"] for station in response.get_json()["stations"]] == ["near"]
    query.assert_called_once_with("Regular")


def test_nearby_stations_requires_query_parameters():
    response = app.test_client().get("/stations/nearby")
    assert response.status_code == 400


def test_nearby_stations_filters_by_max_price():
    documents = [
        {"fields": {
            "id": {"stringValue": "cheap"},
            "latitude": {"doubleValue": 37.67},
            "longitude": {"doubleValue": -122.08},
            "price": {"doubleValue": 4.50},
        }},
        {"fields": {
            "id": {"stringValue": "expensive"},
            "latitude": {"doubleValue": 37.67},
            "longitude": {"doubleValue": -122.08},
            "price": {"doubleValue": 5.50},
        }},
    ]

    with patch("server.services.stations.get_stations_by_fuel", return_value=documents):
        response = app.test_client().get(
            "/stations/nearby?latitude=37.6688&longitude=-122.0808"
            "&fuel_type=regular&radius_miles=10&max_price=5.00"
        )

    assert response.status_code == 200
    assert [station["id"] for station in response.get_json()["stations"]] == ["cheap"]
