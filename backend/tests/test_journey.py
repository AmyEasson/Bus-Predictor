
from datetime import date

import pandas as pd

from app.services import journey


def test_rejects_transfer_when_first_bus_continues_to_destination(monkeypatch):
    """A passenger should not need to change buses if their first bus
    already continues to the destination.
    """

    stop_times = pd.DataFrame([
        # First bus: origin -> interchange -> destination
        {
            "trip_id": "trip_101",
            "stop_id": "origin",
            "stop_sequence": 1,
            "departure_time": "08:00:00",
            "dep_s": 28800,
            "arrival_time": "08:00:00",
            "arr_s": 28800,
        },
        {
            "trip_id": "trip_101",
            "stop_id": "interchange",
            "stop_sequence": 2,
            "departure_time": "08:05:00",
            "dep_s": 29100,
            "arrival_time": "08:05:00",
            "arr_s": 29100,
        },
        {
            "trip_id": "trip_101",
            "stop_id": "destination",
            "stop_sequence": 3,
            "departure_time": "08:10:00",
            "dep_s": 29400,
            "arrival_time": "08:10:00",
            "arr_s": 29400,
        },

        # Second bus: interchange -> destination
        {
            "trip_id": "trip_42",
            "stop_id": "interchange",
            "stop_sequence": 1,
            "departure_time": "08:10:00",
            "dep_s": 29400,
            "arrival_time": "08:10:00",
            "arr_s": 29400,
        },
        {
            "trip_id": "trip_42",
            "stop_id": "destination",
            "stop_sequence": 2,
            "departure_time": "08:15:00",
            "dep_s": 29700,
            "arrival_time": "08:15:00",
            "arr_s": 29700,
        },
    ])

    trips = pd.DataFrame([
        {
            "trip_id": "trip_101",
            "route_id": "route_101",
            "trip_headsign": "Piccadilly Gardens",
            "service_id": "service_1",
        },
        {
            "trip_id": "trip_42",
            "route_id": "route_42",
            "trip_headsign": "Piccadilly Gardens",
            "service_id": "service_1",
        },
    ])

    routes = pd.DataFrame([
        {
            "route_id": "route_101",
            "route_type": "3",
            "route_short_name": "101",
        },
        {
            "route_id": "route_42",
            "route_type": "3",
            "route_short_name": "42",
        },
    ])

    stops = pd.DataFrame([
        {
            "stop_id": "origin",
            "stop_name": "Oxford Road",
            "stop_lat": 53.474,
            "stop_lon": -2.242,
        },
        {
            "stop_id": "interchange",
            "stop_name": "Dickinson Street",
            "stop_lat": 53.478,
            "stop_lon": -2.240,
        },
        {
            "stop_id": "destination",
            "stop_name": "Piccadilly Gardens",
            "stop_lat": 53.480,
            "stop_lon": -2.237,
        },
    ])

    monkeypatch.setattr(
        journey,
        "load_timetable_data",
        lambda: (stop_times, trips, routes, stops),
    )

    monkeypatch.setattr(
        journey,
        "get_active_service_ids",
        lambda travel_date: {"service_1"},
    )

    results = journey.find_transfer_journeys(
        origin_stop_id="origin",
        destination_stop_id="destination",
        travel_date=date(2026, 11, 9),
    )

    assert results == []


def test_accepts_valid_transfer(monkeypatch):
    """A transfer should be returned when the first bus does not reach
    the destination and the second bus completes the journey.
    """

    stop_times = pd.DataFrame([
        # First bus: origin -> interchange (then terminates)
        {
            "trip_id": "trip_101",
            "stop_id": "origin",
            "stop_sequence": 1,
            "departure_time": "08:00:00",
            "dep_s": 28800,
            "arrival_time": "08:00:00",
            "arr_s": 28800,
        },
        {
            "trip_id": "trip_101",
            "stop_id": "interchange",
            "stop_sequence": 2,
            "departure_time": "08:10:00",
            "dep_s": 29400,
            "arrival_time": "08:10:00",
            "arr_s": 29400,
        },

        # Second bus: interchange -> destination
        {
            "trip_id": "trip_42",
            "stop_id": "interchange",
            "stop_sequence": 1,
            "departure_time": "08:15:00",
            "dep_s": 29700,
            "arrival_time": "08:15:00",
            "arr_s": 29700,
        },
        {
            "trip_id": "trip_42",
            "stop_id": "destination",
            "stop_sequence": 2,
            "departure_time": "08:25:00",
            "dep_s": 30300,
            "arrival_time": "08:25:00",
            "arr_s": 30300,
        },
    ])

    trips = pd.DataFrame([
        {
            "trip_id": "trip_101",
            "route_id": "route_101",
            "trip_headsign": "Interchange",
            "service_id": "service_1",
        },
        {
            "trip_id": "trip_42",
            "route_id": "route_42",
            "trip_headsign": "Destination",
            "service_id": "service_1",
        },
    ])

    routes = pd.DataFrame([
        {
            "route_id": "route_101",
            "route_type": "3",
            "route_short_name": "101",
        },
        {
            "route_id": "route_42",
            "route_type": "3",
            "route_short_name": "42",
        },
    ])

    stops = pd.DataFrame([
        {
            "stop_id": "origin",
            "stop_name": "Oxford Road",
            "stop_lat": 53.474,
            "stop_lon": -2.242,
        },
        {
            "stop_id": "interchange",
            "stop_name": "Dickinson Street",
            "stop_lat": 53.478,
            "stop_lon": -2.240,
        },
        {
            "stop_id": "destination",
            "stop_name": "Piccadilly Gardens",
            "stop_lat": 53.480,
            "stop_lon": -2.237,
        },
    ])

    monkeypatch.setattr(
        journey,
        "load_timetable_data",
        lambda: (stop_times, trips, routes, stops),
    )

    monkeypatch.setattr(
        journey,
        "get_active_service_ids",
        lambda travel_date: {"service_1"},
    )

    results = journey.find_transfer_journeys(
        origin_stop_id="origin",
        destination_stop_id="destination",
        travel_date=date(2026, 11, 9),
    )

    assert len(results) == 1

    result = results[0]

    assert result["journey_type"] == "transfer"
    assert result["legs"][0]["route"] == "101"
    assert result["legs"][1]["route"] == "42"
    assert result["interchange_stop"]["stop_id"] == "interchange"
    assert result["transfer_wait_minutes"] == 5
    assert result["duration_minutes"] == 25


def test_transfer_wait_time_boundaries(monkeypatch):
    """Reject waits below 5 or above 30 minutes, but accept exactly 5."""

    def make_timetable(wait_minutes):
        first_arrival = 8 * 3600 + 10 * 60
        second_departure = first_arrival + wait_minutes * 60

        stop_times = pd.DataFrame([
            {
                "trip_id": "trip_101",
                "stop_id": "origin",
                "stop_sequence": 1,
                "departure_time": "08:00:00",
                "dep_s": 28800,
                "arrival_time": "08:00:00",
                "arr_s": 28800,
            },
            {
                "trip_id": "trip_101",
                "stop_id": "interchange",
                "stop_sequence": 2,
                "departure_time": "08:10:00",
                "dep_s": first_arrival,
                "arrival_time": "08:10:00",
                "arr_s": first_arrival,
            },
            {
                "trip_id": "trip_42",
                "stop_id": "interchange",
                "stop_sequence": 1,
                "departure_time": (
                    f"{second_departure // 3600:02d}:"
                    f"{(second_departure % 3600) // 60:02d}:00"
                ),
                "dep_s": second_departure,
                "arrival_time": (
                    f"{second_departure // 3600:02d}:"
                    f"{(second_departure % 3600) // 60:02d}:00"
                ),
                "arr_s": second_departure,
            },
            {
                "trip_id": "trip_42",
                "stop_id": "destination",
                "stop_sequence": 2,
                "departure_time": "09:00:00",
                "dep_s": 32400,
                "arrival_time": "09:00:00",
                "arr_s": 32400,
            },
        ])

        trips = pd.DataFrame([
            {
                "trip_id": "trip_101",
                "route_id": "route_101",
                "trip_headsign": "Interchange",
                "service_id": "service_1",
            },
            {
                "trip_id": "trip_42",
                "route_id": "route_42",
                "trip_headsign": "Destination",
                "service_id": "service_1",
            },
        ])

        routes = pd.DataFrame([
            {
                "route_id": "route_101",
                "route_type": "3",
                "route_short_name": "101",
            },
            {
                "route_id": "route_42",
                "route_type": "3",
                "route_short_name": "42",
            },
        ])

        stops = pd.DataFrame([
            {
                "stop_id": "origin",
                "stop_name": "Origin",
                "stop_lat": 53.474,
                "stop_lon": -2.242,
            },
            {
                "stop_id": "interchange",
                "stop_name": "Interchange",
                "stop_lat": 53.478,
                "stop_lon": -2.240,
            },
            {
                "stop_id": "destination",
                "stop_name": "Destination",
                "stop_lat": 53.480,
                "stop_lon": -2.237,
            },
        ])

        return stop_times, trips, routes, stops

    def find_journeys(wait_minutes):
        timetable = make_timetable(wait_minutes)

        monkeypatch.setattr(
            journey,
            "load_timetable_data",
            lambda: timetable,
        )
        monkeypatch.setattr(
            journey,
            "get_active_service_ids",
            lambda travel_date: {"service_1"},
        )

        return journey.find_transfer_journeys(
            origin_stop_id="origin",
            destination_stop_id="destination",
            travel_date=date(2026, 11, 9),
        )

    assert find_journeys(4) == []
    assert len(find_journeys(5)) == 1
    assert find_journeys(31) == []


def test_deduplicates_same_pair_of_trips(monkeypatch):
    """The same two trips should only produce one journey, even if they
    share multiple possible interchange stops.
    """

    stop_times = pd.DataFrame([
        # First bus: origin -> interchange A -> interchange B
        {
            "trip_id": "trip_101",
            "stop_id": "origin",
            "stop_sequence": 1,
            "departure_time": "08:00:00",
            "dep_s": 28800,
            "arrival_time": "08:00:00",
            "arr_s": 28800,
        },
        {
            "trip_id": "trip_101",
            "stop_id": "interchange_a",
            "stop_sequence": 2,
            "departure_time": "08:05:00",
            "dep_s": 29100,
            "arrival_time": "08:05:00",
            "arr_s": 29100,
        },
        {
            "trip_id": "trip_101",
            "stop_id": "interchange_b",
            "stop_sequence": 3,
            "departure_time": "08:10:00",
            "dep_s": 29400,
            "arrival_time": "08:10:00",
            "arr_s": 29400,
        },

        # Second bus: serves both interchanges, then destination
        {
            "trip_id": "trip_42",
            "stop_id": "interchange_a",
            "stop_sequence": 1,
            "departure_time": "08:15:00",
            "dep_s": 29700,
            "arrival_time": "08:15:00",
            "arr_s": 29700,
        },
        {
            "trip_id": "trip_42",
            "stop_id": "interchange_b",
            "stop_sequence": 2,
            "departure_time": "08:20:00",
            "dep_s": 30000,
            "arrival_time": "08:20:00",
            "arr_s": 30000,
        },
        {
            "trip_id": "trip_42",
            "stop_id": "destination",
            "stop_sequence": 3,
            "departure_time": "08:30:00",
            "dep_s": 30600,
            "arrival_time": "08:30:00",
            "arr_s": 30600,
        },
    ])

    trips = pd.DataFrame([
        {
            "trip_id": "trip_101",
            "route_id": "route_101",
            "trip_headsign": "Interchange",
            "service_id": "service_1",
        },
        {
            "trip_id": "trip_42",
            "route_id": "route_42",
            "trip_headsign": "Destination",
            "service_id": "service_1",
        },
    ])

    routes = pd.DataFrame([
        {
            "route_id": "route_101",
            "route_type": "3",
            "route_short_name": "101",
        },
        {
            "route_id": "route_42",
            "route_type": "3",
            "route_short_name": "42",
        },
    ])

    stops = pd.DataFrame([
        {
            "stop_id": "origin",
            "stop_name": "Origin",
            "stop_lat": 53.474,
            "stop_lon": -2.242,
        },
        {
            "stop_id": "interchange_a",
            "stop_name": "Interchange A",
            "stop_lat": 53.478,
            "stop_lon": -2.240,
        },
        {
            "stop_id": "interchange_b",
            "stop_name": "Interchange B",
            "stop_lat": 53.479,
            "stop_lon": -2.239,
        },
        {
            "stop_id": "destination",
            "stop_name": "Destination",
            "stop_lat": 53.480,
            "stop_lon": -2.237,
        },
    ])

    monkeypatch.setattr(
        journey,
        "load_timetable_data",
        lambda: (stop_times, trips, routes, stops),
    )

    monkeypatch.setattr(
        journey,
        "get_active_service_ids",
        lambda travel_date: {"service_1"},
    )

    results = journey.find_transfer_journeys(
        origin_stop_id="origin",
        destination_stop_id="destination",
        travel_date=date(2026, 11, 9),
    )

    assert len(results) == 1
    assert results[0]["legs"][0]["trip_id"] == "trip_101"
    assert results[0]["legs"][1]["trip_id"] == "trip_42"
