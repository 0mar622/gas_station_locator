# Gas Station Locator

## Install uv

Install uv once on your computer. On macOS or Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart your terminal if needed, then verify the installation:

```bash
uv --version
```

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

Set `HEIGIT_API_KEY` in `.env` to enable trip previews. The key is used only by
the backend for OpenRouteService geocoding and driving directions via HeiGIT; it
is not sent to the browser.

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

## Preview a route and nearby stations

`POST /trip/plan` geocodes the trip addresses with OpenRouteService, requests a
driving route, and returns map-ready GeoJSON plus compatible stations in a
route corridor. This is a preview only; it does not write to Firestore. The
optional `radius_miles` defaults to 5 and `max_price` is an optional price cap.
Station candidates are annotated with their route distance and whether they
fall within the estimated range (`current_fuel_gallons * vehicle_mpg`), but are
not hidden based on that estimate.

```json
{
  "starting_location": "2500 Carlos Bee, Hayward CA",
  "destination": "Oakland, CA",
  "fuel_type": "Regular",
  "current_fuel_gallons": 5.4,
  "vehicle_mpg": 30.2,
  "radius_miles": 5
}
```

The response contains `route` (a GeoJSON FeatureCollection), route distance and
duration, resolved origin/destination coordinates, and a `stations` array for
map markers. Station prices are synthetic EIA-based estimates, not live pump
prices. The separate `GET /stations/nearby` endpoint remains a point-centered
search.

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
