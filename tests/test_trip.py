from datetime import datetime
from unittest.mock import MagicMock

import pytest
from google.auth.exceptions import RefreshError
from requests.exceptions import HTTPError, Timeout

from server.app import app
from server.services import trip as trip_service


@pytest.fixture
def trip():
    return {
        "starting_location": "2500 Carlos Bee, Hayward CA",
        "destination": "Oakland, CA",
        "fuel_type": "Regular",
        "current_fuel_gallons": 5.4,
        "vehicle_mpg": 30.2,
    }


@pytest.fixture
def firestore(monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "test-key.json")
    monkeypatch.setenv("FIRESTORE_DATABASE_ID", "(default)")
    credentials = MagicMock(project_id="test-project")
    monkeypatch.setattr(
        trip_service.service_account.Credentials,
        "from_service_account_file", MagicMock(return_value=credentials),
    )
    session = MagicMock()
    session.__enter__.return_value = session
    session.post.return_value.json.return_value = {
        "name": "projects/test-project/databases/(default)/documents/trips/new-trip"
    }
    monkeypatch.setattr(trip_service, "AuthorizedSession", MagicMock(return_value=session))
    return session


def test_post_saves_trip_before_returning_created(trip, firestore):
    response = app.test_client().post("/trip", json=trip)

    assert response.status_code == 201
    body = response.get_json()
    assert body["status"] == "created"
    assert body["trip_id"] == "new-trip"
    created_at = body["trip"]["created_at"]
    assert datetime.fromisoformat(created_at).tzinfo is not None
    assert body["trip"] == {**trip, "created_at": created_at}
    firestore.post.assert_called_once_with(
        "https://firestore.googleapis.com/v1/projects/test-project"
        "/databases/%28default%29/documents/trips",
        json={"fields": {
            "starting_location": {"stringValue": trip["starting_location"]},
            "destination": {"stringValue": trip["destination"]},
            "fuel_type": {"stringValue": trip["fuel_type"]},
            "current_fuel_gallons": {"doubleValue": 5.4},
            "vehicle_mpg": {"doubleValue": 30.2},
            "created_at": {"timestampValue": created_at},
        }},
        timeout=10,
    )
    firestore.post.return_value.raise_for_status.assert_called_once()


@pytest.mark.parametrize("data", [
    {}, [], None,
    {"starting_location": "Hayward"},
])
def test_invalid_requests_do_not_write(data, firestore):
    response = app.test_client().post("/trip", json=data)
    assert response.status_code == 400
    firestore.post.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("destination", " "),
    ("current_fuel_gallons", -1),
    ("current_fuel_gallons", True),
    ("vehicle_mpg", 0),
    ("vehicle_mpg", "30"),
    ("vehicle_mpg", float("inf")),
])
def test_invalid_fields_do_not_write(trip, firestore, field, value):
    trip[field] = value
    response = app.test_client().post("/trip", json=trip)
    assert response.status_code == 400
    assert field in response.get_json()["error"]
    firestore.post.assert_not_called()


@pytest.mark.parametrize("error", [HTTPError("private"), Timeout("private"), RefreshError("private")])
def test_write_failures_never_return_success(trip, firestore, error):
    firestore.post.return_value.raise_for_status.side_effect = error
    response = app.test_client().post("/trip", json=trip)
    assert response.status_code == 502
    assert "trip_id" not in response.get_json()
    assert "private" not in response.get_data(as_text=True)


def test_missing_credentials_do_not_write(trip, firestore, monkeypatch):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS")
    assert app.test_client().post("/trip", json=trip).status_code == 503
    firestore.post.assert_not_called()


def test_missing_document_confirmation_returns_error(trip, firestore):
    firestore.post.return_value.json.return_value = {}
    assert app.test_client().post("/trip", json=trip).status_code == 502
