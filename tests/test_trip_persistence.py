import hashlib
from unittest.mock import MagicMock

import pytest
from requests.exceptions import HTTPError

from server.services import trip as trip_service


@pytest.fixture
def firestore(monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "test-key.json")
    monkeypatch.setenv("FIRESTORE_DATABASE_ID", "(default)")
    credentials = MagicMock(project_id="test-project")
    monkeypatch.setattr(
        trip_service.service_account.Credentials,
        "from_service_account_file",
        MagicMock(return_value=credentials),
    )
    session = MagicMock()
    monkeypatch.setattr(
        trip_service,
        "AuthorizedSession",
        MagicMock(return_value=session),
    )
    return session


def test_create_trip_stores_token_hash_and_derives_geometry(firestore):
    firestore.post.return_value.json.return_value = {
        "name": "projects/test/databases/(default)/documents/trips/trip-1",
        "updateTime": "2026-01-01T00:00:00Z",
        "fields": {
            "route": {"mapValue": {"fields": {
                "features": {"arrayValue": {"values": [{"mapValue": {"fields": {
                    "geometry": {"mapValue": {"fields": {
                        "coordinates": {"arrayValue": {"values": [
                            {"arrayValue": {"values": [
                                {"doubleValue": -122.0},
                                {"doubleValue": 37.0},
                            ]}},
                            {"arrayValue": {"values": [
                                {"doubleValue": -121.0},
                                {"doubleValue": 38.0},
                            ]}},
                        ]}},
                    }}}
                }}}]}}
            }}}
        },
    }

    document, token = trip_service.create_active_trip({
        "route_coordinates": [[-122.0, 37.0], [-121.0, 38.0]],
        "route": {"features": []},
        "status": "active",
    })

    body = firestore.post.call_args.kwargs["json"]
    assert body["fields"]["trip_token_hash"]["stringValue"] == hashlib.sha256(token.encode()).hexdigest()
    assert "route_coordinates" not in body["fields"]
    assert document["trip_id"] == "trip-1"
    assert document["route_coordinates"] == [[-122.0, 37.0], [-121.0, 38.0]]
    assert "trip_token_hash" not in document or document["trip_token_hash"] != token


def test_update_uses_firestore_version_precondition(firestore):
    firestore.patch.return_value.json.return_value = {
        "name": "projects/test/databases/(default)/documents/trips/trip-1",
        "updateTime": "2026-01-01T00:01:00Z",
        "fields": {"status": {"stringValue": "active"}},
    }
    state = {
        "trip_id": "trip-1",
        "_update_time": "2026-01-01T00:00:00Z",
        "route_coordinates": [[0, 0], [1, 1]],
        "status": "active",
    }

    saved = trip_service.save_trip_update("trip-1", state)

    assert saved["status"] == "active"
    params = firestore.patch.call_args.kwargs["params"]
    assert ("currentDocument.updateTime", "2026-01-01T00:00:00Z") in params
    assert ("updateMask.fieldPaths", "route_coordinates") not in params


def test_update_conflict_becomes_conflict_error(firestore):
    response = MagicMock(status_code=400)
    response.json.return_value = {"error": {"status": "FAILED_PRECONDITION"}}
    response.raise_for_status.side_effect = HTTPError("stale version")
    firestore.patch.return_value = response
    state = {"_update_time": "old", "status": "active"}

    with pytest.raises(trip_service.TripConflictError):
        trip_service.save_trip_update("trip-1", state)
