from unittest.mock import patch

from unittest.mock import MagicMock, patch

from server.app import app
from server.services import getFirebase
from server.services.stations import normalize_station


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


def test_legacy_fuel_price_fields_are_normalized():
    station = normalize_station({
        "name": "projects/p/databases/(default)/documents/stations/old",
        "fields": {
            "name": {"stringValue": "Legacy Station"},
            "latitude": {"stringValue": "37.67"},
            "longitude": {"stringValue": "-122.08"},
            "regular_price": {"doubleValue": 4.75},
        },
    }, "regular")

    assert station["id"] == "old"
    assert station["fuel_type"] == "regular"
    assert station["price"] == 4.75
    assert station["latitude"] == 37.67


def test_fuel_query_includes_canonical_and_legacy_documents(monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "test-key.json")
    credentials = MagicMock(project_id="test-project")
    monkeypatch.setattr(
        getFirebase.service_account.Credentials,
        "from_service_account_file",
        MagicMock(return_value=credentials),
    )
    session = MagicMock()
    session.__enter__.return_value = session
    session.post.return_value.json.side_effect = [
        [{"document": {"name": "stations/new", "fields": {}}}],
        [{"document": {"name": "stations/old", "fields": {}}}],
    ]
    monkeypatch.setattr(getFirebase, "AuthorizedSession", MagicMock(return_value=session))

    documents = getFirebase.get_stations_by_fuel("regular")

    assert [document["name"] for document in documents] == ["stations/new", "stations/old"]
    canonical_query = session.post.call_args_list[0].kwargs["json"]
    legacy_query = session.post.call_args_list[1].kwargs["json"]
    assert canonical_query["structuredQuery"]["where"]["fieldFilter"]["field"]["fieldPath"] == "fuel_type"
    assert legacy_query["structuredQuery"]["where"]["unaryFilter"] == {
        "field": {"fieldPath": "regular_price"},
        "op": "IS_NOT_NULL",
    }
