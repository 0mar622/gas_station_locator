"""Rank safe station candidates by price and driving detour."""


METERS_PER_MILE = 1609.344


def _normalize(values):
    if not values:
        return []
    minimum = min(values)
    maximum = max(values)
    if maximum == minimum:
        return [0.0] * len(values)
    return [(value - minimum) / (maximum - minimum) for value in values]


def rank_reachable_stations(candidates, matrix_distances, current_progress_miles, safe_range_miles):
    """Filter to stations reachable on current fuel and rank with equal weights.

    Matrix source row zero is the current position, followed by each station.
    Matrix destination columns contain all stations followed by each station's
    route projection.
    """
    count = len(candidates)
    reachable = []
    for index, station in enumerate(candidates):
        try:
            to_station = matrix_distances[0][index]
            to_projection = matrix_distances[index + 1][count + index]
            current_to_projection = matrix_distances[0][count + index]
        except (IndexError, TypeError):
            continue
        if any(value is None for value in (to_station, to_projection, current_to_projection)):
            continue

        route_delta = station["route_progress_miles"] - current_progress_miles
        if route_delta < -0.25:
            continue
        route_delta = max(0.0, route_delta)
        to_station_miles = to_station / METERS_PER_MILE
        detour_miles = max(
            0.0,
            (to_station + to_projection - current_to_projection) / METERS_PER_MILE,
        )
        if to_station_miles > safe_range_miles:
            continue

        reachable.append({
            **station,
            "driving_distance_miles": round(to_station_miles, 2),
            "detour_miles": round(detour_miles, 2),
            "within_safe_range": True,
        })

    price_scores = _normalize([station["price"] for station in reachable])
    detour_scores = _normalize([station["detour_miles"] for station in reachable])
    for station, price_score, detour_score in zip(reachable, price_scores, detour_scores):
        station["recommendation_score"] = round((price_score + detour_score) / 2, 4)

    return sorted(
        reachable,
        key=lambda station: (
            station["recommendation_score"],
            station["route_progress_miles"],
            station["id"],
        ),
    )
