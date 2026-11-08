
from pathlib import Path
from functools import lru_cache
from datetime import date

import pandas as pd


# Project root / data directory
DATA_PATH = Path(__file__).resolve().parents[3] / "data"


# Transfer journey constraints (seconds)
MIN_TRANSFER_WAIT = 5 * 60
MAX_TRANSFER_WAIT = 30 * 60
MAX_JOURNEY_DURATION = 120 * 60


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
    bus_trips = trips[
        trips["route_id"].isin(bus_routes["route_id"])
    ].copy()

    return stop_times, bus_trips, bus_routes, stops


def get_active_service_ids(travel_date: date):
    """Return all GTFS services operating on a particular date."""

    load_timetable_data()

    calendar = pd.read_parquet(DATA_PATH / "calendar.parquet")
    exceptions = pd.read_parquet(DATA_PATH / "calendar_dates.parquet")

    date_string = travel_date.strftime("%Y%m%d")

    weekday_columns = [
        "monday", "tuesday", "wednesday", "thursday",
        "friday", "saturday", "sunday"
    ]

    weekday_column = weekday_columns[travel_date.weekday()]

    active = calendar[
        (calendar["start_date"] <= date_string)
        & (calendar["end_date"] >= date_string)
        & (calendar[weekday_column] == "1")
    ]

    active_service_ids = set(active["service_id"])

    date_exceptions = exceptions[
        exceptions["date"] == date_string
    ]

    for _, exception in date_exceptions.iterrows():
        service_id = exception["service_id"]

        if exception["exception_type"] == "1":
            active_service_ids.add(service_id)
        elif exception["exception_type"] == "2":
            active_service_ids.discard(service_id)

    return active_service_ids


def find_direct_journeys(
    origin_stop_id: str,
    destination_stop_id: str,
    travel_date: date,
    limit: int = 10,
    departure_after: str | None = None,
    arrive_by: str | None = None,
):
    """Find scheduled direct bus journeys between two stops."""

    stop_times, trips, routes, stops = load_timetable_data()

    origin_stop_id = str(origin_stop_id)
    destination_stop_id = str(destination_stop_id)

    if origin_stop_id == destination_stop_id:
        return []

    origin_times = stop_times[
        stop_times["stop_id"] == origin_stop_id
    ][
        ["trip_id", "stop_sequence", "departure_time", "dep_s"]
    ].rename(columns={
        "stop_sequence": "origin_sequence",
        "departure_time": "departure_time",
        "dep_s": "departure_seconds",
    })

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

    journeys = origin_times.merge(
        destination_times,
        on="trip_id",
        how="inner",
    )

    if journeys.empty:
        return []

    journeys = journeys[
        journeys["origin_sequence"] < journeys["destination_sequence"]
    ].copy()

    if journeys.empty:
        return []

    journeys = journeys.merge(
        trips[["trip_id", "route_id", "trip_headsign", "service_id"]],
        on="trip_id",
        how="left",
    )

    active_service_ids = get_active_service_ids(travel_date)

    journeys = journeys[
        journeys["service_id"].isin(active_service_ids)
    ].copy()

    if journeys.empty:
        return []

    journeys = journeys.merge(
        routes[["route_id", "route_short_name"]],
        on="route_id",
        how="left",
    )

    journeys["duration_seconds"] = (
        pd.to_numeric(journeys["arrival_seconds"], errors="coerce")
        - pd.to_numeric(journeys["departure_seconds"], errors="coerce")
    )

    journeys = journeys[
        journeys["duration_seconds"].notna()
        & (journeys["duration_seconds"] >= 0)
    ].copy()

    if departure_after:
        hours, minutes = map(int, departure_after.split(":"))
        departure_seconds = hours * 3600 + minutes * 60

        journeys = journeys[
            journeys["departure_seconds"] >= departure_seconds
        ].copy()

    if arrive_by:
        hours, minutes = map(int, arrive_by.split(":"))
        arrival_seconds = hours * 3600 + minutes * 60

        journeys = journeys[
            journeys["arrival_seconds"] <= arrival_seconds
        ].copy()

    journeys = journeys.sort_values(
        ["departure_seconds", "arrival_seconds"]
    ).head(limit)

    results = []

    for _, journey in journeys.iterrows():

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


def find_transfer_journeys(
    origin_stop_id: str,
    destination_stop_id: str,
    travel_date: date,
    limit: int = 10,
    departure_after: str | None = None,
    arrive_by: str | None = None,
):
    """Find journeys involving exactly one change of bus."""

    stop_times, trips, routes, stops = load_timetable_data()

    origin_stop_id = str(origin_stop_id)
    destination_stop_id = str(destination_stop_id)

    if origin_stop_id == destination_stop_id:
        return []

    active_service_ids = get_active_service_ids(travel_date)

    active_trips = trips[
        trips["service_id"].isin(active_service_ids)
    ].copy()

    if active_trips.empty:
        return []

    # Convert optional time filters into seconds
    departure_filter = None
    if departure_after:
        hours, minutes = map(int, departure_after.split(":"))
        departure_filter = hours * 3600 + minutes * 60

    arrival_filter = None
    if arrive_by:
        hours, minutes = map(int, arrive_by.split(":"))
        arrival_filter = hours * 3600 + minutes * 60

    # ---------------------------------------------------------
    # FIRST LEG: origin to possible interchange stops
    # ---------------------------------------------------------

    origin_times = stop_times[
        stop_times["stop_id"] == origin_stop_id
    ][
        ["trip_id", "stop_sequence", "departure_time", "dep_s"]
    ].rename(columns={
        "stop_sequence": "origin_sequence",
        "departure_time": "first_departure_time",
        "dep_s": "first_departure_seconds",
    })

    if origin_times.empty:
        return []

    origin_times = origin_times[
        origin_times["trip_id"].isin(active_trips["trip_id"])
    ].copy()

    if departure_filter is not None:
        origin_times = origin_times[
            origin_times["first_departure_seconds"] >= departure_filter
        ]

    if origin_times.empty:
        return []

    first_legs = origin_times.merge(
        stop_times[
            [
                "trip_id",
                "stop_id",
                "stop_sequence",
                "arrival_time",
                "arr_s",
            ]
        ],
        on="trip_id",
        how="inner",
    )

    first_legs = first_legs[
        first_legs["stop_sequence"] > first_legs["origin_sequence"]
    ].copy()

    first_legs = first_legs[
        ~first_legs["stop_id"].str.startswith("940")
    ].copy()

    if first_legs.empty:
        return []

    first_legs = first_legs.rename(columns={
        "stop_id": "interchange_stop_id",
        "stop_sequence": "interchange_sequence_first",
        "arrival_time": "first_arrival_time",
        "arr_s": "first_arrival_seconds",
    })

    first_legs = first_legs.merge(
        active_trips[
            ["trip_id", "route_id", "trip_headsign"]
        ].rename(columns={
            "trip_id": "first_trip_id",
            "route_id": "first_route_id",
            "trip_headsign": "first_headsign",
        }),
        left_on="trip_id",
        right_on="first_trip_id",
        how="inner",
    )

    first_legs = first_legs.merge(
        routes[["route_id", "route_short_name"]].rename(columns={
            "route_id": "first_route_id",
            "route_short_name": "first_route",
        }),
        on="first_route_id",
        how="left",
    )

    # ---------------------------------------------------------
    # SECOND LEG: possible interchange stops to destination
    # ---------------------------------------------------------

    destination_times = stop_times[
        stop_times["stop_id"] == destination_stop_id
    ][
        ["trip_id", "stop_sequence", "arrival_time", "arr_s"]
    ].rename(columns={
        "stop_sequence": "destination_sequence",
        "arrival_time": "second_arrival_time",
        "arr_s": "second_arrival_seconds",
    })

    if destination_times.empty:
        return []

    destination_times = destination_times[
        destination_times["trip_id"].isin(active_trips["trip_id"])
    ].copy()

    if destination_times.empty:
        return []

    second_legs = stop_times[
        [
            "trip_id",
            "stop_id",
            "stop_sequence",
            "departure_time",
            "dep_s",
        ]
    ].merge(
        destination_times,
        on="trip_id",
        how="inner",
    )

    second_legs = second_legs[
        second_legs["stop_sequence"] < second_legs["destination_sequence"]
    ].copy()

    second_legs = second_legs[
        ~second_legs["stop_id"].str.startswith("940")
    ].copy()

    if second_legs.empty:
        return []

    second_legs = second_legs.rename(columns={
        "stop_id": "interchange_stop_id",
        "stop_sequence": "interchange_sequence_second",
        "departure_time": "second_departure_time",
        "dep_s": "second_departure_seconds",
    })

    second_legs = second_legs.merge(
        active_trips[
            ["trip_id", "route_id", "trip_headsign"]
        ].rename(columns={
            "trip_id": "second_trip_id",
            "route_id": "second_route_id",
            "trip_headsign": "second_headsign",
        }),
        left_on="trip_id",
        right_on="second_trip_id",
        how="inner",
    )

    second_legs = second_legs.merge(
        routes[["route_id", "route_short_name"]].rename(columns={
            "route_id": "second_route_id",
            "route_short_name": "second_route",
        }),
        on="second_route_id",
        how="left",
    )

    # ---------------------------------------------------------
    # MATCH THE TWO LEGS AT THE SAME INTERCHANGE
    # ---------------------------------------------------------

    journeys = first_legs.merge(
        second_legs,
        on="interchange_stop_id",
        how="inner",
        suffixes=("_first", "_second"),
    )

    if journeys.empty:
        return []

    # Must be different trips AND different bus routes
    journeys = journeys[
        (journeys["first_trip_id"] != journeys["second_trip_id"])
        & (journeys["first_route_id"] != journeys["second_route_id"])
    ].copy()

    if journeys.empty:
        return []

    # Calculate waiting time at the interchange
    journeys["transfer_wait_seconds"] = (
        journeys["second_departure_seconds"]
        - journeys["first_arrival_seconds"]
    )

    journeys = journeys[
        (journeys["transfer_wait_seconds"] >= MIN_TRANSFER_WAIT)
        & (journeys["transfer_wait_seconds"] <= MAX_TRANSFER_WAIT)
    ].copy()

    if journeys.empty:
        return []

    # Calculate total journey duration
    journeys["duration_seconds"] = (
        journeys["second_arrival_seconds"]
        - journeys["first_departure_seconds"]
    )

    journeys = journeys[
        (journeys["duration_seconds"] >= 0)
        & (journeys["duration_seconds"] <= MAX_JOURNEY_DURATION)
    ].copy()

    if arrival_filter is not None:
        journeys = journeys[
            journeys["second_arrival_seconds"] <= arrival_filter
        ].copy()

    if journeys.empty:
        return []

    # Sort so that the earliest valid interchange is selected
    journeys = journeys.sort_values(
        [
            "first_departure_seconds",
            "second_arrival_seconds",
            "first_arrival_seconds",
            "transfer_wait_seconds",
        ]
    )

    # One result per pair of trips, not one per shared stop
    journeys = journeys.drop_duplicates(
        subset=["first_trip_id", "second_trip_id"],
        keep="first",
    )

    journeys = journeys.head(limit)

    # ---------------------------------------------------------
    # BUILD THE RESULT OBJECTS
    # ---------------------------------------------------------

    results = []

    stop_details = stops[
        ["stop_id", "stop_name", "stop_lat", "stop_lon"]
    ]

    stop_columns = [
        "stop_id",
        "stop_name",
        "stop_lat",
        "stop_lon",
        "stop_sequence",
        "arrival_time",
        "departure_time",
    ]

    for _, journey in journeys.iterrows():

        # Stops on the first leg
        first_leg_stops = stop_times[
            (stop_times["trip_id"] == journey["first_trip_id"])
            & (
                stop_times["stop_sequence"]
                >= journey["origin_sequence"]
            )
            & (
                stop_times["stop_sequence"]
                <= journey["interchange_sequence_first"]
            )
        ].sort_values("stop_sequence")

        # Stops on the second leg
        second_leg_stops = stop_times[
            (stop_times["trip_id"] == journey["second_trip_id"])
            & (
                stop_times["stop_sequence"]
                >= journey["interchange_sequence_second"]
            )
            & (
                stop_times["stop_sequence"]
                <= journey["destination_sequence"]
            )
        ].sort_values("stop_sequence")

        first_leg_stops = first_leg_stops.merge(
            stop_details,
            on="stop_id",
            how="left",
        )

        second_leg_stops = second_leg_stops.merge(
            stop_details,
            on="stop_id",
            how="left",
        )

        first_stops = first_leg_stops[
            stop_columns
        ].to_dict(orient="records")

        second_stops = second_leg_stops[
            stop_columns
        ].to_dict(orient="records")

        # Include the interchange only once in the combined route
        combined_stops = first_stops + second_stops[1:]

        interchange = first_stops[-1]

        results.append({
            "journey_type": "transfer",
            "departure_time": journey["first_departure_time"],
            "arrival_time": journey["second_arrival_time"],
            "duration_minutes": round(
                journey["duration_seconds"] / 60
            ),
            "transfer_wait_minutes": round(
                journey["transfer_wait_seconds"] / 60
            ),
            "interchange_stop": {
                "stop_id": journey["interchange_stop_id"],
                "stop_name": interchange["stop_name"],
                "stop_lat": interchange["stop_lat"],
                "stop_lon": interchange["stop_lon"],
            },
            "legs": [
                {
                    "trip_id": journey["first_trip_id"],
                    "route": journey["first_route"],
                    "destination": journey["first_headsign"],
                    "departure_time": journey["first_departure_time"],
                    "arrival_time": journey["first_arrival_time"],
                    "stops": first_stops,
                },
                {
                    "trip_id": journey["second_trip_id"],
                    "route": journey["second_route"],
                    "destination": journey["second_headsign"],
                    "departure_time": journey["second_departure_time"],
                    "arrival_time": journey["second_arrival_time"],
                    "stops": second_stops,
                },
            ],
            "stops": combined_stops,
        })

    return results
