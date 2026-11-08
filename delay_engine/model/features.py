"""
features.py - shared feature engineering for the delay model.

Used by build_pairs.py (training) AND predict.py (live predictions), so the model always sees
features computed the same way.

Feature groups
--------------
  core       delay now, stops ahead, scheduled travel time, route, direction, destination stop
  time       local hour, minutes since midnight, weekend flag, peak flag, darkness
  live       recent delay on this route (last 30 min), recent delay ADDED anywhere on the
             corridor (last 30 min), gap to the bus in front (bunching)
  weather    rain, temperature, wind                 (context/context_hourly.parquet)
  calendar   school term, bank holiday                (context/context_hourly.parquet)
  events     big event on anywhere in the city + crowd size  (context/context_hourly.parquet)
             event near THIS stop + its crowd size           (context/events.csv)

Context files come from the context teammate (see context/ README):
  context_hourly.parquet  one row per hour (UTC), joined on the bus timestamp floored to the hour
  events.csv              one row per big event, with venue lat/lon and UTC start/end
Missing files are fine: those features become empty and train.py skips them.

All timestamps are UTC internally; local time (Europe/London) is only used for "hour of day".
"""
import os
import sqlite3

import numpy as np
import pandas as pd

TZ = "Europe/London"
RECENT_WINDOW = "30min"          # how far back the "live" features look
EVENT_RADIUS_KM = 1.5            # stops this close to a venue count as "near an event"
EVENT_BEFORE_H, EVENT_AFTER_H = 2, 2   # crowds arriving 2 h before start, leaving up to 2 h after
                                       # (after-window matches context_hourly's event_active)
MANCHESTER = (53.48, -2.24)            # for sunrise/sunset (darkness feature)

# Feature lists, grouped so train.py can test each group's contribution (ablation)
CORE = ["delay_now_s", "stops_ahead", "sched_travel_s", "route", "direction", "to_stop"]
TIME = ["hour", "minute_of_day", "is_weekend", "is_peak", "is_dark"]
LIVE = ["recent_route_delay_s", "recent_added_delay_s", "gap_ahead_s", "headway_ratio"]
WEATHER = ["precipitation", "temperature_2m", "wind_speed_10m"]
CALENDAR = ["is_school_term", "is_bank_holiday"]
EVENTS = ["event_active", "event_attendance", "event_nearby", "event_nearby_attendance"]
HOURLY_COLS = WEATHER + CALENDAR + ["event_active", "event_attendance"]   # from context_hourly
CATEGORICAL = ["route", "direction", "to_stop"]


# ------------------------------------------------------------------------------------------
# Loading stop arrivals
# ------------------------------------------------------------------------------------------

_GTFS_CACHE = {}


def _gtfs_lookups(gtfs):
    """Trip directions and stop names from the GTFS .parquet tables, loaded once per folder."""
    if gtfs not in _GTFS_CACHE:
        trips = pd.read_parquet(os.path.join(gtfs, "trips.parquet"))
        trips = trips[["trip_id"] + (["direction_id"] if "direction_id" in trips else [])]
        stops = pd.read_parquet(os.path.join(gtfs, "stops.parquet"), columns=["stop_id", "stop_name"])
        _GTFS_CACHE[gtfs] = (trips, stops)
    return _GTFS_CACHE[gtfs]


def _trip_ends(gtfs, trip_ids):
    """First and last stop_sequence of each trip - reads stop_times only for these trips
    (the full North West stop_times table is far too big to load whole)."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    t = pq.read_table(os.path.join(gtfs, "stop_times.parquet"), columns=["trip_id", "stop_sequence"])
    t = t.filter(pc.is_in(t["trip_id"], value_set=pa.array(list(trip_ids), type=t["trip_id"].type)))
    return t.to_pandas().groupby("trip_id").stop_sequence.agg(["min", "max"])


def _read_team_arrivals(path, gtfs):
    """Read arrivals.py output (stop_arrivals.parquet) and add the GTFS fields the model needs.

    arrivals.py columns -> model columns: line -> route_short_name, sched_arr_utc ->
    scheduled_utc, actual_arr_utc -> actual_utc. run_id is rebuilt as
    service_date|operator|vehicle|trip (arrivals.py's run_id is a per-file row number).
    Added from the GTFS .parquet tables in `gtfs`: direction_id, stop_name, first/last-stop flags.
    """
    sa = pd.read_parquet(path)
    sa = sa.rename(columns={"line": "route_short_name", "sched_arr_utc": "scheduled_utc",
                            "actual_arr_utc": "actual_utc"})
    sa["run_id"] = (sa.service_date.astype(str) + "|" + sa.operator_ref.fillna("").astype(str)
                    + "|" + sa.vehicle_ref.astype(str) + "|" + sa.trip_id.astype(str))

    trips, stops = _gtfs_lookups(gtfs)
    sa = sa.merge(trips, on="trip_id", how="left") if "direction_id" in trips \
        else sa.assign(direction_id=None)
    sa = sa.merge(stops, on="stop_id", how="left")
    sa["stop_name"] = sa.stop_name.fillna(sa.stop_id)

    ends = _trip_ends(gtfs, set(sa.trip_id))
    sa = sa.merge(ends, left_on="trip_id", right_index=True, how="left")
    sa["is_first_stop"] = (sa.stop_sequence == sa["min"]).astype(int)
    sa["is_last_stop"] = (sa.stop_sequence == sa["max"]).astype(int)
    return sa.drop(columns=["min", "max"])


def load_stop_arrivals(path="delay_engine/trip_matching/out/stop_arrivals.parquet", gtfs="data/"):
    """Load stop-by-stop delays and add per-arrival helper columns.

    Accepts either
      * the team pipeline's arrivals.py output   (a .parquet file)   <- the normal input now
      * compute_delays.py's output               (a .sqlite file, table stop_arrivals)

    Adds:
      added_delay_s  delay gained since the previous observed stop on the same run
                     (where delay is CREATED - used for the corridor congestion feature)
      gap_ahead_s    seconds since the previous bus on the same route+direction passed this stop
      headway_ratio  actual gap / scheduled gap  (<0.5 = bunched behind another bus,
                     >1.5 = big gap in front)
    """
    gtfs = gtfs if gtfs.endswith("/") else gtfs + "/"
    if str(path).endswith(".parquet"):
        sa = _read_team_arrivals(path, gtfs)
    else:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        sa = pd.read_sql("SELECT * FROM stop_arrivals", con)
        con.close()
    for c in ("scheduled_utc", "actual_utc"):
        sa[c] = pd.to_datetime(sa[c], utc=True, format="ISO8601")
    sa = sa.dropna(subset=["actual_utc", "scheduled_utc", "delay_s"])
    sa["direction_id"] = sa.direction_id.astype(str)
    sa["route_short_name"] = sa.route_short_name.astype(str)

    # Delay added since the previous stop of the same run - only when the two stops are
    # ADJACENT on the trip. If stops in between were missed, the difference would cover several
    # stretches of road and look like one huge hotspot.
    sa = sa.sort_values(["run_id", "stop_sequence"])
    g_run = sa.groupby("run_id")
    sa["added_delay_s"] = g_run.delay_s.diff()
    if "stop_idx" in sa:                       # arrivals.py: position of the stop in its trip
        sa.loc[g_run.stop_idx.diff() != 1, "added_delay_s"] = np.nan

    # Headway at each stop: compare consecutive buses of the same route+direction at that stop
    sa = sa.sort_values(["route_short_name", "direction_id", "stop_id", "actual_utc"])
    g = sa.groupby(["route_short_name", "direction_id", "stop_id"])
    sa["gap_ahead_s"] = g.actual_utc.diff().dt.total_seconds()
    sched_gap = g.scheduled_utc.diff().dt.total_seconds()
    sa["headway_ratio"] = sa.gap_ahead_s / sched_gap.where(sched_gap > 0)
    return sa.sort_values(["run_id", "stop_sequence"]).reset_index(drop=True)


# ------------------------------------------------------------------------------------------
# Time features
# ------------------------------------------------------------------------------------------

def sun_elevation_deg(ts_utc, lat=MANCHESTER[0], lon=MANCHESTER[1]):
    """Approximate solar elevation (degrees) for UTC timestamps. Accurate to well under a degree,
    which is plenty for "is it dark?". Below 0 = sun has set."""
    t = ts_utc.dt.tz_convert("UTC")
    doy = t.dt.dayofyear.values
    hours = (t.dt.hour + t.dt.minute / 60 + t.dt.second / 3600).values
    g = 2 * np.pi / 365 * (doy - 1 + (hours - 12) / 24)               # fractional year
    decl = (0.006918 - 0.399912 * np.cos(g) + 0.070257 * np.sin(g) - 0.006758 * np.cos(2 * g)
            + 0.000907 * np.sin(2 * g) - 0.002697 * np.cos(3 * g) + 0.00148 * np.sin(3 * g))
    eqtime = 229.18 * (0.000075 + 0.001868 * np.cos(g) - 0.032077 * np.sin(g)
                       - 0.014615 * np.cos(2 * g) - 0.040849 * np.sin(2 * g))   # minutes
    solar_time = hours * 60 + eqtime + 4 * lon                         # minutes
    ha = np.radians(solar_time / 4 - 180)                              # hour angle
    la = np.radians(lat)
    el = np.arcsin(np.sin(la) * np.sin(decl) + np.cos(la) * np.cos(decl) * np.cos(ha))
    return np.degrees(el)


def add_time_features(df, ts_col="now_utc"):
    """Hour of day etc. from a UTC timestamp column (converted to UK local time first)."""
    local = df[ts_col].dt.tz_convert(TZ)
    df["hour"] = local.dt.hour
    df["minute_of_day"] = local.dt.hour * 60 + local.dt.minute
    df["is_weekend"] = (local.dt.dayofweek >= 5).astype(int)
    weekday = df.is_weekend == 0
    df["is_peak"] = (weekday & (local.dt.hour.between(7, 9) | local.dt.hour.between(16, 18))) \
        .astype(int)
    df["is_dark"] = (sun_elevation_deg(df[ts_col]) < 0).astype(int)
    return df


# ------------------------------------------------------------------------------------------
# Live (recent) features - things a passenger app would know at prediction time
# ------------------------------------------------------------------------------------------

def _rolling_median(events, key_cols, value_col, window=RECENT_WINDOW):
    """Median of value_col over the trailing window (strictly before each time), per key."""
    out = []
    for key, grp in events.dropna(subset=[value_col]).groupby(key_cols):
        s = grp.set_index("actual_utc")[value_col].sort_index()
        r = s.rolling(window, closed="left").median()
        frame = r.rename("value").reset_index()
        if not isinstance(key, tuple):
            key = (key,)
        for k, v in zip(key_cols, key):
            frame[k] = v
        out.append(frame)
    if not out:
        return pd.DataFrame(columns=["actual_utc", "value", *key_cols])
    return pd.concat(out, ignore_index=True).dropna(subset=["value"])


def live_tables(sa):
    """Pre-compute the rolling "last 30 minutes" tables from stop arrivals ONCE.

    Pass the result to add_live_features(..., tables=...) for every batch of pairs - recomputing
    them per batch is what makes large runs crawl."""
    mid = sa[(sa.is_first_stop == 0) & (sa.is_last_stop == 0)]

    # Route-level recent delay (per route + direction)
    rr = _rolling_median(mid, ["route_short_name", "direction_id"], "delay_s")
    rr = rr.rename(columns={"route_short_name": "route", "direction_id": "direction",
                            "value": "recent_route_delay_s"}).sort_values("actual_utc")

    # Network-wide recent added delay (all routes together)
    ca = mid.dropna(subset=["added_delay_s"]).set_index("actual_utc").added_delay_s.sort_index()
    ca = ca.rolling(RECENT_WINDOW, closed="left").median().rename("recent_added_delay_s") \
        .reset_index().dropna()
    return rr, ca


def add_live_features(df, sa=None, ts_col="now_utc", tables=None):
    """Attach recent-delay features as known at time ts_col (no peeking into the future).

    recent_route_delay_s   median delay of all buses on this route+direction in the last 30 min
    recent_added_delay_s   median delay ADDED per stop across the network, last 30 min
                           (a live "traffic is getting worse" signal)
    Give either `sa` (stop arrivals; tables are computed here) or `tables` from live_tables(sa).
    """
    rr, ca = tables if tables is not None else live_tables(sa)
    idx_name = "_row"
    df = df.reset_index(drop=True)
    df[idx_name] = np.arange(len(df))
    df = df.sort_values(ts_col)
    df = pd.merge_asof(df, rr, left_on=ts_col, right_on="actual_utc",
                       by=["route", "direction"], direction="backward",
                       tolerance=pd.Timedelta(RECENT_WINDOW)).drop(columns="actual_utc")
    df = pd.merge_asof(df, ca, left_on=ts_col, right_on="actual_utc", direction="backward",
                       tolerance=pd.Timedelta(RECENT_WINDOW)).drop(columns="actual_utc")
    return df.sort_values(idx_name).drop(columns=idx_name).reset_index(drop=True)


# ------------------------------------------------------------------------------------------
# Hourly context: weather, calendar, city-wide events (context_hourly.parquet)
# ------------------------------------------------------------------------------------------

def load_context_hourly(path="context/context_hourly.parquet"):
    """One row per hour (UTC). Only the columns the model uses are kept."""
    if not os.path.exists(path):
        return None
    c = pd.read_parquet(path)
    c["hour_utc"] = pd.to_datetime(c.hour_utc, utc=True)
    keep = ["hour_utc"] + [col for col in HOURLY_COLS if col in c]
    return c[keep].drop_duplicates("hour_utc")


def add_hourly_context(df, ctx, ts_col="now_utc"):
    """Join hourly context on the timestamp floored to the hour."""
    if ctx is None:
        for col in HOURLY_COLS:
            df[col] = np.nan
        return df
    df["hour_utc"] = df[ts_col].dt.floor("h")
    df = df.merge(ctx, on="hour_utc", how="left").drop(columns="hour_utc")
    for col in HOURLY_COLS:                 # columns the context file didn't have
        if col not in df:
            df[col] = np.nan
    return df


# ------------------------------------------------------------------------------------------
# Events near a specific stop (events.csv)
# ------------------------------------------------------------------------------------------

def load_events(path="context/events.csv"):
    """Columns used: venue, lat, lon, start_utc, end_utc, expected_attendance (or capacity)."""
    if not os.path.exists(path):
        return None
    ev = pd.read_csv(path)
    ev["start_utc"] = pd.to_datetime(ev.start_utc, utc=True)
    ev["end_utc"] = pd.to_datetime(ev.end_utc, utc=True)
    size = "expected_attendance" if "expected_attendance" in ev else "capacity"
    ev["attendance"] = pd.to_numeric(ev[size], errors="coerce").fillna(0)
    return ev.dropna(subset=["lat", "lon", "start_utc", "end_utc"])


def _km(lat1, lon1, lat2, lon2):
    return 111.32 * np.hypot(lat2 - lat1, (lon2 - lon1) * np.cos(np.radians(lat1)))


def add_events(df, ev, ts_col="now_utc", lat_col="to_lat", lon_col="to_lon"):
    """event_nearby = 1 if the destination stop is within EVENT_RADIUS_KM of a venue from
    2 h before the start to 2 h after the end; event_nearby_attendance = crowd size (0 if none)."""
    df["event_nearby"] = 0
    df["event_nearby_attendance"] = 0.0
    if ev is None:
        return df
    # Only events overlapping the data's time range matter (the file covers the whole year)
    lo = df[ts_col].min() - pd.Timedelta(hours=EVENT_AFTER_H)
    hi = df[ts_col].max() + pd.Timedelta(hours=EVENT_BEFORE_H)
    ev = ev[(ev.end_utc >= lo) & (ev.start_utc <= hi)]
    for e in ev.itertuples():
        near = _km(df[lat_col], df[lon_col], e.lat, e.lon) < EVENT_RADIUS_KM
        during = df[ts_col].between(e.start_utc - pd.Timedelta(hours=EVENT_BEFORE_H),
                                    e.end_utc + pd.Timedelta(hours=EVENT_AFTER_H))
        hit = near & during
        df.loc[hit, "event_nearby"] = 1
        df.loc[hit, "event_nearby_attendance"] = np.maximum(
            df.loc[hit, "event_nearby_attendance"], e.attendance)
    return df