
from pathlib import Path
from functools import lru_cache

import pandas as pd


# Project root / data directory
DATA_PATH = Path(__file__).resolve().parents[3] / "data"


@lru_cache(maxsize=1)
def load_timetable_data():
    """Load and cache the GTFS timetable datasets."""

    stop_times = pd.read_parquet(DATA_PATH / "stop_times.parquet")
    trips = pd.read_parquet(DATA_PATH / "trips.parquet")
    routes = pd.read_parquet(DATA_PATH / "routes.parquet")
    stops = pd.read_parquet(DATA_PATH / "stops.parquet")

    # Normalise IDs so joins work consistently
    for df, columns in [
        (stop_times, ["trip_id", "stop_id"]),
        (trips, ["trip_id", "route_id"]),
        (routes, ["route_id", "route_type"]),
        (stops, ["stop_id"]),
    ]:
        for column in columns:
            df[column] = df[column].astype(str)

    # Only include bus services (GTFS route_type 3)
    bus_routes = routes[routes["route_type"] == "3"].copy()
    bus_trips = trips[trips["route_id"].isin(bus_routes["route_id"])].copy()

    return stop_times, bus_trips, bus_routes, stops


def find_direct_journeys(
    origin_stop_id: str,
    destination_stop_id: str,
    limit: int = 10,
):
    """
    Find scheduled direct bus journeys between two stops.

    A journey is valid when the bus visits the origin before
    the destination on the same trip.
    """

    stop_times, trips, routes, stops = load_timetable_data()

    origin_stop_id = str(origin_stop_id)
    destination_stop_id = str(destination_stop_id)

    if origin_stop_id == destination_stop_id:
        return []

    # Find scheduled departures from the origin
    origin_times = stop_times[
        stop_times["stop_id"] == origin_stop_id
    ][
        ["trip_id", "stop_sequence", "departure_time", "dep_s"]
    ].rename(columns={
        "stop_sequence": "origin_sequence",
        "departure_time": "departure_time",
        "dep_s": "departure_seconds",
    })

    # Find scheduled arrivals at the destination
    destination_times = stop_times[
        stop_times["stop_id"] == destination_stop_id
    ][
        ["trip_id", "stop_sequence", "arrival_time", "arr_s"]
    ].rename(columns={
        "stop_sequence": "destination_sequence",
        "arrival_time": "arrival_time",
        "arr_s": "arrival_seconds",
    })

    if origin_times.empty or destination_times.empty:
        return []

    # Match origin and destination stops on the same trip
    journeys = origin_times.merge(
        destination_times,
        on="trip_id",
        how="inner",
    )

    # The origin must occur before the destination
    journeys = journeys[
        journeys["origin_sequence"] < journeys["destination_sequence"]
    ].copy()

    if journeys.empty:
        return []

    # Add trip and route information
    journeys = journeys.merge(
        trips[["trip_id", "route_id", "trip_headsign", "service_id"]],
        on="trip_id",
        how="left",
    )

    journeys = journeys.merge(
        routes[["route_id", "route_short_name"]],
        on="route_id",
        how="left",
    )

    # Calculate duration using seconds rather than clock strings.
    # This correctly handles GTFS times such as 24:01:00.
    journeys["duration_seconds"] = (
        pd.to_numeric(journeys["arrival_seconds"], errors="coerce")
        - pd.to_numeric(journeys["departure_seconds"], errors="coerce")
    )

    journeys = journeys[
        journeys["duration_seconds"].notna()
        & (journeys["duration_seconds"] >= 0)
    ].copy()

    # Earliest departures first
    journeys = journeys.sort_values(
        ["departure_seconds", "arrival_seconds"]
    ).head(limit)

    results = []

    for _, journey in journeys.iterrows():

        # Get all stops between the selected origin and destination
        journey_stops = stop_times[
            (stop_times["trip_id"] == journey["trip_id"])
            & (
                stop_times["stop_sequence"]
                >= journey["origin_sequence"]
            )
            & (
                stop_times["stop_sequence"]
                <= journey["destination_sequence"]
            )
        ].sort_values("stop_sequence")

        journey_stops = journey_stops.merge(
            stops[
                ["stop_id", "stop_name", "stop_lat", "stop_lon"]
            ],
            on="stop_id",
            how="left",
        )

        intermediate_stops = journey_stops[
            [
                "stop_id",
                "stop_name",
                "stop_lat",
                "stop_lon",
                "stop_sequence",
                "arrival_time",
                "departure_time",
            ]
        ].to_dict(orient="records")

        results.append({
            "trip_id": journey["trip_id"],
            "route": journey["route_short_name"],
            "destination": journey["trip_headsign"],
            "service_id": journey["service_id"],
            "departure_time": journey["departure_time"],
            "arrival_time": journey["arrival_time"],
            "duration_minutes": round(
                journey["duration_seconds"] / 60
            ),
            "stops": intermediate_stops,
        })

    return results
