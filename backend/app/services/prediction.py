"""Adds delay predictions to the journeys returned by journey.py.

Flow:  /api/journeys -> journey.py (timetable) -> annotate_journeys() -> delay_engine DelayModel
If the model can't load, journeys come back unchanged with prediction.covered = False,
so the planner keeps working from the timetable alone.
"""
import os
import sys
import zlib
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]  # repo root (same as DATA_PATH's parent in journey.py)
sys.path.insert(0, str(ROOT / "delay_engine" / "model"))

TZ = "Europe/London"

# The model was built to be told how late the bus is *right now*. For a future journey we
# don't know that, so we assume the bus is on time when it reaches the boarding stop.
# TODO: replace with the live delay of the matched bus when one is available.
ASSUMED_DELAY_NOW_S = 0.0

# Risk label from the "be safe" (P90) delay, in minutes. Placeholder thresholds - calibrate them.
RISK_LOW_MAX, RISK_MEDIUM_MAX = 3.0, 6.0

_model = None
_model_failed = False

# PREDICTION_MODE=mock invents predictions so the UI can be built before the real model exists.
# Never leave this on for a demo: every mock prediction is flagged "mock": true.
MOCK = os.environ.get("PREDICTION_MODE", "").lower() == "mock"


class MockModel:
    meta = {"categories": {}}

    def predict_arrival(self, route, direction, to_stop, to_lat, to_lon, now_utc, delay_now_s,
                        stops_ahead, sched_travel_s, scheduled_arrival_utc, **kw):
        hour = pd.Timestamp(now_utc).tz_convert(TZ).hour
        jitter = (zlib.crc32(f"{route}|{to_stop}|{hour}".encode()) % 150) / 100  # 0 to 1.5 min, stable
        p50 = (0.25 * stops_ahead + (1.5 if hour in (7, 8, 9, 16, 17, 18) else 0) + jitter) * 60
        p10, p90 = 0.3 * p50, 2.2 * p50 + 60
        s = pd.Timestamp(scheduled_arrival_utc)
        return {"delay_p10_s": p10, "delay_p50_s": p50, "delay_p90_s": p90,
                "arrival_p10": s + pd.Timedelta(seconds=p10), "arrival_p50": s + pd.Timedelta(seconds=p50),
                "arrival_p90": s + pd.Timedelta(seconds=p90)}



def get_model():
    """Load the DelayModel once. Returns None if it can't be loaded."""
    global _model, _model_failed
    if MOCK and _model is None:
        print("[prediction] MOCK MODE: predictions are invented, not from the model")
        _model = MockModel()
    if _model is None and not _model_failed:
        try:
            from predict import DelayModel  # delay_engine/model/predict.py
            _model = DelayModel(str(ROOT / "delay_engine" / "model" / "models"),
                                str(ROOT / "context"))
        except Exception as e:  # missing files, lightgbm not installed, ...
            print(f"[prediction] model not loaded: {e}")
            _model_failed = True
    return _model


@lru_cache(maxsize=1)
def _direction_lookup():
    from .journey import load_timetable_data
    trips = load_timetable_data()[1]
    if "direction_id" not in trips.columns:
        return {}
    return dict(zip(trips["trip_id"], trips["direction_id"].astype(str)))


def _hms(t):
    h, m, s = (int(x) for x in str(t).split(":"))
    return h * 3600 + m * 60 + s


def service_time_utc(travel_date, seconds):
    """GTFS time (seconds since the service day began, can pass 24h) -> UTC timestamp.
    The service day starts at local noon minus 12 h, as in compute_delays.py."""
    noon = pd.Timestamp(travel_date) + pd.Timedelta(hours=12)
    start = noon.tz_localize(TZ) - pd.Timedelta(hours=12)
    return (start + pd.Timedelta(seconds=float(seconds))).tz_convert("UTC")


def _local_hhmm(ts):
    return pd.Timestamp(ts).tz_convert(TZ).strftime("%H:%M")


def _risk(p90_min):
    return "low" if p90_min < RISK_LOW_MAX else "medium" if p90_min < RISK_MEDIUM_MAX else "high"


def _route_known(model, route):
    known = model.meta.get("categories", {}).get("route")
    return known is None or str(route) in {str(r) for r in known}


def predict_leg(model, travel_date, route, trip_id, stops):
    """One bus leg. `stops` runs from the boarding stop to the alighting stop."""
    if len(stops) < 2:
        return {"covered": False, "reason": "no_stops"}
    if not _route_known(model, route):
        return {"covered": False, "reason": "route_not_in_training_data"}

    board, alight = stops[0], stops[-1]
    dep_s, arr_s = _hms(board["departure_time"]), _hms(alight["arrival_time"])
    r = model.predict_arrival(
        route=route,
        direction=_direction_lookup().get(trip_id, ""),
        to_stop=alight["stop_id"], to_lat=alight["stop_lat"], to_lon=alight["stop_lon"],
        now_utc=service_time_utc(travel_date, dep_s),  # time of travel, so weather/events match
        delay_now_s=ASSUMED_DELAY_NOW_S,
        stops_ahead=len(stops) - 1,
        sched_travel_s=arr_s - dep_s,
        scheduled_arrival_utc=service_time_utc(travel_date, arr_s),
    )
    p50, p90 = r["delay_p50_s"] / 60, r["delay_p90_s"] / 60
    return {
        "covered": True,
        "delay_p10_min": round(r["delay_p10_s"] / 60, 1),
        "delay_p50_min": round(p50, 1),
        "delay_p90_min": round(p90, 1),
        "arrival_p50": _local_hhmm(r["arrival_p50"]),
        "arrival_p90": _local_hhmm(r["arrival_p90"]),
        "risk_level": _risk(p90),
        "_arrival_p90_s": (r["arrival_p90"] - service_time_utc(travel_date, 0)).total_seconds(),
    }


def _legs_of(journey):
    if journey.get("legs"):
        return journey["legs"]
    return [{"route": journey["route"], "trip_id": journey["trip_id"], "stops": journey.get("stops", [])}]


def annotate_journeys(journeys, travel_date):
    """Adds journey["prediction"] to each journey, in place. Call before stop lists are stripped."""
    model = get_model()
    for j in journeys:
        if model is None:
            j["prediction"] = {"covered": False, "reason": "model_unavailable"}
            continue
        try:
            legs = [predict_leg(model, travel_date, leg["route"], leg["trip_id"], leg.get("stops", []))
                    for leg in _legs_of(j)]
            if not all(l["covered"] for l in legs):
                reason = next(l["reason"] for l in legs if not l["covered"])
                j["prediction"] = {"covered": False, "reason": reason}
                continue
            last = legs[-1]
            pred = {k: last[k] for k in ("delay_p10_min", "delay_p50_min", "delay_p90_min",
                                         "arrival_p50", "arrival_p90", "risk_level")}
            pred["covered"] = True
            if MOCK:
                pred["mock"] = True
            if len(legs) > 1:
                # Could the first bus's safe arrival land after the second bus has left?
                next_dep = service_time_utc(travel_date, _hms(j["legs"][1]["stops"][0]["departure_time"]))
                first_p90 = service_time_utc(travel_date, 0) + pd.Timedelta(seconds=legs[0]["_arrival_p90_s"])
                pred["connection_at_risk"] = bool(first_p90 > next_dep)
            j["prediction"] = pred
        except Exception as e:
            j["prediction"] = {"covered": False, "reason": f"prediction_failed: {e}"}