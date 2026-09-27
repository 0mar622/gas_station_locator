"""Seed the MVP Firestore stations collection from the California CSV."""

import argparse
import csv
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = PROJECT_ROOT / "data" / "ca_gas_stations_synthetic_prices.csv"
COLLECTION = "stations"
FIELDS = ("id", "name", "latitude", "longitude", "price", "fuel_type")
COMMIT_BATCH_SIZE = 400
FIRESTORE_SCOPE = "https://www.googleapis.com/auth/datastore"

load_dotenv(PROJECT_ROOT / ".env")


def load_records(csv_path):
    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        required = {"osm_id", "name", "latitude", "longitude", "fuel_type", "price_usd_per_gallon"}
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")

        records = []
        seen_ids = set()
        for line_number, row in enumerate(reader, start=2):
            if not row["price_usd_per_gallon"].strip():
                raise ValueError(f"CSV row {line_number} has no price")
            if not row["fuel_type"].strip() or row["fuel_type"].strip().lower() == "unknown":
                raise ValueError(f"CSV row {line_number} has no known fuel type")

            osm_id = row["osm_id"].strip()
            fuel_type = row["fuel_type"].strip()
            # A station can have one row per fuel. Include the fuel in the stable ID.
            station_id = re.sub(r"[^A-Za-z0-9_-]", "_", f"{osm_id}_{fuel_type}")
            if station_id in seen_ids:
                raise ValueError(f"Duplicate station/fuel ID on CSV row {line_number}: {station_id}")
            seen_ids.add(station_id)

            try:
                latitude = float(row["latitude"])
                longitude = float(row["longitude"])
                price = float(row["price_usd_per_gallon"])
            except ValueError as exc:
                raise ValueError(f"CSV row {line_number} has an invalid number") from exc

            records.append(
                {
                    "id": station_id,
                    "name": row["name"].strip(),
                    "latitude": latitude,
                    "longitude": longitude,
                    "price": price,
                    "fuel_type": fuel_type,
                }
            )
    return records


def firestore_value(value):
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    return {"stringValue": value}


def firestore_writes(records, database_resource):
    for record in records:
        document_name = f"{database_resource}/documents/{COLLECTION}/{quote(record['id'], safe='')}"
        yield {
            "update": {
                "name": document_name,
                "fields": {key: firestore_value(record[key]) for key in FIELDS},
            }
        }


def firestore_database_resource(credentials_path):
    key_path = Path(credentials_path)
    if not key_path.is_absolute():
        key_path = PROJECT_ROOT / key_path
    credentials = service_account.Credentials.from_service_account_file(
        key_path,
        scopes=[FIRESTORE_SCOPE],
    )
    if not credentials.project_id:
        raise RuntimeError("Firebase service-account JSON must include a project_id")

    project_id = credentials.project_id
    database_id = os.getenv("FIRESTORE_DATABASE_ID", "(default)")
    database_resource = f"projects/{project_id}/databases/{database_id}"
    commit_url = (
        "https://firestore.googleapis.com/v1/"
        f"projects/{quote(project_id, safe='')}/databases/"
        f"{quote(database_id, safe='')}/documents:commit"
    )
    return credentials, database_resource, commit_url


def seed_firestore(records, credentials_path):
    print("Loading Firebase service-account credentials...", flush=True)
    credentials, database_resource, commit_url = firestore_database_resource(credentials_path)
    writes = list(firestore_writes(records, database_resource))
    batch_count = (len(writes) + COMMIT_BATCH_SIZE - 1) // COMMIT_BATCH_SIZE

    print(
        f"Prepared {len(writes)} writes in {batch_count} batches for "
        f"Firestore database '{os.getenv('FIRESTORE_DATABASE_ID', '(default)')}', "
        f"collection '{COLLECTION}'.",
        flush=True,
    )
    with AuthorizedSession(credentials, refresh_timeout=10) as session:
        for batch_index, start in enumerate(range(0, len(writes), COMMIT_BATCH_SIZE), start=1):
            batch = writes[start : start + COMMIT_BATCH_SIZE]
            batch_end = start + len(batch)
            print(
                f"Submitting batch {batch_index}/{batch_count} "
                f"({start + 1}-{batch_end} of {len(writes)} records)...",
                flush=True,
            )
            response = session.post(commit_url, json={"writes": batch}, timeout=30)
            if not response.ok:
                detail = response.text.strip().replace("\n", " ")
                print(
                    f"Firestore rejected batch {batch_index}/{batch_count} "
                    f"with HTTP {response.status_code}: {detail[:2000]}",
                    file=sys.stderr,
                    flush=True,
                )
            response.raise_for_status()
            print(f"Committed {batch_end}/{len(writes)} records.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="Input California stations CSV")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write records to Firestore (without this flag, only validate and preview)",
    )
    args = parser.parse_args()

    records = load_records(args.csv)
    print(f"Validated {len(records)} priced station/fuel records from {args.csv}", flush=True)
    if not args.apply:
        print("Dry run only; pass --apply to write these records to Firestore.", flush=True)
        return

    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not credentials_path:
        raise RuntimeError("Set GOOGLE_APPLICATION_CREDENTIALS in the project .env before applying")
    seed_firestore(records, credentials_path)
    print(f"Seeded {len(records)} station/fuel records into Firestore collection '{COLLECTION}'.", flush=True)


if __name__ == "__main__":
    main()
