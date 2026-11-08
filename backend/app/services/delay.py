"""Delay data for the API, read from the tables delay_engine/export_for_api.py writes to backend/data/delay/.

All numbers are historical: what buses typically did at that stretch / hour / day type over the archive window
(see meta.json for the dates). Nothing here is live yet.

Delay map semantics (one stretch = stop A -> next stop B):
  base         typical lateness at B over the whole day (same day type), in minutes behind timetable
  time_of_day  how much later or earlier than that buses are at the selected hour
  weather      extra delay gained on the stretch when it rains, vs dry (measured; mostly ~0)
  events       extra delay gained on the stretch when an event is on nearby (only near venues)
"overall" = base + the enabled factors. Colouring by one factor shows just that factor.

The map draws hex_m-wide hexagons: each is the bus-pass-weighted mean over the stretches ending inside it.
(Stop-to-stop lines cut through buildings, since we have no road shapes, and left gaps.)
"""
import json
import math
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parents[2] / "data" / "delay"
LONDON = ZoneInfo("Europe/London")
ALL_KEYS = ("weather", "time_of_day", "events")
FACTOR_LABELS = {"weather": "Weather", "time_of_day": "Time of day", "events": "Events"}
LEGEND = [
    {"band": "on_time", "label": "On time"},
    {"band": "minor", "label": "+2–5"},
    {"band": "moderate", "label": "+5–8"},
    {"band": "severe", "label": "8+ min"},
]
MAP_HOURS = range(6, 24)  # hours shown in the hour-of-day chart

# Hexagon grid for the delay map. Flat-earth metres around Manchester are accurate to well under 1% over the
# region. Pointy-top hexagons, hex_m metres across (flat side to flat side). The frontend picks a size from the
# zoom level; only these sizes are allowed, so the per-size cache below stays small.
HEX_SIZES = (150, 250, 400, 700, 1200, 2000)
HEX_M = 400  # default
_LAT0 = 53.48
_KX, _KY = 111_320.0 * math.cos(math.radians(_LAT0)), 110_540.0
EVENT_PRE_H, EVENT_POST_H = 2, 2  # same window build_analysis.py used to measure event effects


class DelayDataMissing(RuntimeError):
    pass


def _path(name):
    p = DATA / name
    if not p.exists():
        raise DelayDataMissing(
            f"{p} not found. Run delay_engine/export_for_api.py (see its docstring) to create it.")
    return p


@lru_cache(maxsize=1)
def meta():
    return json.loads(_path("meta.json").read_text())


@lru_cache(maxsize=1)
def segments():
    return pd.read_parquet(_path("segments.parquet"))


def _radius(hex_m):
    return hex_m / math.sqrt(3)  # centre-to-corner


def _hex_of(lat, lon, hex_m):
    """Axial (q, r) of the hexagon containing each point (numpy arrays in, int arrays out)."""
    R = _radius(hex_m)
    x, y = np.asarray(lon) * _KX, np.asarray(lat) * _KY
    qf = (math.sqrt(3) / 3 * x - y / 3) / R
    rf = (2 / 3 * y) / R
    sf = -qf - rf
    q, r, s_ = np.round(qf), np.round(rf), np.round(sf)
    dq, dr, ds = np.abs(q - qf), np.abs(r - rf), np.abs(s_ - sf)
    fix_q = (dq > dr) & (dq > ds)
    fix_r = ~fix_q & (dr > ds)
    q = np.where(fix_q, -r - s_, q)
    r = np.where(fix_r, -q - s_, r)
    return q.astype(int), r.astype(int)


def _hex_ring(q, r, hex_m):
    """Corners of hexagon (q, r) as [[lat, lon], ...]."""
    R = _radius(hex_m)
    cx, cy = R * math.sqrt(3) * (q + r / 2), R * 1.5 * r
    out = []
    for i in range(6):
        a = math.radians(60 * i - 30)
        out.append([round((cy + R * math.sin(a)) / _KY, 5), round((cx + R * math.cos(a)) / _KX, 5)])
    return out


@lru_cache(maxsize=len(HEX_SIZES))
def segments_hexed(hex_m):
    """segments() plus the hexagon of each stretch's end stop (lateness is measured on arrival there)."""
    s = segments().copy()
    s["hq"], s["hr"] = _hex_of(s.to_lat.to_numpy(), s.to_lon.to_numpy(), hex_m)
    return s


@lru_cache(maxsize=1)
def network():
    return pd.read_parquet(_path("network_hourly.parquet"))


@lru_cache(maxsize=1)
def events():
    p = DATA / "events.csv"
    if not p.exists():
        return pd.DataFrame(columns=["date", "start", "venue", "lat", "lon", "type", "opponent"])
    return pd.read_csv(p, dtype={"date": str, "start": str})


def band(minutes):
    if minutes < 2:
        return "on_time"
    if minutes < 5:
        return "minor"
    if minutes < 8:
        return "moderate"
    return "severe"


def now():
    return datetime.now(LONDON)


def is_weekend(day_type):
    """day_type 'weekday' / 'weekend', or None for today's."""
    if day_type is None:
        return now().weekday() >= 5
    return day_type == "weekend"


def as_of():
    """End of the data window (the API serves historical patterns, not live data)."""
    return datetime.fromisoformat(meta()["data_to"]).replace(hour=23, minute=59, tzinfo=LONDON)


def _effect(table, key, value):
    for row in meta()["effects"].get(table, []):
        if str(row.get(key)) == value:
            return row.get("mean_excess_s")
    return None


def _descriptions(hour, weekend):
    m = meta()
    window = f"{m['days']} days of buses"

    dry, wet = _effect("rain", "rain", "dry"), _effect("rain", "rain", "moderate (0.5-2)")
    weather = (f"Rain adds {wet - dry:+.1f} s per stretch vs dry ({window}): no real effect"
               if dry is not None and wet is not None else "Effect of rain on each stretch")

    net = network()
    row = net[(net.is_weekend == int(weekend)) & (net.hour == hour)]
    day = "weekends" if weekend else "weekdays"
    allday = net[net.is_weekend == int(weekend)]
    if len(row):
        r = row.iloc[0]
        avg_on_time = (allday.pct_on_time * allday.n).sum() / allday.n.sum()
        time_of_day = f"{hour:02d}:00 on {day}: {r.pct_on_time:.0f}% of buses on time (all-day {avg_on_time:.0f}%)"
    else:
        time_of_day = f"No buses observed at {hour:02d}:00 on {day}"

    none, pre = _effect("events_near_venue", "event_state", "no event"), _effect("events_near_venue", "event_state", "pre")
    ev = (f"Within {m['venue_km']} km of a venue, the 2 h before an event add {pre - none:+.0f} s per stretch"
          if none is not None and pre is not None else "Effect of events near each stretch")
    return {"weather": weather, "time_of_day": time_of_day, "events": ev}


def _events_today(hour):
    """Today's events whose influence window (2 h before start to 2 h after the end) covers the selected hour."""
    today = now().strftime("%Y-%m-%d")
    e = events()
    e = e[e.date == today]
    out = []
    for i, r in enumerate(e.itertuples(index=False)):
        try:
            sh, sm = (int(x) for x in str(r.start).split(":")[:2])
            dur = float(getattr(r, "duration_h", 2) or 2)
        except ValueError:
            continue
        start = sh + sm / 60
        # the selected hour covers [hour, hour + 1)
        if not (hour + 1 > start - EVENT_PRE_H and hour < start + dur + EVENT_POST_H):
            continue
        name = r.venue if not isinstance(getattr(r, "opponent", None), str) else f"{r.venue}: {r.opponent}"
        out.append({"id": f"ev-{today}-{i}", "name": name, "kind": str(r.type), "time_label": str(r.start),
                    "lat": float(r.lat), "lon": float(r.lon)})
    return out


def get_delay_map(hour, colour_by, enabled, day_type=None, limit=1500, min_n=20, bbox=None, hex_min_n=30,
                  hex_m=HEX_M):
    if hex_m not in HEX_SIZES:
        raise ValueError(f"hex_m must be one of {HEX_SIZES}")
    weekend = is_weekend(day_type)
    s = segments_hexed(hex_m)
    s = s[(s.is_weekend == int(weekend)) & (s.hour == hour) & (s.n >= min_n)]
    if bbox is not None:
        lat0, lon0, lat1, lon1 = bbox
        inside = lambda lat, lon: lat.between(lat0, lat1) & lon.between(lon0, lon1)
        s = s[inside(s.from_lat, s.from_lon) | inside(s.to_lat, s.to_lon)]

    parts = pd.DataFrame({
        "weather": s.rain_effect_s.fillna(0) / 60,
        "time_of_day": (s.late_med_s - s.late_allday_s) / 60,
        "events": s.event_effect_s.fillna(0) / 60,
    }, index=s.index)
    keys = [k for k in ALL_KEYS if k in enabled and (colour_by == "overall" or k == colour_by)]
    total = parts[keys].sum(axis=1) if keys else pd.Series(0.0, index=s.index)
    if colour_by == "overall":
        total = total + s.late_allday_s / 60
    s = s.assign(delay=total)

    # ---- hexagons: bus-pass-weighted mean over the stretches ending inside each one
    w = s.n.astype(float)
    hx = pd.DataFrame({"hq": s.hq, "hr": s.hr, "w": w, "wd": w * s.delay,
                       **{f"w_{k}": w * parts[k] for k in ALL_KEYS}})
    g = hx.groupby(["hq", "hr"], sort=False).sum()
    g = g[g.w >= hex_min_n]
    # per hexagon: its worst stretch (for the tooltip) and the lines running through it
    worst_in = {(r.hq, r.hr): r for r in s.sort_values("delay", ascending=False)
                .drop_duplicates(["hq", "hr"]).itertuples(index=False)}
    lines_in = {}
    for key, ln in zip(zip(s.hq, s.hr), s.lines):
        lines_in.setdefault(key, set()).update(ln.split(","))
    hexes = []
    for row in g.reset_index().itertuples(index=False):
        q, r = int(row.hq), int(row.hr)
        d = max(0.0, row.wd / row.w)
        ws = worst_in[(q, r)]
        hexes.append({
            "id": f"{q},{r}",
            "path": _hex_ring(q, r, hex_m),
            "delay_minutes": round(d, 1),
            "band": band(d),
            "breakdown": {k: round(float(getattr(row, f"w_{k}") / row.w), 2) for k in ALL_KEYS},
            "observations": int(row.w),
            "worst_stretch": f"{ws.from_name} → {ws.to_name}",
            "worst_stretch_minutes": round(max(0.0, float(ws.delay)), 1),
            "lines": ",".join(sorted(lines_in[(q, r)], key=lambda x: (len(x), x))),
        })

    # ---- stretches: the worst `limit`, for the "worst" list
    top = s.assign(delay=s.delay.clip(lower=0)).sort_values("delay", ascending=False).head(limit)
    out_segments = []
    for r, p in zip(top.itertuples(index=False), parts.loc[top.index].itertuples(index=False)):
        out_segments.append({
            "id": f"{r.from_stop_id}>{r.to_stop_id}",
            "name": f"{r.from_name} → {r.to_name}",
            "from_stop_id": r.from_stop_id,
            "to_stop_id": r.to_stop_id,
            "path": [[r.from_lat, r.from_lon], [r.to_lat, r.to_lon]],
            "delay_minutes": round(float(r.delay), 1),
            "band": band(r.delay),
            "breakdown": {k: round(float(getattr(p, k)), 2) for k in ALL_KEYS},
            "lines": r.lines,
            "observations": int(r.n),
        })

    descriptions = _descriptions(hour, weekend)
    # bus-pass-weighted mean over every stretch at this hour (not just the ones listed)
    factors = [{
        "key": k,
        "label": FACTOR_LABELS[k],
        "minutes": round(float((parts[k] * w).sum() / w.sum()), 1) if len(s) else 0.0,
        "description": descriptions[k],
    } for k in ALL_KEYS]

    net = network()
    net = net[(net.is_weekend == int(weekend)) & net.hour.isin(MAP_HOURS)]
    hourly = [{"hour": int(r.hour), "avg_delay_minutes": round(float(r.avg_delay_min), 1),
               "band": band(r.avg_delay_min)} for r in net.itertuples(index=False)]

    m = meta()
    return {
        "as_of": as_of(),
        "hour": hour,
        "colour_by": colour_by,
        "day_type": "weekend" if weekend else "weekday",
        "data_from": m["data_from"],
        "data_to": m["data_to"],
        "data_days": m["days"],
        "hex_m": hex_m,
        "conditions": {
            "weather": {"summary": "Rain: no measurable effect", "temp_c": None, "wind_kmh": None},
            # only on the day type of today, otherwise "tonight's concert" would sit on a weekday map
            "events": _events_today(hour) if weekend == is_weekend(None) else [],
        },
        "factors": factors,
        "hourly": hourly,
        "hexes": hexes,
        "segments": out_segments,
        "worst": [{"segment_id": x["id"], "name": x["name"], "delay_minutes": x["delay_minutes"]}
                  for x in out_segments[:5]],
        "legend": LEGEND,
    }


def get_network_summary(hour, day_type=None):
    weekend = is_weekend(day_type)
    net = network()
    row = net[(net.is_weekend == int(weekend)) & (net.hour == hour)]
    if row.empty:
        return {"as_of": as_of(), "pct_on_time": 0, "delayed_over_5min": 0, "avg_delay_minutes": 0.0,
                "day_type": "weekend" if weekend else "weekday", "buses": 0}
    r = row.iloc[0]
    return {
        "as_of": as_of(),
        "pct_on_time": int(round(r.pct_on_time)),
        "delayed_over_5min": int(round(r.late_buses)),   # buses >5 min late during that hour, on a typical day
        "avg_delay_minutes": round(float(r.avg_delay_min), 1),
        "day_type": "weekend" if weekend else "weekday",
        "buses": int(round(r.buses)),
    }


def get_typical_delay(from_id, to_id, hour, day_type=None):
    """Typical lateness at to_id for buses coming from from_id (adjacent stops), or None if not enough data."""
    weekend = is_weekend(day_type)
    s = segments()
    r = s[(s.from_stop_id == from_id) & (s.to_stop_id == to_id) & (s.is_weekend == int(weekend)) & (s.hour == hour)]
    if r.empty:
        return None
    return {"from_id": from_id, "to_id": to_id, "hour": hour,
            "typical_delay_minutes": round(float(r.iloc[0].late_med_s) / 60, 1)}


def get_late_buses():
    """Latest output of current_delays.py (a past moment replayed from the archive, see as_of_utc)."""
    return json.loads(_path("current_delays.json").read_text())


def get_status():
    m = meta()
    return {
        "live": False,
        "region": "Greater Manchester",
        "updated_at": as_of(),
        "signals": [f"BODS archive {m['data_from']} to {m['data_to']}", "GTFS timetable", "events",
                    "road works", "weather"],
    }
