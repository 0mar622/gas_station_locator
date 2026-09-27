"""Validate trip details and save them to Firestore."""

import math
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account
from requests.exceptions import RequestException

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def validate_trip(data):
    """Return cleaned trip details and any field validation errors."""
    if not isinstance(data, dict):
        return {}, {"body": "Must be a valid JSON object."}

    trip = {}
    errors = {}

    for field in ("starting_location", "destination", "fuel_type"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            errors[field] = "Must be a non-empty string."
        else:
            trip[field] = value.strip()

    for field in ("current_fuel_gallons", "vehicle_mpg"):
        value = data.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or (isinstance(value, float) and not math.isfinite(value))
        ):
            errors[field] = "Must be a finite number."
        elif field == "vehicle_mpg" and value <= 0:
            errors[field] = "Must be greater than zero."
        elif value < 0:
            errors[field] = "Must be zero or greater."
        else:
            trip[field] = value

    return trip, errors


def save_trip(trip):
    """Create a Firestore document from validated trip details."""
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
    url = (
        f"https://firestore.googleapis.com/v1/projects/{project_id}"
        f"/databases/{database_id}/documents/trips"
    )
    created_at = datetime.now(timezone.utc).isoformat()
    fields = {
        field: {"stringValue": trip[field]}
        for field in ("starting_location", "destination", "fuel_type")
    }
    for field in ("current_fuel_gallons", "vehicle_mpg"):
        fields[field] = {"doubleValue": trip[field]}
    fields["created_at"] = {"timestampValue": created_at}

    with AuthorizedSession(credentials, refresh_timeout=10) as session:
        response = session.post(url, json={"fields": fields}, timeout=10)
        response.raise_for_status()
        document = response.json()

    name = document.get("name") if isinstance(document, dict) else None
    if not isinstance(name, str) or not name.rsplit("/", 1)[-1]:
        raise RequestException("Firestore did not return a document name")

    return {
        "trip_id": name.rsplit("/", 1)[-1],
        "trip": {**trip, "created_at": created_at},
    }
