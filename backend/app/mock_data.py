# Placeholder data in the final response shapes, so the frontend can be built
# against it now. Stops are approximate; weather, events, delays and risk
# numbers are invented. Replace the functions here with real database/model
# calls later and keep the return shapes the same.
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    LONDON = ZoneInfo("Europe/London")
except Exception:
    LONDON = timezone.utc


def now() -> datetime:
    return datetime.now(LONDON)


STOPS = {
    "uom": {"id": "uom", "name": "University of Manchester", "lat": 53.4668, "lon": -2.2339},
    "oxford-road-station": {"id": "oxford-road-station", "name": "Oxford Road Station", "lat": 53.4741, "lon": -2.2425},
    "deansgate": {"id": "deansgate", "name": "Deansgate", "lat": 53.4743, "lon": -2.2500},
    "peter-st": {"id": "peter-st", "name": "Peter St", "lat": 53.4780, "lon": -2.2465},
    "piccadilly-gardens": {"id": "piccadilly-gardens", "name": "Piccadilly Gardens", "lat": 53.4808, "lon": -2.2374},
    "etihad-campus": {"id": "etihad-campus", "name": "Etihad Campus", "lat": 53.4831, "lon": -2.2004},
    "salford-quays": {"id": "salford-quays", "name": "Salford Quays", "lat": 53.4720, "lon": -2.2980},
    "wilmslow-rd": {"id": "wilmslow-rd", "name": "Wilmslow Rd", "lat": 53.4545, "lon": -2.2205},
}

# w = weather, t = time of day, e = events: minutes of delay at the baseline hour
SEGMENTS = [
    {"id": "uom-oxford-road-station", "name": "Oxford Rd (University)", "from": "uom", "to": "oxford-road-station", "w": 0, "t": 0, "e": 0},
    {"id": "oxford-road-station-deansgate", "name": "Oxford Rd Stn / Deansgate", "from": "oxford-road-station", "to": "deansgate", "w": 0, "t": 0, "e": 0},
    {"id": "deansgate-peter-st", "name": "Deansgate / Peter St", "from": "deansgate", "to": "peter-st", "w": 0, "t": 0.5, "e": 0},
    {"id": "peter-st-piccadilly-gardens", "name": "Peter St / Piccadilly", "from": "peter-st", "to": "piccadilly-gardens", "w": 0.5, "t": 1, "e": 0.5},
    {"id": "oxford-rd-piccadilly", "name": "Oxford Rd → Piccadilly", "from": "uom", "to": "piccadilly-gardens", "w": 3, "t": 2, "e": 4},
    {"id": "oxford-road-station-piccadilly-gardens", "name": "Oxford Rd Stn → Piccadilly", "from": "oxford-road-station", "to": "piccadilly-gardens", "w": 2, "t": 1, "e": 4},
    {"id": "piccadilly-gardens-etihad-campus", "name": "Etihad Campus approach", "from": "piccadilly-gardens", "to": "etihad-campus", "w": 1, "t": 2, "e": 5},
    {"id": "salford-quays-deansgate", "name": "Salford Quays / Deansgate", "from": "salford-quays", "to": "deansgate", "w": 0, "t": 0, "e": 0},
    {"id": "piccadilly-gardens-wilmslow-rd", "name": "Wilmslow Rd", "from": "piccadilly-gardens", "to": "wilmslow-rd", "w": 0, "t": 0, "e": 0},
]

ALL_KEYS = ("weather", "time_of_day", "events")
KEY_FIELD = {"weather": "w", "time_of_day": "t", "events": "e"}
FACTOR_LABELS = {"weather": "Weather", "time_of_day": "Time of day", "events": "Events"}

# Average delay across the network by hour; hour 14 is the baseline (scale 1.0)
HOURLY_AVG = {7: 1.5, 8: 1.8, 9: 3.0, 10: 5.5, 11: 3.5, 12: 1.5, 13: 1.5, 14: 3.0, 15: 3.5, 16: 6.0, 17: 6.5, 18: 4.0}

CONDITIONS = {
    "weather": {"summary": "Light rain", "temp_c": 8.0, "wind_kmh": 12.0},
    "events": [
        {"id": "xmas", "name": "Christmas Markets", "kind": "market", "time_label": "", "lat": 53.4795, "lon": -2.2440},
        {"id": "city-arsenal", "name": "City v Arsenal", "kind": "football", "time_label": "15:00", "lat": 53.4831, "lon": -2.2004},
    ],
}

LEGEND = [
    {"band": "on_time", "label": "On time"},
    {"band": "minor", "label": "+2–5"},
    {"band": "moderate", "label": "+5–8"},
    {"band": "severe", "label": "8+ min"},
]


def hour_scale(hour: int) -> float:
    return HOURLY_AVG.get(hour, 1.0) / 3.0


def band(minutes: float) -> str:
    if minutes < 2:
        return "on_time"
    if minutes < 5:
        return "minor"
    if minutes < 8:
        return "moderate"
    return "severe"


def time_description(hour: int) -> str:
    if 7 <= hour <= 9:
        return "Morning rush hour"
    if hour in (10, 11):
        return "Late morning"
    if hour in (12, 13):
        return "Lunchtime"
    if hour == 14:
        return "Mid-afternoon, school-run starts"
    if hour in (15, 16):
        return "School run and early rush"
    if hour in (17, 18):
        return "Evening rush hour"
    return "Quiet hours"


def events_description() -> str:
    return " · ".join(
        f'{e["name"]} {e["time_label"]}'.strip() for e in CONDITIONS["events"]
    )


def weather_description() -> str:
    w = CONDITIONS["weather"]
    return f'{w["summary"]} · {w["wind_kmh"]:.0f} km/h wind'


# ---------- simple lookups ----------

def get_status() -> dict:
    return {
        "live": True,
        "region": "Greater Manchester",
        "updated_at": now(),
        "signals": ["live bus positions", "weather", "local events"],
    }


def get_places(q: str | None) -> list[dict]:
    stops = list(STOPS.values())
    if q:
        stops = [s for s in stops if q.lower() in s["name"].lower()]
    return stops


def get_network_summary(hour: int) -> dict:
    s = hour_scale(hour)
    return {
        "as_of": now(),
        "pct_on_time": max(20, round(62 - (s - 1) * 25)),
        "delayed_over_5min": round(14 * s),
        "avg_delay_minutes": round(3 * s, 1),
    }


def get_vehicles(hour: int) -> list[dict]:
    s = hour_scale(hour)
    raw = [
        ("v1", "18", 53.4700, -2.2390, 3),
        ("v2", "216", 53.4820, -2.2150, 5),
        ("v3", "86", 53.4780, -2.2330, 7),
        ("v4", "42", 53.4690, -2.2420, 2),
        ("v5", "50", 53.4590, -2.2250, 0),
    ]
    out = []
    for vid, line, lat, lon, base in raw:
        d = round(base * s, 1)
        out.append({"id": vid, "line": line, "lat": lat, "lon": lon, "delay_minutes": d, "band": band(d)})
    return out


def get_typical_delay(from_id: str, to_id: str, hour: int) -> dict:
    base = 2 + (len(from_id) + len(to_id)) % 5
    return {"from_id": from_id, "to_id": to_id, "hour": hour, "typical_delay_minutes": round(base * hour_scale(hour), 1)}


# ---------- delay map ----------

def _segment_out(seg: dict, hour: int, keys) -> dict:
    s = hour_scale(hour)
    breakdown = {k: round(seg[KEY_FIELD[k]] * s, 1) for k in keys}
    delay = round(sum(breakdown.values()), 1)
    a, b = STOPS[seg["from"]], STOPS[seg["to"]]
    return {
        "id": seg["id"],
        "name": seg["name"],
        "from_stop_id": seg["from"],
        "to_stop_id": seg["to"],
        "path": [[a["lat"], a["lon"]], [b["lat"], b["lon"]]],
        "delay_minutes": delay,
        "band": band(delay),
        "breakdown": breakdown,
    }


def get_delay_map(hour: int, colour_by: str, enabled: list[str]) -> dict:
    keys = [k for k in ALL_KEYS if k in enabled and (colour_by == "overall" or k == colour_by)]
    segments = [_segment_out(s, hour, keys) for s in SEGMENTS]
    worst = sorted(segments, key=lambda s: -s["delay_minutes"])[:3]
    scale = hour_scale(hour)
    descriptions = {
        "weather": weather_description(),
        "time_of_day": time_description(hour),
        "events": events_description(),
    }
    factors = [
        {
            "key": k,
            "label": FACTOR_LABELS[k],
            "minutes": max(round(seg[KEY_FIELD[k]] * scale, 1) for seg in SEGMENTS),
            "description": descriptions[k],
        }
        for k in ALL_KEYS
    ]
    hourly = [{"hour": h, "avg_delay_minutes": v, "band": band(v)} for h, v in HOURLY_AVG.items()]
    return {
        "as_of": now(),
        "hour": hour,
        "colour_by": colour_by,
        "conditions": CONDITIONS,
        "factors": factors,
        "hourly": hourly,
        "segments": segments,
        "worst": [
            {"segment_id": w["id"], "name": w["name"], "delay_minutes": w["delay_minutes"]} for w in worst
        ],
        "legend": LEGEND,
    }


# ---------- routes ----------

ROUTE_TEMPLATES = [
    {
        "id": "reliable", "label": "Most reliable", "timetable": 29, "risk": 12, "lines": ["18"], "walk": 3,
        "explanation": "Avoids Oxford Rd rain slowdown and the Piccadilly stretch hit by Christmas Markets crowds.",
        "factors": {
            "weather": (1, "Sheltered side streets, little rain impact."),
            "time_of_day": (1, "Quieter streets during the school run."),
            "events": (0, "Steers clear of the Piccadilly Gardens crowds."),
        },
    },
    {
        "id": "fastest", "label": "Fastest on paper", "timetable": 22, "risk": 68, "lines": ["86"], "walk": 4,
        "explanation": "Oxford Rd corridor: light rain and school-run traffic push this well past the timetable.",
        "factors": {
            "weather": (3, "Light rain slows boarding and traffic on Oxford Rd."),
            "time_of_day": (2, "School-run build-up from ~15:00 along the Oxford Rd corridor."),
            "events": (4, "Christmas Markets crowds around Piccadilly Gardens and City v Arsenal traffic."),
        },
    },
    {
        "id": "balanced", "label": "Balanced", "timetable": 26, "risk": 41, "lines": ["42", "216"], "walk": 2,
        "explanation": "Change at Oxford Road Station; second bus affected by match-day build-up near Etihad.",
        "factors": {
            "weather": (2, "Rain affects the second leg."),
            "time_of_day": (1, "Moderate traffic on the connecting road."),
            "events": (4, "Match-day build-up near Etihad."),
        },
    },
]


def _via(route_id: str, origin: str, dest: str) -> list[str]:
    if origin == "uom" and dest == "piccadilly-gardens":
        return {"reliable": ["oxford-road-station", "deansgate", "peter-st"], "fastest": [], "balanced": ["oxford-road-station"]}[route_id]
    cands = [s for s in ("oxford-road-station", "deansgate", "peter-st") if s not in (origin, dest)]
    return {"reliable": cands[:2], "fastest": [], "balanced": cands[:1]}[route_id]


def _pair_segment(a: str, b: str, hour: int) -> dict:
    for seg in SEGMENTS:
        if {seg["from"], seg["to"]} == {a, b}:
            return _segment_out(seg, hour, ALL_KEYS)
    pa, pb = STOPS[a], STOPS[b]
    delay = round(1.5 * hour_scale(hour), 1)
    return {
        "id": f"{a}-{b}",
        "name": f'{pa["name"]} → {pb["name"]}',
        "from_stop_id": a,
        "to_stop_id": b,
        "path": [[pa["lat"], pa["lon"]], [pb["lat"], pb["lon"]]],
        "delay_minutes": delay,
        "band": band(delay),
        "breakdown": {},
    }


def _segment_delay(seg_id: str, hour: int) -> int:
    seg = next(s for s in SEGMENTS if s["id"] == seg_id)
    return max(1, round(_segment_out(seg, hour, ALL_KEYS)["delay_minutes"]))


def _mid(a: str, b: str) -> tuple[float, float]:
    return (STOPS[a]["lat"] + STOPS[b]["lat"]) / 2, (STOPS[a]["lon"] + STOPS[b]["lon"]) / 2


def _callouts(route_id: str, origin: str, dest: str, hour: int) -> list[dict]:
    if not (origin == "uom" and dest == "piccadilly-gardens"):
        return []
    ox = _segment_delay("oxford-rd-piccadilly", hour)
    ox_lat, ox_lon = _mid("uom", "piccadilly-gardens")
    if route_id == "reliable":
        ps = _segment_delay("deansgate-peter-st", hour)
        return [
            {"label": f"Peter St +{ps} min", "detail": "Reliable corridor", "lat": STOPS["peter-st"]["lat"], "lon": STOPS["peter-st"]["lon"], "tone": "good"},
            {"label": f"Oxford Rd → Piccadilly +{ox} min", "detail": "Avoided: rain + Christmas Markets", "lat": ox_lat, "lon": ox_lon, "tone": "bad"},
        ]
    if route_id == "fastest":
        return [{"label": f"Oxford Rd → Piccadilly +{ox} min", "detail": "Rain, school run and Christmas Markets", "lat": ox_lat, "lon": ox_lon, "tone": "bad"}]
    d = _segment_delay("oxford-road-station-piccadilly-gardens", hour)
    lat, lon = _mid("oxford-road-station", "piccadilly-gardens")
    return [{"label": f"Oxford Rd Stn → Piccadilly +{d} min", "detail": "Match-day build-up", "lat": lat, "lon": lon, "tone": "bad"}]


def get_stop(stop_id: str) -> dict | None:
    return STOPS.get(stop_id)


def get_route_response(origin_id: str, destination_id: str, mode: str, when: datetime | None) -> dict:
    if when is None:
        when = now()
    elif when.tzinfo is None:
        when = when.replace(tzinfo=LONDON)
    hour = when.hour
    scale = hour_scale(hour)

    routes = []
    for rank, t in enumerate(ROUTE_TEMPLATES, start=1):
        factors = [
            {"key": k, "label": FACTOR_LABELS[k], "minutes": float(round(t["factors"][k][0] * scale)), "description": t["factors"][k][1]}
            for k in ALL_KEYS
        ]
        delay = sum(f["minutes"] for f in factors)
        total = t["timetable"] + delay
        if mode == "depart":
            depart, arrive = when, when + timedelta(minutes=total)
        else:
            arrive, depart = when, when - timedelta(minutes=total)
        risk_pct = min(95, round(t["risk"] * scale))
        stops = [origin_id] + _via(t["id"], origin_id, destination_id) + [destination_id]
        segments = [_pair_segment(a, b, hour) for a, b in zip(stops, stops[1:])]
        routes.append({
            "id": t["id"],
            "label": t["label"],
            "rank": rank,
            "depart_at": depart,
            "arrive_at": arrive,
            "timetable_minutes": float(t["timetable"]),
            "predicted_delay_minutes": delay,
            "predicted_minutes": total,
            "risk_level": "low" if risk_pct < 25 else "medium" if risk_pct < 55 else "high",
            "risk_pct": risk_pct,
            "lines": t["lines"],
            "walk_minutes": t["walk"],
            "explanation": t["explanation"],
            "factors": factors,
            "path": [[STOPS[s]["lat"], STOPS[s]["lon"]] for s in stops],
            "segments": segments,
            "callouts": _callouts(t["id"], origin_id, destination_id, hour),
        })

    return {
        "origin": STOPS[origin_id],
        "destination": STOPS[destination_id],
        "mode": mode,
        "time": when,
        "conditions": CONDITIONS,
        "routes": routes,
        "model": {"confidence": "medium", "data_basis": "6 weeks of GM bus data"},
    }