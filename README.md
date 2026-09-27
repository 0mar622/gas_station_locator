# Gas Station Locator

## Development setup

This project uses [uv](https://docs.astral.sh/uv/) to manage its Python environment and dependencies.

```bash
uv sync
source .venv/bin/activate
```

Run tests with:

```bash
uv run pytest
```

Create a local environment file for API keys when needed. Never commit `.env`:

```bash
cp .env.example .env
```

## Read stations from Firestore

In your root `.env`, set `GOOGLE_APPLICATION_CREDENTIALS` to the path of your
service-account JSON file (see `.env.example`). Relative paths are resolved from
the project root. `FIRESTORE_DATABASE_ID` defaults to `(default)`.

Run the Firestore GET request directly from the project root:

```bash
uv sync
uv run python server/services/getFirebase.py
```

This prints your station data as JSON without starting Flask. You can also run
`server/services/getFirebase.py` using your editor's Run button with the project
`.venv` Python interpreter, or call the function from Python:

```python
from server.services.getFirebase import get_stations

data = get_stations()
print(data)
```

The backend authenticates with Google and makes an HTTP GET request to the
Firestore `stations` collection. The response uses Firestore's REST JSON format:
`documents` contains document names and typed fields such as `stringValue`.
Each request fetches up to 100 documents. If `nextPageToken` is returned, fetch
the next page using `get_stations(page_token=data["nextPageToken"])`.

The Flask `GET /stations` endpoint also uses this function. To access it in your
browser, start Flask with `uv run python -m server.app` and open
`http://127.0.0.1:5000/stations`.

The service account needs Firestore read permission through Google Cloud IAM.
Credentials stay on the backend. This local MVP endpoint has no user authentication.

## Seed the California station dataset

The California CSV contains synthetic EIA-based estimates, not observed pump
prices. Review the CSV before seeding. `scripts/seed.py` uses the same service
account configuration as the Firestore reader, and defaults to a no-write dry
run:

```bash
uv run python scripts/seed.py
```

After confirming the preview, write the records to the Firestore `stations`
collection with:

```bash
uv run python scripts/seed.py --apply
```

Each CSV station/fuel row becomes one document with `id`, `name`, `latitude`,
`longitude`, `price`, and `fuel_type`. The stable document ID combines the OSM
station ID and fuel type, so rerunning the seed updates those documents instead
of creating duplicates. Use `--csv PATH` to seed a different CSV.
