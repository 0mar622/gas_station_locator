"""Save users to Firestore."""

import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

STRING_FIELDS = ("email", "first_name", "last_name", "fuel_type")
NUMBER_FIELDS = ("tank_capacity", "vehicle_mpg")


def save_user(data):
    if not isinstance(data, dict):
        raise ValueError("Send a JSON object with user details.")

    for field in STRING_FIELDS:
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f"{field} is required.")

    for field in NUMBER_FIELDS:
        if type(data.get(field)) not in (int, float) or data[field] <= 0:
            raise ValueError(f"{field} must be a positive number.")

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
        f"/databases/{database_id}/documents/users"
    )
    created_at = datetime.now(timezone.utc).isoformat()
    user = {field: data[field] for field in STRING_FIELDS + NUMBER_FIELDS}
    fields = {
        **{field: {"stringValue": user[field]} for field in STRING_FIELDS},
        **{field: {"doubleValue": user[field]} for field in NUMBER_FIELDS},
        "created_at": {"timestampValue": created_at},
    }

    with AuthorizedSession(credentials, refresh_timeout=10) as session:
        response = session.post(url, json={"fields": fields}, timeout=10)
        response.raise_for_status()
        document = response.json()

    return {
        "user_id": document["name"].rsplit("/", 1)[-1],
        "user": {**user, "created_at": created_at},
    }
