"""Persist active trip state in Firestore."""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account
from requests.exceptions import HTTPError, RequestException

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


class TripNotFoundError(Exception):
    """The requested trip does not exist."""


class TripAuthorizationError(Exception):
    """The per-trip token is missing or invalid."""


class TripConflictError(Exception):
    """Another progress update changed this trip concurrently."""


def _encode_value(value):
    if value is None:
        return {"nullValue": None}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, list):
        return {"arrayValue": {"values": [_encode_value(item) for item in value]}}
    if isinstance(value, dict):
        return {
            "mapValue": {
                "fields": {key: _encode_value(item) for key, item in value.items()}
            }
        }
    raise TypeError(f"Unsupported Firestore value type: {type(value).__name__}")


def _decode_value(value):
    if "mapValue" in value:
        return {
            key: _decode_value(item)
            for key, item in value["mapValue"].get("fields", {}).items()
        }
    if "arrayValue" in value:
        return [
            _decode_value(item)
            for item in value["arrayValue"].get("values", [])
        ]
    for key in (
        "nullValue",
        "booleanValue",
        "integerValue",
        "doubleValue",
        "stringValue",
        "timestampValue",
    ):
        if key in value:
            decoded = value[key]
            if key == "integerValue":
                return int(decoded)
            if key == "doubleValue":
                return float(decoded)
            return decoded
    return None


def _firestore_session():
    key_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not key_file:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS is not configured")
    try:
        credentials = service_account.Credentials.from_service_account_file(
            PROJECT_ROOT / key_file,
            scopes=["https://www.googleapis.com/auth/datastore"],
        )
    except (OSError, ValueError) as exc:
        raise RuntimeError("Unable to load Firestore credentials") from exc
    if not credentials.project_id:
        raise RuntimeError("Firestore credentials must include a project_id")
    project_id = quote(credentials.project_id, safe="")
    database_id = quote(os.getenv("FIRESTORE_DATABASE_ID", "(default)"), safe="")
    base_url = (
        f"https://firestore.googleapis.com/v1/projects/{project_id}"
        f"/databases/{database_id}/documents"
    )
    return AuthorizedSession(credentials, refresh_timeout=10), base_url


def _trip_document_url(base_url, trip_id):
    return f"{base_url}/trips/{quote(trip_id, safe='')}"


def _decode_document(document):
    state = {
        key: _decode_value(value)
        for key, value in document.get("fields", {}).items()
    }
    state["trip_id"] = document.get("name", "").rsplit("/", 1)[-1]
    state["_update_time"] = document.get("updateTime")
    if "route_coordinates" not in state:
        try:
            state["route_coordinates"] = state["route"]["features"][0]["geometry"]["coordinates"]
        except (KeyError, IndexError, TypeError):
            state["route_coordinates"] = []
    return state


def _persisted_fields(state):
    return {
        key: value
        for key, value in state.items()
        if key not in {"trip_id", "_update_time", "route_coordinates"}
    }


def create_active_trip(state):
    token = secrets.token_urlsafe(32)
    stored = {
        **state,
        "trip_token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    session, base_url = _firestore_session()
    try:
        response = session.post(
            f"{base_url}/trips",
            json={
                "fields": {
                    key: _encode_value(value)
                    for key, value in _persisted_fields(stored).items()
                }
            },
            timeout=10,
        )
        response.raise_for_status()
        document = response.json()
    finally:
        session.close()
    name = document.get("name")
    if not name:
        raise RequestException("Firestore did not return a document name")
    return _decode_document(document), token


def _get_trip_document(session, base_url, trip_id):
    response = session.get(_trip_document_url(base_url, trip_id), timeout=10)
    try:
        response.raise_for_status()
    except HTTPError as exc:
        if response.status_code == 404:
            raise TripNotFoundError("Trip not found.") from exc
        raise
    return response.json()


def load_active_trip(trip_id, token):
    if not isinstance(token, str) or not token:
        raise TripAuthorizationError("A trip access token is required.")
    session, base_url = _firestore_session()
    try:
        document = _get_trip_document(session, base_url, trip_id)
    finally:
        session.close()
    state = _decode_document(document)
    _authorize(state, token)
    return state


def _authorize(state, token):
    if not isinstance(token, str) or not token:
        raise TripAuthorizationError("A trip access token is required.")
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(digest, state.get("trip_token_hash", "")):
        raise TripAuthorizationError("Invalid trip access token.")


def save_trip_update(trip_id, state):
    """Replace known trip fields if the Firestore version has not changed."""
    session, base_url = _firestore_session()
    try:
        url = _trip_document_url(base_url, trip_id)
        persisted = _persisted_fields(state)
        params = [("updateMask.fieldPaths", key) for key in persisted]
        params.append(("currentDocument.updateTime", state["_update_time"]))
        fields = {
            key: _encode_value(value)
            for key, value in persisted.items()
        }
        response = session.patch(
            url,
            params=params,
            json={"fields": fields},
            timeout=10,
        )
        try:
            error_status = response.json().get("error", {}).get("status")
        except (AttributeError, ValueError):
            error_status = None
        if response.status_code in (409, 412) or error_status == "FAILED_PRECONDITION":
            raise TripConflictError("Trip changed during this update. Retry with a fresh read.")
        response.raise_for_status()
        return _decode_document(response.json())
    finally:
        session.close()


def token_from_header(header):
    if not isinstance(header, str) or not header.startswith("Bearer "):
        return None
    return header[7:].strip()
