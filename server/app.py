from flask import Flask, request
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
    from .services.trip import save_trip
else:
    from services.getFirebase import get_stations
    from services.routing import (
        AddressNotFoundError,
        RouteConfigurationError,
        RouteNotFoundError,
        plan_trip,
    )
    from services.stations import get_nearby_stations
    from services.trip import save_trip

app = Flask(__name__)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/trip")
def create_trip():
    try:
        return {"status": "created", **save_trip(request.get_json(silent=True))}, 201
    except (GoogleAuthError, RequestException):
        return {"error": "Unable to confirm the trip was saved to Firestore."}, 502
    except ValueError as error:
        return {"error": str(error)}, 400
    except RuntimeError:
        return {"error": "Check the backend Firestore credential configuration."}, 503


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
