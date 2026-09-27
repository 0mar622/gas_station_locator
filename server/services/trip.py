"""Validate trip details and save them to Firestore."""

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

FIELD_TYPES = {
    "starting_location": "stringValue",
    "destination": "stringValue",
    "fuel_type": "stringValue",
    "current_fuel_gallons": "doubleValue",
    "vehicle_mpg": "doubleValue",
}


def save_trip(data):
    """Check required fields and create a trip in Firestore."""
    if not isinstance(data, dict):
        raise ValueError("Send a JSON object with trip details.")
    for field, field_type in FIELD_TYPES.items():
        value = data.get(field)
        if field_type == "stringValue":
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} is required and must be text.")
        elif type(value) not in (int, float) or not 0 <= value < float("inf"):
            raise ValueError(f"{field} must be a nonnegative number.")
    if data["vehicle_mpg"] == 0:
        raise ValueError("vehicle_mpg must be greater than zero.")

    try:
        credentials = service_account.Credentials.from_service_account_file(
            PROJECT_ROOT / os.environ["GOOGLE_APPLICATION_CREDENTIALS"],
            scopes=["https://www.googleapis.com/auth/datastore"],
        )
    except (KeyError, OSError, ValueError) as exc:
        raise RuntimeError("Unable to load Firestore credentials") from exc

    project_id = quote(credentials.project_id, safe="")
    database_id = quote(os.getenv("FIRESTORE_DATABASE_ID", "(default)"), safe="")
    url = (
        f"https://firestore.googleapis.com/v1/projects/{project_id}"
        f"/databases/{database_id}/documents/trips"
    )
    created_at = datetime.now(timezone.utc).isoformat()
    trip = {field: data[field] for field in FIELD_TYPES}
    fields = {field: {FIELD_TYPES[field]: value} for field, value in trip.items()}
    fields["created_at"] = {"timestampValue": created_at}

    with AuthorizedSession(credentials, refresh_timeout=10) as session:
        response = session.post(url, json={"fields": fields}, timeout=10)
        response.raise_for_status()
        document = response.json()

    name = document.get("name")
    if not name:
        raise RequestException("Firestore did not return a document name")

    return {
        "trip_id": name.rsplit("/", 1)[-1],
        "trip": {**trip, "created_at": created_at},
    }
