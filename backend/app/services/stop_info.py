"""Everything the stop card shows: the stop, lines serving it, next departures (timetable) and how late
buses typically are there (delay engine export)."""
from datetime import date, datetime
from functools import lru_cache

from . import delay
from .journey import get_active_service_ids, load_timetable_data


@lru_cache(maxsize=1)
def stop_summaries():
    """Per stop: the lines using it and where most of its buses head ("towards ...").
    86% of stop names are shared by several stops, so search results need this to tell them apart.
    Built once from the timetable (~2 s), then cached."""
    stop_times, trips, routes, _ = load_timetable_data()
    t = trips[["trip_id", "route_id", "trip_headsign"]].merge(routes[["route_id", "route_short_name"]], on="route_id")
    st = stop_times[["trip_id", "stop_id", "stop_sequence"]]
    # the last stop of a trip is an arrival only, so it says nothing about where buses from here go
    last = st.groupby("trip_id").stop_sequence.transform("max")
    x = st[st.stop_sequence < last].merge(t, on="trip_id")
    lines = x.groupby("stop_id").route_short_name.agg(
        lambda v: sorted(set(v.astype(str)), key=lambda r: (len(r), r)))
    heads = (x[x.trip_headsign.fillna("") != ""].groupby(["stop_id", "trip_headsign"]).size()
             .reset_index(name="n").sort_values("n", ascending=False).drop_duplicates("stop_id")
             .set_index("stop_id").trip_headsign)
    return {"lines": lines.to_dict(), "towards": heads.to_dict()}


def describe_stop(stop_id):
    """{"lines": [...], "towards": str | None} for one stop."""
    s = stop_summaries()
    return {"lines": s["lines"].get(stop_id, []), "towards": s["towards"].get(stop_id)}


def _hhmm(seconds):
    h, m = divmod(int(seconds) // 60, 60)
    return f"{h % 24:02d}:{m:02d}"


def get_stop_info(stop_id: str, when: datetime, limit: int = 8):
    stop_times, trips, routes, stops = load_timetable_data()
    row = stops[stops.stop_id == stop_id]
    if row.empty:
        return None
    s = row.iloc[0]

    at_stop = stop_times[stop_times.stop_id == stop_id][["trip_id", "stop_sequence", "dep_s"]]
    at_stop = at_stop.merge(trips[["trip_id", "route_id", "service_id", "trip_headsign"]], on="trip_id")
    at_stop = at_stop.merge(routes[["route_id", "route_short_name"]], on="route_id")

    lines = sorted(set(at_stop.route_short_name.astype(str)), key=lambda x: (len(x), x))

    # next departures today (trips whose service runs today, leaving from now on)
    today: date = when.date()
    now_s = when.hour * 3600 + when.minute * 60
    active = get_active_service_ids(today)
    nxt = at_stop[at_stop.service_id.isin(active) & (at_stop.dep_s >= now_s)]
    # skip trips that end here (nothing to board)
    last_seq = stop_times[stop_times.trip_id.isin(nxt.trip_id)].groupby("trip_id").stop_sequence.max()
    nxt = nxt[nxt.stop_sequence < nxt.trip_id.map(last_seq)]
    nxt = nxt.sort_values("dep_s").head(limit)
    departures = [{"route": str(r.route_short_name), "headsign": r.trip_headsign or "",
                   "time": _hhmm(r.dep_s), "minutes_away": int((r.dep_s - now_s) // 60),
                   "trip_id": r.trip_id} for r in nxt.itertuples(index=False)]

    try:
        typical = delay.get_stop_typical(stop_id, when.hour)
    except delay.DelayDataMissing:
        typical = None

    return {
        "stop": {"stop_id": stop_id, "stop_name": s.stop_name,
                 "stop_lat": float(s.stop_lat), "stop_lon": float(s.stop_lon)},
        "lines": lines,
        "towards": describe_stop(stop_id)["towards"],
        "departures": departures,
        "typical": typical,
    }
