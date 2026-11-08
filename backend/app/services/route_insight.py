"""Historical delay picture along a journey, from the delay engine's exports (backend/data/delay).

Amy's prediction.py answers "how late will this bus be" with the model. This answers the "where and why":
for every stretch the journey rides (stop A -> next stop B, at the time the bus is scheduled there), what buses
typically did there over the archive window, plus the share of that line's buses that run more than 5 min late
at that time of day (route_reliability_by_band.csv).

Adds journey["insight"] (call before stop lists are stripped):
  stretches        [{path, minutes, band, added_s, name, from_stop_id, to_stop_id}] for colouring the route
  typical_late_min lateness on arrival at the final stop, typically
  risk_pct         chance at least one leg's bus is >5 min late (from route reliability, legs independent)
  factors          time_of_day / weather / events, minutes, each with a sentence
  worst            the stretch where buses lose most time (for a map callout), or None
  explanation      one sentence for the result card
  coverage, observations, confidence   how much data this is based on
"""
import math
from datetime import date
from functools import lru_cache

import numpy as np
import pandas as pd

from . import delay

LATE_PCT_BANDS = ("AM peak (07-09)", "midday (09-16)", "PM peak (16-18)", "evening/early", "weekend")
VENUE_KM = 1.5


def _secs(t):
    h, m, s = (int(x) for x in str(t).split(":"))
    return h * 3600 + m * 60 + s


def _band_name(hour, weekend):
    """Same bands as delay_engine/archival_data/route_reliability.py."""
    if weekend:
        return "weekend"
    if hour in (7, 8):
        return "AM peak (07-09)"
    if 9 <= hour < 16:
        return "midday (09-16)"
    if hour in (16, 17):
        return "PM peak (16-18)"
    return "evening/early"


@lru_cache(maxsize=1)
def _segment_index():
    s = delay.segments()
    return s.set_index(["from_stop_id", "to_stop_id", "is_weekend", "hour"]).sort_index()


@lru_cache(maxsize=1)
def _reliability():
    p = delay.DATA / "route_reliability_by_band.csv"
    if not p.exists():
        return {}
    r = pd.read_csv(p, dtype={"route_id": str})
    return {(row.route_id, row.band): (float(row.late_pct), int(row.n)) for row in r.itertuples(index=False)}


@lru_cache(maxsize=1)
def _trip_route():
    from .journey import load_timetable_data
    trips = load_timetable_data()[1]
    return dict(zip(trips.trip_id.astype(str), trips.route_id.astype(str)))


def _km(lat1, lon1, lat2, lon2):
    dy = (lat2 - lat1) * 110.54
    dx = (lon2 - lon1) * 111.32 * math.cos(math.radians(lat1))
    return math.hypot(dx, dy)


def _events_on(travel_date):
    e = delay.events()
    return e[e.date == travel_date.isoformat()] if len(e) else e


def _event_active(evs, lat, lon, hour_f):
    """An event within VENUE_KM whose window (2 h before to 2 h after) covers this time, or None."""
    for r in evs.itertuples(index=False):
        try:
            sh, sm = (int(x) for x in str(r.start).split(":")[:2])
        except ValueError:
            continue
        start = sh + sm / 60
        dur = float(getattr(r, "duration_h", 2) or 2)
        if start - 2 <= hour_f <= start + dur + 2 and _km(lat, lon, float(r.lat), float(r.lon)) <= VENUE_KM:
            name = r.venue if not isinstance(getattr(r, "opponent", None), str) else f"{r.venue} ({r.opponent})"
            return name
    return None


def _legs(j):
    if j.get("journey_type") == "transfer":
        return j.get("legs", [])
    return [{"route": j.get("route"), "trip_id": j.get("trip_id"), "stops": j.get("stops", [])}]


def journey_insight(j, travel_date: date):
    weekend = travel_date.weekday() >= 5
    idx = _segment_index()
    evs = _events_on(travel_date)
    rel = _reliability()
    trip_route = _trip_route()

    stretches, tod_last, event_s, events_hit = [], 0.0, 0.0, set()
    timed = []  # (path, seconds since service-day start) of every stretch ridden, for road works
    n_pairs = n_hit = observations = 0
    leg_late, on_time_probs, last_late = [], [], None
    for leg in _legs(j):
        stops = leg.get("stops") or []
        leg_tod = None
        for a, b in zip(stops, stops[1:]):
            n_pairs += 1
            t = _secs(a.get("departure_time") or a.get("arrival_time"))
            hour = (t // 3600) % 24
            key = (a["stop_id"], b["stop_id"], int(weekend), hour)
            path = [[a["stop_lat"], a["stop_lon"]], [b["stop_lat"], b["stop_lon"]]]
            name = f"{a['stop_name']} → {b['stop_name']}"
            timed.append((path, t, name))
            if key not in idx.index:
                stretches.append({"path": path, "minutes": None, "band": None, "added_s": None, "name": name,
                                  "from_stop_id": a["stop_id"], "to_stop_id": b["stop_id"]})
                continue
            r = idx.loc[key]
            n_hit += 1
            observations += int(r.n)
            late = max(0.0, float(r.late_med_s) / 60)
            last_late = late
            leg_tod = (float(r.late_med_s) - float(r.late_allday_s)) / 60
            ev = _event_active(evs, b["stop_lat"], b["stop_lon"], t / 3600 % 24) if len(evs) else None
            if ev and not pd.isna(r.event_effect_s):
                event_s += float(r.event_effect_s)
                events_hit.add(ev)
            stretches.append({"path": path, "minutes": round(late, 1), "band": delay.band(late),
                              "added_s": round(float(r.added_med_s)), "name": name,
                              "from_stop_id": a["stop_id"], "to_stop_id": b["stop_id"]})
        if leg_tod is not None:
            tod_last += leg_tod
        leg_late.append(last_late)

        # this leg's line: share of its buses >5 min late at this time of day
        if stops:
            hour0 = (_secs(stops[0].get("departure_time") or stops[0]["arrival_time"]) // 3600) % 24
            rid = trip_route.get(str(leg.get("trip_id")))
            got = rel.get((rid, _band_name(hour0, weekend))) if rid else None
            if got:
                on_time_probs.append(1 - got[0] / 100)

    # Rain: per-stretch estimates are noisy (summed over a route they swing by +-1 min), so use the network-wide
    # measured effect (moderate rain vs dry, per stretch) times the stretches ridden.
    dry = delay._effect("rain", "rain", "dry")
    wet = delay._effect("rain", "rain", "moderate (0.5-2)")
    rain_s = (wet - dry) * n_pairs if dry is not None and wet is not None else 0.0

    coverage = n_hit / n_pairs if n_pairs else 0.0
    risk_pct = round(100 * (1 - math.prod(on_time_probs))) if on_time_probs else None
    worst = max((s for s in stretches if s["added_s"] is not None), key=lambda s: s["added_s"], default=None)
    if worst is not None and worst["added_s"] < 30:
        worst = None  # nothing worth calling out

    works_s, works_on_route = _roadworks_along(timed, travel_date, weekend)
    typical = leg_late[-1] if leg_late and leg_late[-1] is not None else None
    hour_dep = (_secs(j["departure_time"]) // 3600) % 24
    factors = [
        {"key": "time_of_day", "label": "Time of day", "minutes": round(tod_last, 1),
         "description": (f"Buses on this route run {abs(tod_last):.0f} min {'later' if tod_last >= 0 else 'earlier'} "
                         f"around {hour_dep:02d}:00 than on average") if abs(tod_last) >= 0.5
                        else f"Around {hour_dep:02d}:00 is a typical time for this route"},
        {"key": "weather", "label": "Weather", "minutes": round(rain_s / 60, 1),
         "description": f"If it rains: {rain_s / 60:+.1f} min along this route. Rain made no real difference in our data"},
        {"key": "events", "label": "Events", "minutes": round(event_s / 60, 1),
         "description": (f"{', '.join(sorted(events_hit))} nearby: {event_s / 60:+.1f} min" if events_hit
                         else "No football or concerts near this route at that time")},
        {"key": "roadworks", "label": "Road works", "minutes": round(works_s / 60, 1),
         "description": _works_sentence(works_on_route, works_s)},
    ]

    # Where and why only: how late is shown separately (the model's prediction when there is one), and
    # repeating a historical number here would contradict it.
    bits = []
    if worst:
        bits.append(f"Most time is lost {worst['name']} (+{worst['added_s'] / 60:.0f} min)")
    if abs(tod_last) >= 1:
        bits.append(f"{abs(tod_last):.0f} min {'slower' if tod_last > 0 else 'quicker'} than usual at this hour")
    if events_hit:
        bits.append(f"event at {', '.join(sorted(events_hit))}")
    if works_on_route and works_s >= 15:
        top = works_on_route[0]
        bits.append(f"{top['traffic_management'].lower()} on {top['street']}"
                    + (f" (+{len(works_on_route) - 1} more works)" if len(works_on_route) > 1 else ""))
    if bits:
        explanation = "; ".join(bits) + "."
        explanation = explanation[0].upper() + explanation[1:]
    elif coverage >= 0.4:
        explanation = "A steady route: no stretch or time of day stands out in past data."
    else:
        explanation = "Not enough past data on this route to explain its delays."

    confidence = "high" if coverage >= 0.7 and observations >= 500 else "medium" if coverage >= 0.4 else "low"
    m = delay.meta()
    return {
        "stretches": stretches,
        "typical_late_min": None if typical is None else round(typical, 1),
        "risk_pct": risk_pct,
        "factors": factors,
        "worst": worst,
        "roadworks": works_on_route,
        "explanation": explanation,
        "coverage": round(coverage, 2),
        "observations": observations,
        "confidence": confidence,
        "data_days": m["days"],
    }


def _seg_dist_m(px, py, ax, ay, bx, by):
    """Distance (m) from points (px, py) to segment a-b, all in local metres (numpy arrays for p)."""
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    u = np.clip(((px - ax) * dx + (py - ay) * dy) / L2, 0, 1) if L2 > 0 else np.zeros_like(px)
    return np.hypot(px - (ax + u * dx), py - (ay + u * dy))


def _roadworks_along(timed, travel_date, weekend):
    """Road works within ROADWORKS_RADIUS_M of the stretches ridden, active when the bus is there.
    Per stretch: one job adds its own effect (measured for that permit, else typical for its traffic-management
    type); several at once add at least the analysis's "concurrent works" figure. Scaled to the hour of travel.
    Returns (total extra seconds, [works sorted by effect])."""
    w = delay.roadworks()
    if w is None or not timed:
        return 0.0, []
    day0 = pd.Timestamp(travel_date).tz_localize(delay.LONDON)
    t_mid = day0 + pd.Timedelta(seconds=float(np.median([t for _, t, _ in timed])))
    act = delay.roadworks_active(t_mid.tz_convert("UTC"))
    if act is None or act.empty:
        return 0.0, []
    lat0 = timed[0][0][0][0]
    kx, ky = 111_320.0 * math.cos(math.radians(lat0)), 110_540.0
    # cheap box filter first
    lats = [p for path, _, _ in timed for p in (path[0][0], path[1][0])]
    lons = [p for path, _, _ in timed for p in (path[0][1], path[1][1])]
    pad = 0.002
    act = act[act.lat.between(min(lats) - pad, max(lats) + pad) & act.lon.between(min(lons) - pad, max(lons) + pad)]
    if act.empty:
        return 0.0, []
    wx, wy = act.lon.to_numpy() * kx, act.lat.to_numpy() * ky
    total, hit = 0.0, {}
    for path, t, name in timed:
        (alat, alon), (blat, blon) = path
        near = _seg_dist_m(wx, wy, alon * kx, alat * ky, blon * kx, blat * ky) <= delay.ROADWORKS_RADIUS_M
        if not near.any():
            continue
        hour = int(t // 3600) % 24
        scale = delay.roadworks_hour_scale(hour, weekend)
        here = act[near]
        own = here.effect_base_s.to_numpy()
        extra = max(own.max(), delay.roadworks_concurrent_s(len(here)) if len(here) > 1 else 0.0) * scale
        total += extra
        for r in here.itertuples(index=False):
            item = hit.setdefault(r.permit_reference_number, delay.roadwork_out(r, scale))
            item.setdefault("stretches", []).append(name)
    works = sorted(hit.values(), key=lambda x: -x["effect_s"])
    return total, works


def _works_sentence(works, total_s):
    if not works:
        return "No road works on this route at that time (Street Manager permits)"
    top = works[0]
    kind = "measured there" if top["measured"] else f"typical for {top['traffic_management'].lower()}"
    if len(works) == 1:
        return (f"{top['traffic_management']} on {top['street']}: about +{total_s:.0f} s along this route "
                f"({kind}: +{top['effect_s']:.0f} s per stretch)")
    return (f"{len(works)} works along this route, about +{total_s:.0f} s in total. Biggest: "
            f"{top['traffic_management'].lower()} on {top['street']} (+{top['effect_s']:.0f} s per stretch, {kind})")


def annotate_route_insights(journeys, travel_date):
    """Adds journey["insight"] in place. Never fails the request: on any error the journey just has none."""
    try:
        delay.segments()  # raises DelayDataMissing early if the export isn't there
    except Exception as e:
        for j in journeys:
            j["insight"] = None
        print(f"[route_insight] unavailable: {e}")
        return
    for j in journeys:
        try:
            j["insight"] = journey_insight(j, travel_date)
        except Exception as e:  # one odd journey must not break the list
            print(f"[route_insight] {e!r}")
            j["insight"] = None
