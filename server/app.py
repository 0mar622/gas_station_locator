from flask import Flask, request
from google.auth.exceptions import GoogleAuthError
from requests.exceptions import RequestException

if __package__:
    from .services.getFirebase import get_stations
else:
    from services.getFirebase import get_stations

app = Flask(__name__)


@app.get("/health")
def health():
    return {"status": "ok"}


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
