# Gas Station Locator

For the UI team's endpoint sequence, request examples, state handling, and error
guidance, see the [frontend integration guide](FRONTEND_INTEGRATION.md).

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

Set `HEIGIT_API_KEY` in `.env` to enable trip previews and active trip tracking.
The key is used only by the backend for OpenRouteService geocoding, directions,
and distance matrices via HeiGIT; it is not sent to the browser.

## Start and track a trip

Start Flask with `uv run python -m server.app`. Optionally call `POST /trip/plan`
to preview a route without saving it. To begin tracking, call
`POST http://127.0.0.1:5000/trip/start`:

```json
{
  "starting_location": "2500 Carlos Bee, Hayward CA",
  "destination": "Oakland, CA",
  "fuel_type": "Regular",
  "current_fuel_gallons": 5.4,
  "tank_capacity_gallons": 14,
  "vehicle_mpg": 30.2,
  "radius_miles": 5
}
```

Provide exactly one of `current_fuel_gallons` or `current_fuel_percent`.
`tank_capacity_gallons` is required; fuel values are US gallons, MPG must be
positive, and the current level cannot exceed tank capacity. The endpoint plans
the route and saves it with the trip's current fuel state in Firestore.

The HTTP 201 response includes the `trip_id`, an `access_token`, route geometry,
fuel estimates, and reachable station recommendations. Keep the token private;
send it as `Authorization: Bearer <access_token>` when reading or updating that
trip. Firestore stores only a hash of the token.

While driving, send GPS updates to `POST /trip/{trip_id}/progress`:

```json
{
  "update_id": "unique-client-generated-id",
  "observed_at": "2026-09-26T19:20:00Z",
  "latitude": 37.67,
  "longitude": -122.08,
  "accuracy_meters": 12
}
```

When refueling, include `gallons_added` in a progress update. The backend tracks
distance against the route and estimates fuel use from MPG. It keeps a 10% tank
reserve when checking whether a station is reachable. GPS updates with accuracy
worse than 50 meters do not affect distance estimates; duplicate and stale
updates are ignored. After two accurate updates more than 0.5 miles off-route,
the backend requests a replacement route. It marks the trip complete after two
accurate updates within 0.1 miles of the destination.

Call `GET /trip/{trip_id}` with the same authorization header to reload the
latest trip state. Progress responses also include current estimates and station
recommendations. The old save-only `POST /trip` endpoint has been replaced by
`POST /trip/start`.

Fuel use and cost are estimates based on GPS, MPG, and synthetic station prices.
Exact fuel level requires vehicle telemetry or a reported refuel. Cost estimates
use the next recommended station's price as a proxy for remaining fuel purchases.

## Preview a route and nearby stations

`POST /trip/plan` geocodes the trip addresses with OpenRouteService, requests a
driving route, and returns map-ready GeoJSON plus compatible stations in a route
corridor. This is a preview only; it does not write to Firestore. The optional
`radius_miles` defaults to 5 and `max_price` is an optional price cap.

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
