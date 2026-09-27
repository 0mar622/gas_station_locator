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

## Save a trip

Start Flask with `uv run python -m server.app`. Send a JSON body to
`POST http://127.0.0.1:5000/trip` from the frontend or Postman:

```json
{
  "starting_location": "2500 Carlos Bee, Hayward CA",
  "destination": "Oakland, CA",
  "fuel_type": "Regular",
  "current_fuel_gallons": 5.4,
  "vehicle_mpg": 30.2
}
```

Set `Content-Type: application/json`. All fields are required; fuel is in US
gallons and must be nonnegative, and MPG must be positive. The logic in
`server/services/trip.py` saves the validated fields and a `created_at` timestamp
to a new Firestore document at `trips/{trip_id}` using the existing credentials.
The service account needs Firestore write permission.

After Firestore confirms creation, the endpoint returns HTTP 201 with
`{"status": "created", "trip_id": "...", "trip": {...}}`.
Invalid input returns 400 without writing. Missing credential configuration
returns 503; authentication or Firestore request failures return 502.
Each successful POST creates a new trip. A network timeout can leave the write's
outcome uncertain, so check Firestore before retrying to avoid duplicate trips.

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
