from flask import Flask, request
from google.auth.exceptions import GoogleAuthError
from requests.exceptions import RequestException

if __package__:
    from .services.getFirebase import get_stations
    from .services.trip import save_trip, validate_trip
else:
    from services.getFirebase import get_stations
    from services.trip import save_trip, validate_trip

app = Flask(__name__)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/trip")
def create_trip():
    trip, errors = validate_trip(request.get_json(silent=True))
    if errors:
        return {"error": "Invalid trip details.", "fields": errors}, 400
    try:
        saved_trip = save_trip(trip)
    except RuntimeError:
        return {"error": "Check the backend Firestore credential configuration."}, 503
    except (GoogleAuthError, RequestException):
        return {"error": "Unable to confirm the trip was saved to Firestore."}, 502
    return {"status": "created", **saved_trip}, 201


@app.get("/stations")
def stations():
    try:
        return get_stations(request.args.get("pageToken"))
    except RuntimeError:
        return {"error": "Check the backend Firestore credential configuration."}, 503
    except (GoogleAuthError, RequestException):
        return {"error": "Unable to fetch stations from Firestore."}, 502


if __name__ == "__main__":
    app.run()
