"""Generate an interactive driving map with local gas station markers."""

import json
from html import escape
from pathlib import Path

import folium
import requests


def _coordinates(lat, lng, label):
    """Validate and normalize a latitude/longitude pair."""
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}: lat and lng must be numbers") from exc
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError(f"{label}: coordinates are out of range")
    return lat, lng


def generate_map(start_lat, start_lng, end_lat, end_lng, json_path):
    """Fetch an OSRM driving route and save a Folium map; return its Path.

    json_path must contain a JSON list of objects with name, lat, lng,
    and optional address fields. All stations are shown. The output is
    route_map.html beside the JSON file; an existing output is overwritten.

    File/JSON errors, invalid station data, and requests errors propagate
    to the caller. OSRM routing failures raise RuntimeError.
    """
    start = _coordinates(start_lat, start_lng, "Start")
    end = _coordinates(end_lat, end_lng, "Destination")
    json_path = Path(json_path).expanduser().resolve()
    with json_path.open(encoding="utf-8") as file:
        stations = json.load(file)
    if not isinstance(stations, list):
        raise ValueError("Gas station JSON must contain a list of stations")

    station_markers = []
    for index, station in enumerate(stations):
        if not isinstance(station, dict) or not {"name", "lat", "lng"} <= station.keys():
            raise ValueError(f"Station {index}: expected name, lat, and lng fields")
        location = _coordinates(station["lat"], station["lng"], f"Station {index}")
        popup = f"<b>{escape(str(station['name']))}</b>"
        if station.get("address"):
            popup += f"<br>{escape(str(station['address']))}"
        station_markers.append((location, popup))

    coordinates = f"{start[1]},{start[0]};{end[1]},{end[0]}"
    response = requests.get(
        f"https://router.project-osrm.org/route/v1/driving/{coordinates}",
        params={"overview": "full", "geometries": "geojson"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        raise RuntimeError(f"OSRM could not find a route: {data.get('message', data)}")
    route = data["routes"][0]
    route_points = [(lat, lng) for lng, lat in route["geometry"]["coordinates"]]
    if not route_points:
        raise RuntimeError("OSRM returned an empty route")

    route_map = folium.Map(location=start, zoom_start=12)
    folium.Marker(start, popup="Start", icon=folium.Icon(color="green")).add_to(route_map)
    folium.Marker(end, popup="Destination", icon=folium.Icon(color="red")).add_to(route_map)
    folium.PolyLine(
        route_points,
        color="blue",
        weight=5,
        opacity=0.8,
        tooltip=f"{route['distance'] / 1000:.1f} km",
    ).add_to(route_map)

    gas_layer = folium.FeatureGroup(name="Gas stations").add_to(route_map)
    for location, popup in station_markers:
        folium.Marker(
            location,
            popup=folium.Popup(popup, max_width=300),
            icon=folium.Icon(color="orange", icon="gas-pump", prefix="fa"),
        ).add_to(gas_layer)
    folium.LayerControl().add_to(route_map)
    route_map.fit_bounds([start, end] + route_points + [p for p, _ in station_markers])

    output = json_path.parent / "route_map.html"
    route_map.save(str(output))
    return output


'''
if __name__ == "__main__":
    import webbrowser

    output = generate_map(
        37.5485, -121.9886,
        37.6577, -122.0578,
        Path(__file__).parent / "gas_stations.json",
    )
    webbrowser.open(output.as_uri())
'''