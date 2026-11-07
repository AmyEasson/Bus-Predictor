#!/usr/bin/env python3
"""
compute_delays.py - actual minus scheduled arrival at every stop, for matched bus runs.

Trip matching is done upstream by delay_engine/trip_matching (prepare_timetable.py + matcher.py).
This script takes its runs_matched.parquet and, for each matched run:
  1. reads the run's GPS fixes from the SAME snapshot the matcher used,
  2. works out when the bus passed each stop on its trip (interpolating between fixes),
  3. computes delay = actual - scheduled, handling post-midnight trips and UTC/local time,
  4. writes analysis.sqlite -> table stop_arrivals.

Usage (from the project root):
    python3 delay_engine/stop_arrivals/compute_delays.py \
        --snapshot snapshot.sqlite \
        --matched delay_engine/trip_matching/out/runs_matched.parquet \
        --gtfs gtfs/ \
        --out analysis.sqlite

Time handling: everything is UTC internally. GTFS stop times are seconds since the start of the
service day, which GTFS defines as local noon minus 12 h (= local midnight except on clock-change
days). Times past 24:00:00 therefore carry into the next calendar day automatically.
"""
import argparse
import sqlite3
import time

import numpy as np
import pandas as pd

TZ = "Europe/London"
PASS_RADIUS_M = 150        # track must come this close to a stop to count as passing it
MAX_ABS_DELAY_S = 3600     # delays bigger than 1 hour (early or late) are almost always wrong
EPOCH = pd.Timestamp("1970-01-01", tz="UTC") #reference point for converting times to seconds


# ---------------------------------------------------------------- inputs -------------------

def gtfs_secs(s):
    """Convert a column of GTFS time strings to seconds since the start of the service day"""
    h, m, sec = s.str.strip().str.split(":", expand=True).astype(int).T.values
    return h * 3600 + m * 60 + sec


def service_day_start_utc(service_date):
    """For each service date, return the moment its service day starts, in UTC"""
    noon = (service_date + pd.Timedelta(hours=12)).dt.tz_localize(TZ)
    return (noon - pd.Timedelta(hours=12)).dt.tz_convert("UTC")


def make_run_id(operator_ref, vehicle_ref, aimed_utc):
    """Build a stable text ID for a run: operator|vehicle|scheduled origin deprature (UTC)
    This is the same definition of a "run" that matcher.py uses (one bus doing one journey).
    We rebuild it here rather than using the matcher's run_id column, because that column is just
    a row number and changes every time the matcher is re-run.
    Missing operator codes become '' so they still join consistently on both sides."""
    return (operator_ref.fillna("").astype(str) + "|" + vehicle_ref.astype(str) + "|"
            + aimed_utc.dt.strftime("%Y-%m-%dT%H:%M:%SZ"))


def load_matched(path):
    """Read the matcher's output: one row per live run that was matched to a timetabled trip."""
    m = pd.read_parquet(path)
    m["aimed_utc"] = pd.to_datetime(m.aimed_utc, utc=True)
    m["run_id"] = make_run_id(m.operator_ref, m.vehicle_ref, m.aimed_utc)
    m["service_date"] = pd.to_datetime(m.service_date.astype(str).str[:10])
    m["day_start"] = service_day_start_utc(m.service_date)
    line_col = "route_short_name" if "route_short_name" in m else "line"
    m = m.rename(columns={line_col: "route_short_name"})
    keep = ["run_id", "operator_ref", "vehicle_ref", "aimed_utc", "trip_id",
            "route_short_name", "service_date", "day_start"]
    if "direction_id" in m:
        keep.append("direction_id")
    m = m[keep].drop_duplicates("run_id")
    print(f"Matched runs from matcher: {len(m):,}")
    return m


def load_stop_times(gtfs, trip_ids):
    """Stop times + stop coordinates for the matched trips only."""
    wanted = set(trip_ids)
    parts = []
    for chunk in pd.read_csv(gtfs + "stop_times.txt", dtype=str, chunksize=1_000_000,
                             usecols=["trip_id", "arrival_time", "departure_time",
                                      "stop_id", "stop_sequence"]):
        parts.append(chunk[chunk.trip_id.isin(wanted)])
    st = pd.concat(parts, ignore_index=True)
    st["stop_sequence"] = st.stop_sequence.astype(int)
    st["sched_s"] = gtfs_secs(st.arrival_time.fillna(st.departure_time))
    st = st.sort_values(["trip_id", "stop_sequence"])
    stops = pd.read_csv(gtfs + "stops.txt", dtype={"stop_id": str},
                        usecols=["stop_id", "stop_name", "stop_lat", "stop_lon"])
    st = st.merge(stops, on="stop_id", how="left")
    st["is_first_stop"] = st.groupby("trip_id").stop_sequence.transform("min") == st.stop_sequence
    st["is_last_stop"] = st.groupby("trip_id").stop_sequence.transform("max") == st.stop_sequence
    return st[["trip_id", "stop_id", "stop_sequence", "sched_s", "stop_name", "stop_lat",
               "stop_lon", "is_first_stop", "is_last_stop"]]


def add_direction(matched, gtfs):
    """direction_id from trips.txt if the matcher didn't carry it through."""
    if "direction_id" in matched:
        return matched
    trips = pd.read_csv(gtfs + "trips.txt", dtype=str)
    if "direction_id" not in trips:
        return matched.assign(direction_id=None)
    return matched.merge(trips[["trip_id", "direction_id"]], on="trip_id", how="left")


def load_positions(snapshot, matched):
    """GPS fixes belonging to the matched runs."""
    lines = sorted(matched.route_short_name.astype(str).unique())
    con = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
    q = ("SELECT operator_ref, vehicle_ref, origin_aimed_departure_time, recorded_at, "
         "latitude, longitude FROM positions WHERE latitude IS NOT NULL "
         f"AND published_line_name IN ({','.join('?' * len(lines))})")
    pos = pd.read_sql(q, con, params=lines)
    con.close()
    pos["recorded_at"] = pd.to_datetime(pos.recorded_at, utc=True, format="ISO8601")
    pos["aimed_utc"] = pd.to_datetime(pos.origin_aimed_departure_time, utc=True,
                                      format="ISO8601")
    pos["run_id"] = make_run_id(pos.operator_ref, pos.vehicle_ref, pos.aimed_utc)
    pos = pos[pos.run_id.isin(matched.run_id)]
    print(f"GPS fixes for matched runs: {len(pos):,}")
    return pos[["run_id", "recorded_at", "latitude", "longitude"]]


# ---------------------------------------------------------------- stop passings ------------

def to_xy(lat, lon, lat0):
    """Local flat-earth metres - fine over a few km."""
    k = 111_320.0
    return np.asarray(lon) * k * np.cos(np.radians(lat0)), np.asarray(lat) * k


def passing_time(fx, fy, ft, sx, sy):
    """Time the bus was nearest point (sx, sy), interpolating between GPS fixes.
    Returns (epoch seconds, distance in metres)."""
    d = np.hypot(fx - sx, fy - sy)
    i = int(d.argmin())
    best_t, best_d = ft[i], d[i]
    for j in (i - 1, i):                       # segments either side of the closest fix
        if j < 0 or j + 1 >= len(fx):
            continue
        ax, ay, bx, by = fx[j], fy[j], fx[j + 1], fy[j + 1]
        seg2 = (bx - ax) ** 2 + (by - ay) ** 2
        if seg2 == 0:
            continue
        f = min(1.0, max(0.0, ((sx - ax) * (bx - ax) + (sy - ay) * (by - ay)) / seg2))
        px, py = ax + f * (bx - ax), ay + f * (by - ay)
        dd = np.hypot(px - sx, py - sy)
        if dd < best_d:
            best_d, best_t = dd, ft[j] + f * (ft[j + 1] - ft[j])
    return best_t, best_d


def stop_passings(pos, matched, st):
    pos = pos.merge(matched[["run_id", "trip_id"]], on="run_id")
    st_by_trip = dict(tuple(st.groupby("trip_id")))
    lat0 = pos.latitude.mean()
    out = []
    for run_id, fixes in pos.sort_values("recorded_at").groupby("run_id"):
        if len(fixes) < 3:
            continue
        stops = st_by_trip.get(fixes.trip_id.iloc[0])
        if stops is None:
            continue
        fx, fy = to_xy(fixes.latitude.values, fixes.longitude.values, lat0)
        ft = (fixes.recorded_at - EPOCH).dt.total_seconds().values
        sx, sy = to_xy(stops.stop_lat.values, stops.stop_lon.values, lat0)
        res = [passing_time(fx, fy, ft, x, y) for x, y in zip(sx, sy)]
        t = np.array([r[0] for r in res])
        d = np.array([r[1] for r in res])
        ok = d <= PASS_RADIUS_M
        if ok.sum() < 2:
            continue
        s = stops[ok].copy()
        s["actual_utc"] = pd.to_datetime(t[ok], unit="s", utc=True)
        s["match_dist_m"] = d[ok].round(1)
        s["run_id"] = run_id
        out.append(s)
    if not out:
        raise SystemExit("No stop passings found - check the snapshot is the one the matcher "
                         "used and that PASS_RADIUS_M is sensible")
    arr = pd.concat(out, ignore_index=True)

    # Arrival times must increase along the trip: drop stops that go backwards (GPS noise, loops)
    arr = arr.sort_values(["run_id", "stop_sequence"])
    arr = arr[arr.actual_utc >= arr.groupby("run_id").actual_utc.cummax()]
    return arr.merge(matched, on=["run_id", "trip_id"])


# ---------------------------------------------------------------- main ---------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default="snapshot.sqlite",
                    help="the SAME snapshot matcher.py was run on")
    ap.add_argument("--matched", default="delay_engine/trip_matching/out/runs_matched.parquet")
    ap.add_argument("--gtfs", default="gtfs/", help="folder with stop_times.txt, stops.txt, trips.txt")
    ap.add_argument("--out", default="analysis.sqlite")
    args = ap.parse_args()
    gtfs = args.gtfs if args.gtfs.endswith("/") else args.gtfs + "/"
    t0 = time.time()

    matched = add_direction(load_matched(args.matched), gtfs)
    st = load_stop_times(gtfs, matched.trip_id)
    pos = load_positions(args.snapshot, matched)
    arr = stop_passings(pos, matched, st)
    print(f"Runs with stop arrivals: {arr.run_id.nunique():,} of {len(matched):,}")

    # Delay = actual - scheduled. Both UTC; day_start absorbs the timezone,
    # sched_s > 86400 carries post-midnight trips into the next calendar day.
    arr["scheduled_utc"] = arr.day_start + pd.to_timedelta(arr.sched_s, unit="s")
    arr["delay_s"] = (arr.actual_utc - arr.scheduled_utc).dt.total_seconds().round()
    n = len(arr)
    arr = arr[arr.delay_s.abs() <= MAX_ABS_DELAY_S]
    print(f"Stop arrivals: {len(arr):,} ({n - len(arr):,} dropped as |delay| > 1 h)")

    cols = ["run_id", "trip_id", "route_short_name", "direction_id", "service_date",
            "stop_id", "stop_sequence", "stop_name", "stop_lat", "stop_lon",
            "scheduled_utc", "actual_utc", "delay_s", "match_dist_m",
            "is_first_stop", "is_last_stop"]
    res = arr[cols].copy()
    for c in ("scheduled_utc", "actual_utc"):
        res[c] = res[c].dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    res["service_date"] = res.service_date.dt.strftime("%Y-%m-%d")

    out = sqlite3.connect(args.out)
    res.to_sql("stop_arrivals", out, if_exists="replace", index=False)
    out.execute("CREATE INDEX IF NOT EXISTS idx_sa_route ON stop_arrivals(route_short_name, stop_id)")
    out.commit()
    out.close()

    # Sanity summary (exclude terminus stops, which are distorted by waiting/padding)
    mid = arr[~arr.is_first_stop & ~arr.is_last_stop]
    print("\nDelay by route (minutes, excluding first/last stops):")
    print((mid.groupby("route_short_name").delay_s
              .describe(percentiles=[.5, .9])[["count", "mean", "50%", "90%"]] / [1, 60, 60, 60])
          .round(1).to_string())
    print(f"\nWrote {len(res):,} rows to {args.out} -> stop_arrivals  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()