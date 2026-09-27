"""Read gas stations through the Firestore REST API."""

import json
import os
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def get_stations(page_token=None):
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
        f"/databases/{database_id}/documents/stations"
    )
    params = {"pageSize": 100}
    if page_token:
        params["pageToken"] = page_token

    with AuthorizedSession(credentials, refresh_timeout=10) as session:
        response = session.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

    data.setdefault("documents", [])
    return data


def get_stations_by_fuel(fuel_type):
    """Get station documents matching a fuel type."""
    key_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not key_file:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS is not configured")

    credentials = service_account.Credentials.from_service_account_file(
        PROJECT_ROOT / key_file,
        scopes=["https://www.googleapis.com/auth/datastore"],
    )
    project_id = quote(credentials.project_id, safe="")
    database_id = quote(os.getenv("FIRESTORE_DATABASE_ID", "(default)"), safe="")
    url = (
        f"https://firestore.googleapis.com/v1/projects/{project_id}"
        f"/databases/{database_id}/documents:runQuery"
    )
    query = {
        "structuredQuery": {
            "from": [{"collectionId": "stations"}],
            "where": {
                "fieldFilter": {
                    "field": {"fieldPath": "fuel_type"},
                    "op": "EQUAL",
                    "value": {"stringValue": fuel_type.lower()},
                }
            },
        }
    }

    with AuthorizedSession(credentials, refresh_timeout=10) as session:
        response = session.post(url, json=query, timeout=10)
        response.raise_for_status()

    return [item["document"] for item in response.json() if "document" in item]


if __name__ == "__main__":
    print(json.dumps(get_stations(), indent=2))
