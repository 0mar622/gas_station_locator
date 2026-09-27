from unittest.mock import MagicMock

from server.services.recommendation import rank_reachable_stations
from server.services.routing import _get_matrix_distances
from server.services.stations import closest_route_projection


def test_rank_reachable_stations_filters_unsafe_and_scores_price_and_detour():
    candidates = [
        {"id": "cheap", "price": 4.0, "route_progress_miles": 4.0},
        {"id": "balanced", "price": 4.5, "route_progress_miles": 3.0},
        {"id": "unsafe", "price": 3.0, "route_progress_miles": 8.0},
    ]
    # Sources: current, then each station. Destinations: stations, then
    # each station's route projection, in meters.
    distances = [
        [3 * 1609.344, 2 * 1609.344, 8 * 1609.344, 3 * 1609.344, 2 * 1609.344, 8 * 1609.344],
        [0, 0, 0, 1 * 1609.344, 1 * 1609.344, 1 * 1609.344],
        [0, 0, 0, 1 * 1609.344, 1 * 1609.344, 1 * 1609.344],
        [0, 0, 0, 1 * 1609.344, 1 * 1609.344, 1 * 1609.344],
    ]

    ranked = rank_reachable_stations(candidates, distances, 0, 5)

    assert {station["id"] for station in ranked} == {"cheap", "balanced"}
    assert all(station["within_safe_range"] for station in ranked)
    assert ranked[0]["recommendation_score"] <= ranked[1]["recommendation_score"]


def test_rank_equal_candidates_uses_route_progress_tie_break():
    candidates = [
        {"id": "later", "price": 4.0, "route_progress_miles": 3.0},
        {"id": "earlier", "price": 4.0, "route_progress_miles": 2.0},
    ]
    distances = [
        [2 * 1609.344, 2 * 1609.344, 2 * 1609.344, 2 * 1609.344],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]

    ranked = rank_reachable_stations(candidates, distances, 0, 5)

    assert [station["id"] for station in ranked] == ["earlier", "later"]


def test_matrix_query_batches_current_and_station_route_distances():
    session = MagicMock()
    session.post.return_value.json.return_value = {"distances": [[10, 2], [4, 1]]}
    candidates = [{
        "longitude": -122.1,
        "latitude": 37.7,
        "route_projection": [-122.11, 37.71],
    }]

    distances = _get_matrix_distances(
        session,
        {"longitude": -122.0, "latitude": 37.6},
        candidates,
        "test-key",
    )

    assert distances == [[10, 2], [4, 1]]
    assert session.post.call_args.args[0].endswith("/matrix/driving-car")
    assert session.post.call_args.kwargs["json"]["sources"] == ["0", "1"]
    assert session.post.call_args.kwargs["json"]["destinations"] == ["1", "2"]


def test_route_progress_scales_polyline_fraction_to_driving_distance():
    _, progress, _ = closest_route_projection(
        0.0,
        0.05,
        [[0.0, 0.0], [0.1, 0.0]],
        route_distance_miles=10,
    )

    assert progress == 5
