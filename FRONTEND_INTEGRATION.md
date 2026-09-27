# Frontend integration guide

This guide describes the API sequence for the trip-planning and active-trip UI. The frontend talks to Flask; it does not access Firestore or OpenRouteService directly.

## Which endpoint should I call?

| User action | API | When to use it |
| --- | --- | --- |
| Preview a route before the user commits | `POST /trip/plan` | Optional, read-only preview. It does not create a saved trip. |
| Begin an active trip | `POST /trip/start` | Call after the user confirms the trip. It creates the persisted trip and returns its ID and access token. |
| Send location or report fuel added | `POST /trip/{trip_id}/progress` | Call while tracking an active trip. Refueling is reported through this same endpoint. |
| Restore or refresh a trip | `GET /trip/{trip_id}` | Call when reopening the trip UI or when the latest state is needed independently of a progress update. |

`GET /stations/nearby` is a separate point-centered station search; it is not needed for the route-aware recommendations in the active-trip flow. Do not use the legacy save-only `POST /trip` for starting an active trip.

## Typical sequence

```text
Optional: user edits trip details ──> POST /trip/plan (preview only)
User taps Start ────────────────────> POST /trip/start
                                      save trip_id + access_token
While trip is active ───────────────> POST /trip/{trip_id}/progress (repeat)
User reports refueling ─────────────> same progress endpoint + gallons_added
App reopens / needs a refresh ──────> GET /trip/{trip_id}
Trip response says completed ──────> stop location tracking
```

The plan preview and active-trip start are intentionally separate. Use the preview to show a tentative route before confirmation; use `/trip/start` to begin tracking. Starting recalculates recommendations and persists the trip, so a preview response is not a substitute for the start response.

## 1. Optional route preview

Send the trip inputs to `POST /trip/plan` as JSON. Required fields are `starting_location`, `destination`, `fuel_type`, `current_fuel_gallons`, and `vehicle_mpg`. `radius_miles` is optional (default 5); `max_price` is an optional price cap.

```js
const response = await fetch(`${API_BASE_URL}/trip/plan`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    starting_location: "2500 Carlos Bee, Hayward CA",
    destination: "Oakland, CA",
    fuel_type: "Regular",
    current_fuel_gallons: 5.4,
    vehicle_mpg: 30.2,
    radius_miles: 5,
  }),
});
const preview = await response.json();
if (!response.ok) throw new Error(preview.error ?? "Could not preview trip");
```

Use `preview.route` as map-ready GeoJSON and `preview.stations` for preview markers. The response also includes resolved `origin` and `destination`, route distance and duration, estimated range, `radius_miles`, and `price_note`. This call does not write to Firestore and does not return an active `trip_id` or token.

## 2. Start the active trip

When the user taps Start, call `POST /trip/start`. Required fields are `starting_location`, `destination`, `fuel_type`, `vehicle_mpg`, and `tank_capacity_gallons`, plus exactly one of `current_fuel_gallons` or `current_fuel_percent`. The current fuel value cannot exceed tank capacity. `radius_miles` and `max_price` are optional.

```js
const response = await fetch(`${API_BASE_URL}/trip/start`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    starting_location: "2500 Carlos Bee, Hayward CA",
    destination: "Oakland, CA",
    fuel_type: "Regular",
    current_fuel_gallons: 5.4,
    tank_capacity_gallons: 14,
    vehicle_mpg: 30.2,
    radius_miles: 5,
  }),
});
const trip = await response.json();
if (!response.ok) throw new Error(trip.error ?? "Could not start trip");

// Keep both values in private app state; the token is a credential.
const { trip_id, access_token } = trip;
```

The successful response is HTTP `201`. Save `trip_id` and `access_token` for subsequent calls, and use the returned state—not the earlier preview—to render the active trip. Keep the token out of URLs, analytics, logs, and shared/public storage. Firestore stores only a hash of it. If the token is lost, there is no token-refresh endpoint; the current API cannot authorize that trip again.

The response includes route geometry, `current_location`, fuel/range/cost estimates, `stations`, `station_status`, and possibly a `warning`. Recommended station objects include map coordinates and fields such as `name`, `fuel_type`, `price`, `driving_distance_miles`, `detour_miles`, and `within_safe_range`. Treat the returned station list and its order as the backend's current recommendations.

## 3. Track progress and report refueling

Once the trip is active, request device location permission and send GPS fixes to `POST /trip/{trip_id}/progress`. Send an ISO 8601 timestamp with timezone, a unique `update_id`, coordinates, and reported accuracy in meters:

```js
async function sendProgress({ tripId, token, position, gallonsAdded }) {
  const body = {
    update_id: crypto.randomUUID(),
    observed_at: new Date(position.timestamp).toISOString(),
    latitude: position.coords.latitude,
    longitude: position.coords.longitude,
    accuracy_meters: position.coords.accuracy,
  };
  if (gallonsAdded != null) body.gallons_added = gallonsAdded;

  const response = await fetch(
    `${API_BASE_URL}/trip/${encodeURIComponent(tripId)}/progress`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
    },
  );
  const result = await response.json();
  if (!response.ok) throw new Error(result.error ?? "Could not update trip");
  return result;
}
```

Send `gallons_added` in the same progress request when the user reports refueling. It means gallons added, not the new total fuel level. The backend adds it to its estimate and rejects a value that would put fuel above tank capacity. Use a fresh GPS fix if available. Apply the returned trip state to the UI after every successful update; avoid maintaining a separate client-side fuel/range calculation as the source of truth.

The client may throttle location updates to manage battery/network use, but should send fresh fixes during an active trip and after meaningful movement. Fixes with accuracy worse than 50 meters do not affect route progress (a reported refuel is still processed). The backend refreshes station recommendations after refueling, rerouting, returning to the route, or roughly each half-mile of progress; the UI should display the recommendations returned by the API rather than trying to reproduce that logic.

`update_status` is `accepted`, `duplicate`, or `stale`. Duplicate and stale updates are safe to handle as successful responses: use the returned current trip state, but do not show the same refuel as newly applied a second time. If a network timeout makes it unclear whether a request arrived, retry the exact same body with the same `update_id`; do not generate a new ID for that retry.

## 4. Resume or refresh

Call `GET /trip/{trip_id}` when the user reopens the active-trip screen or the client needs to reload state without sending a new GPS fix:

```js
const response = await fetch(
  `${API_BASE_URL}/trip/${encodeURIComponent(tripId)}`,
  { headers: { Authorization: `Bearer ${token}` } },
);
const trip = await response.json();
if (!response.ok) throw new Error(trip.error ?? "Could not load trip");
```

The response uses the same public trip-state shape as progress updates. A progress response already contains the latest state, so an extra GET after every accepted progress update is unnecessary.

## Showing trip state

- `status` is `created` in the initial start response, then `active` or `completed` on reads/updates. Stop location tracking when it becomes `completed`; there is no separate finish endpoint.
- `route` is GeoJSON. `origin`, `destination`, and `current_location` can be used for labels and map markers.
- `stations` and `station_status` describe the current recommendation result. If there is no safe recommendation, show the `warning` (for example, no station is reachable while keeping the reserve) and avoid presenting an empty list as “no fuel needed.” Other status values can include `off_route`, `route_unavailable`, or `unavailable`.
- `fuel_remaining_gallons`, `estimated_range_miles`, and `safe_range_miles` are estimates. Safe range keeps a 10% tank reserve. `fuel_needed_gallons` and `additional_gallons_needed` estimate the remaining trip requirement.
- Cost fields are estimates, not quotes. Station prices are synthetic EIA-based estimates, not live pump prices; `cost_price_assumption` explains how the current cost estimate is calculated. Show `price_note` wherever station prices are shown.

The estimates rely on reported fuel, GPS, and vehicle MPG—not live vehicle telemetry. Make it clear that actual fuel level, route conditions, and pump prices may differ.

## Errors and recovery

All error responses include an `error` string. Handle non-2xx responses before treating a response as trip state.

| HTTP status | Meaning / suggested UI behavior |
| --- | --- |
| `400` | Invalid input, invalid progress data, over-capacity refuel, or attempt to update a completed trip. Show a useful message; correct the input before retrying. |
| `401` | Missing or invalid trip token. Check that the saved token is sent as a Bearer token. |
| `404` | Trip ID was not found. Return to trip setup or explain that this trip is unavailable. |
| `409` | Concurrent update changed the trip. Reload with `GET /trip/{trip_id}`, then send a new progress event with a fresh ID and timestamp if needed. |
| `422` | Address could not be resolved or no route was found. Let the user correct the locations. |
| `502` / `503` | Upstream service, credentials, or backend configuration problem. Preserve the last displayed state and offer retry; do not assume fuel or progress was updated. |

The same `401`/`404` handling applies to reads and progress updates. `422` is used by preview/start; the progress endpoint does not use it. Never put backend API keys or Firebase service-account credentials in frontend configuration.
