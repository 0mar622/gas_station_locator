from flask import Flask, render_template, request
from google.auth.exceptions import GoogleAuthError
from requests.exceptions import RequestException

if __package__:
    from .services.getFirebase import get_stations
    from .services.routing import (
        AddressNotFoundError,
        RouteConfigurationError,
        RouteNotFoundError,
        plan_trip,
    )
    from .services.stations import get_nearby_stations
    from .services.trip import (
        TripAuthorizationError,
        TripConflictError,
        TripNotFoundError,
        token_from_header,
    )
    from .services.trip_tracking import (
        get_active_trip,
        start_active_trip,
        update_active_trip,
    )
else:
    from services.getFirebase import get_stations
    from services.routing import (
        AddressNotFoundError,
        RouteConfigurationError,
        RouteNotFoundError,
        plan_trip,
    )
    from services.stations import get_nearby_stations
    from services.trip import (
        TripAuthorizationError,
        TripConflictError,
        TripNotFoundError,
        token_from_header,
    )
    from services.trip_tracking import (
        get_active_trip,
        start_active_trip,
        update_active_trip,
    )

app = Flask(__name__, template_folder="templates", static_folder="static")


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/trip/start")
def start_trip():
    try:
        return start_active_trip(request.get_json(silent=True)), 201
    except AddressNotFoundError as error:
        return {"error": str(error)}, 422
    except RouteNotFoundError as error:
        return {"error": str(error)}, 422
    except ValueError as error:
        return {"error": str(error)}, 400
    except RouteConfigurationError:
        return {"error": "Check the OpenRouteService API key configuration."}, 503
    except RuntimeError:
        return {"error": "Check the backend Firestore credential configuration."}, 503
    except (GoogleAuthError, RequestException):
        return {"error": "Unable to start or save the trip."}, 502


@app.post("/trip/<trip_id>/progress")
def update_trip_progress(trip_id):
    try:
        token = token_from_header(request.headers.get("Authorization"))
        return update_active_trip(trip_id, token, request.get_json(silent=True)), 200
    except TripAuthorizationError as error:
        return {"error": str(error)}, 401
    except TripNotFoundError as error:
        return {"error": str(error)}, 404
    except TripConflictError as error:
        return {"error": str(error)}, 409
    except ValueError as error:
        return {"error": str(error)}, 400
    except RouteConfigurationError:
        return {"error": "Check the OpenRouteService API key configuration."}, 503
    except RuntimeError:
        return {"error": "Check the backend Firestore credential configuration."}, 503
    except (GoogleAuthError, RequestException):
        return {"error": "Unable to update trip progress."}, 502


@app.get("/trip/<trip_id>")
def read_trip(trip_id):
    try:
        token = token_from_header(request.headers.get("Authorization"))
        return get_active_trip(trip_id, token), 200
    except TripAuthorizationError as error:
        return {"error": str(error)}, 401
    except TripNotFoundError as error:
        return {"error": str(error)}, 404
    except RuntimeError:
        return {"error": "Check the backend Firestore credential configuration."}, 503
    except (GoogleAuthError, RequestException):
        return {"error": "Unable to read the trip."}, 502


@app.post("/trip/plan")
def preview_trip():
    try:
        return plan_trip(request.get_json(silent=True)), 200
    except AddressNotFoundError as error:
        return {"error": str(error)}, 422
    except RouteNotFoundError as error:
        return {"error": str(error)}, 422
    except ValueError as error:
        return {"error": str(error)}, 400
    except RouteConfigurationError:
        return {"error": "Check the OpenRouteService API key configuration."}, 503
    except RuntimeError:
        return {"error": "Check the backend Firestore credential configuration."}, 503
    except (GoogleAuthError, RequestException):
        return {"error": "Unable to calculate the route or fetch stations."}, 502


@app.get("/stations")
def stations():
    try:
        return get_stations(request.args.get("pageToken"))
    except RuntimeError:
        return {"error": "Check the backend Firestore credential configuration."}, 503
    except (GoogleAuthError, RequestException):
        return {"error": "Unable to fetch stations from Firestore."}, 502


@app.get("/stations/nearby")
def nearby_stations():
    try:
        stations = get_nearby_stations(
            request.args.get("latitude"),
            request.args.get("longitude"),
            request.args.get("fuel_type"),
            request.args.get("radius_miles", 10),
            request.args.get("max_price"),
        )
        return {"stations": stations}
    except (TypeError, ValueError):
        return {"error": "Check the station query parameters"}, 400
    except RuntimeError:
        return {"error": "Check the backend Firestore credential configuration."}, 503
    except (GoogleAuthError, RequestException):
        return {"error": "Unable to fetch stations from Firestore."}, 502


if __name__ == "__main__":
    app.run()
