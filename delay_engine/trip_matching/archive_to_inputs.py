#!/usr/bin/env python3
"""
archive_to_inputs.py - feed the BODS archive through the team's arrivals.py, unchanged.

The archive (bods_archive/gm_YYYYMMDD.parquet) is GTFS-realtime vehicle positions:
    trip_id, route_id, start_date, start_time, lat, lon, bearing, timestamp, vehicle_id
Every position already carries its timetable trip_id, so matcher.py isn't needed. This script
writes exactly the two inputs arrivals.py reads, so archive and live delays come from the SAME code:

    <out-dir>/archive_snapshot.sqlite   table "positions", same columns arrivals.py queries
    <out-dir>/runs_matched.parquet      one row per run, same columns matcher.py writes

Then run arrivals.py on them (from the project root):

    python3 delay_engine/trip_matching/archive_to_inputs.py \
        --archive bods_archive/ --gtfs-dir <folder with trips/routes .parquet> \
        --out-dir delay_engine/trip_matching/out_archive --lines 42,43,50,142,143

    python3 delay_engine/trip_matching/arrivals.py \
        --snapshot delay_engine/trip_matching/out_archive/archive_snapshot.sqlite \
        --gtfs-dir <same folder> --out-dir delay_engine/trip_matching/out_archive

    -> delay_engine/trip_matching/out_archive/stop_arrivals.parquet  (same format as live)

Use a separate --out-dir (out_archive) so the live pipeline's out/ files aren't overwritten.

How runs are defined (so arrivals.py's join works):
    run         = one bus (vehicle_id) running one trip_id on one start_date
    operator    = "ARCHIVE" (the archive has no operator code)
    aimed_utc   = scheduled trip start in UTC = service-day start + start_time
                  (service day starts at local noon minus 12 h, same rule as arrivals.py,
                  so post-midnight start_times like 24:40:00 and BST/GMT are handled)
The archive has at most one position per bus per minute; arrivals.py interpolates between
positions and its default --max-gap of 120 s still keeps normal 60 s gaps.
"""
import argparse
import glob
import os
import re
import sqlite3
import time

import pandas as pd
import pyarrow.parquet as pq

TZ = "Europe/London"
OPERATOR = "ARCHIVE"


def day_of(path):
    m = re.search(r"(\d{8})", os.path.basename(path))
    return m.group(1) if m else ""


def service_day_start_utc(dates):
    """Naive service dates -> UTC start of each service day (local noon minus 12 h)."""
    noon = (dates + pd.Timedelta(hours=12)).dt.tz_localize(TZ)
    return (noon - pd.Timedelta(hours=12)).dt.tz_convert("UTC")


def hhmmss_to_s(s):
    """'07:30:00' -> 27000, '24:40:00' -> 88800. Blank or malformed values -> NaN (not a crash)."""
    p = s.astype(str).str.strip().str.extract(r"^(\d{1,2}):(\d{2}):(\d{2})$")
    p = p.apply(pd.to_numeric, errors="coerce")
    return p[0] * 3600 + p[1] * 60 + p[2]


def first_departures(gtfs_dir, trip_ids):
    """Scheduled first departure (s since service-day start) of each trip, from the timetable.
    Used when an archive row's start_time is blank or malformed."""
    st = pd.read_parquet(os.path.join(gtfs_dir, "stop_times.parquet"),
                         columns=["trip_id", "stop_sequence", "dep_s"],
                         filters=[("trip_id", "in", list(trip_ids))])
    st = st.sort_values(["trip_id", "stop_sequence"])
    return st.groupby("trip_id").dep_s.first()


# Route numbers are NOT unique across the North West: other towns' operators also run a "42" or
# a "43". Keep only routes whose stops are, on average, inside this central-Manchester box.
# (Warrington, Wigan, Bolton etc. fall outside it.) Override with --route-ids if needed.
MANCHESTER_BOX = dict(min_lat=53.35, max_lat=53.56, min_lon=-2.40, max_lon=-2.05)


def load_trip_lines(gtfs_dir, lines, route_ids=None):
    """trip_id -> line, for the lines we want, keeping only the Manchester routes with that number.

    Prints every candidate route (agency, trips, where its stops are) and whether it's kept,
    so you can see exactly which operators' routes go into the analysis."""
    trips = pd.read_parquet(os.path.join(gtfs_dir, "trips.parquet"), columns=["trip_id", "route_id"])
    routes = pd.read_parquet(os.path.join(gtfs_dir, "routes.parquet"))
    routes["route_short_name"] = routes.route_short_name.astype(str).str.strip()
    routes["route_id"] = routes.route_id.astype(str)
    trips["route_id"] = trips.route_id.astype(str)
    cand = routes[routes.route_short_name.isin(lines)]
    t = trips.merge(cand[["route_id", "route_short_name"]], on="route_id")

    # Where each candidate route runs: mean position of its trips' first stops
    st = pd.read_parquet(os.path.join(gtfs_dir, "stop_times.parquet"),
                         columns=["trip_id", "stop_sequence", "stop_id"],
                         filters=[("trip_id", "in", list(set(t.trip_id)))])
    stops = pd.read_parquet(os.path.join(gtfs_dir, "stops.parquet"),
                            columns=["stop_id", "stop_lat", "stop_lon"])
    for c in ("stop_lat", "stop_lon"):
        stops[c] = pd.to_numeric(stops[c], errors="coerce")
    where = (st.merge(t[["trip_id", "route_id"]], on="trip_id").merge(stops, on="stop_id")
               .groupby("route_id")[["stop_lat", "stop_lon"]].mean())

    info = cand.set_index("route_id")[[c for c in ("agency_id", "route_short_name")
                                        if c in cand]].join(where)
    info["trips"] = t.groupby("route_id").size()
    if route_ids:
        info["keep"] = info.index.isin(route_ids)
    else:
        b = MANCHESTER_BOX
        info["keep"] = (info.stop_lat.between(b["min_lat"], b["max_lat"])
                        & info.stop_lon.between(b["min_lon"], b["max_lon"]))
    print("candidate routes (route numbers are shared with other towns):")
    print(info.round(3).to_string())

    kept = set(info.index[info.keep])
    t = t[t.route_id.isin(kept)]
    print(f"GTFS: lines {lines} -> {len(kept)} Manchester routes, {len(t):,} trips")
    return t[["trip_id", "route_short_name"]].rename(columns={"route_short_name": "line"})


def read_day(path, trip_ids):
    """One day's positions for our trips only (filtered while reading; files are ~1M rows).
    Empty-string trip ids (~4% of rows) are never in trip_ids, so they're dropped too."""
    df = pq.read_table(path, filters=[("trip_id", "in", trip_ids)]).to_pandas()
    return df[df.lat.notna() & df.lon.notna()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default="bods_archive/", help="folder of gm_YYYYMMDD.parquet")
    ap.add_argument("--gtfs-dir", required=True,
                    help="folder with the GTFS .parquet tables (trips, routes, ...) used by arrivals.py")
    ap.add_argument("--out-dir", default="delay_engine/trip_matching/out_archive")
    ap.add_argument("--lines", default="42,43,50,142,143")
    ap.add_argument("--route-ids", default=None,
                    help="comma-separated route_ids to use instead of the automatic Manchester filter")
    ap.add_argument("--from", dest="date_from", default="00000000", help="YYYYMMDD")
    ap.add_argument("--to", dest="date_to", default="99999999", help="YYYYMMDD")
    a = ap.parse_args()
    lines = [x.strip() for x in a.lines.split(",")]
    os.makedirs(a.out_dir, exist_ok=True)
    t0 = time.time()

    files = sorted(f for f in glob.glob(os.path.join(a.archive, "*.parquet"))
                   if a.date_from <= day_of(f) <= a.date_to)
    if not files:
        raise SystemExit(f"no parquet files in {a.archive} for that date range")

    route_ids = [x.strip() for x in a.route_ids.split(",")] if a.route_ids else None
    trip_lines = load_trip_lines(a.gtfs_dir, lines, route_ids)
    trip_ids = sorted(set(trip_lines.trip_id))

    # ---- read all days (only our trips, so this stays small) ------------------------------
    parts = []
    print(f"\n{'file':8s} {'positions':>10s} {'runs':>6s}")
    for f in files:
        d = read_day(f, trip_ids)
        n_runs = d.drop_duplicates(["vehicle_id", "trip_id", "start_date"]).shape[0]
        print(f"{day_of(f):8s} {len(d):10,d} {n_runs:6,d}"
              + ("   <- none of our trips: timetable mismatch?" if n_runs == 0 else ""))
        parts.append(d)
    pos = pd.concat(parts, ignore_index=True)
    # A bus running across midnight UTC appears in two daily files; same report twice -> once
    pos = pos.drop_duplicates(["vehicle_id", "timestamp"])
    pos = pos.merge(trip_lines, on="trip_id")

    # ---- runs: one per (vehicle, trip, service date) -> matcher.py's output format --------
    runs = pos.drop_duplicates(["vehicle_id", "trip_id", "start_date"]).copy()
    runs["service_dt"] = pd.to_datetime(runs.start_date, format="%Y%m%d", errors="coerce")
    runs = runs[runs.service_dt.notna()]
    # Scheduled start: archive's start_time, or the timetable's first departure if it's
    # blank/malformed (the archive's start_time is only a copy of that anyway)
    start_s = hhmmss_to_s(runs.start_time)
    n_bad = int(start_s.isna().sum())
    if n_bad:
        fallback = runs.trip_id.map(first_departures(a.gtfs_dir, set(runs.trip_id)))
        start_s = start_s.fillna(pd.to_numeric(fallback, errors="coerce"))
        print(f"\n{n_bad:,} runs had a blank/malformed start_time -> used the timetable's first "
              f"departure ({int(start_s.isna().sum()):,} still unknown, dropped)")
    runs = runs[start_s.notna()].copy()
    start_s = start_s[start_s.notna()]
    runs["aimed_utc"] = (service_day_start_utc(runs.service_dt)
                         + pd.to_timedelta(start_s.astype(float), unit="s"))
    runs = runs.sort_values(["service_dt", "aimed_utc", "vehicle_id"]).reset_index(drop=True)
    runs["run_id"] = runs.index.astype("int64")
    matched = pd.DataFrame({
        "run_id": runs.run_id,
        "operator_ref": OPERATOR,
        "vehicle_ref": runs.vehicle_id.astype(str),
        "aimed_utc": runs.aimed_utc,
        "trip_id": runs.trip_id,
        "line": runs.line,
        "service_date": runs.service_dt.dt.strftime("%Y-%m-%d"),
        "match_method": "archive_trip_id",     # trip id came from the archive, not matching
        "prev_day": False,
    })
    matched.to_parquet(os.path.join(a.out_dir, "runs_matched.parquet"), index=False)

    # ---- positions -> snapshot-like SQLite with the columns arrivals.py queries ------------
    pos = pos.merge(runs[["vehicle_id", "trip_id", "start_date", "aimed_utc"]],
                    on=["vehicle_id", "trip_id", "start_date"])
    snap = pd.DataFrame({
        "recorded_at": pd.to_datetime(pos.timestamp, unit="s", utc=True)
                         .dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "operator_ref": OPERATOR,
        "vehicle_ref": pos.vehicle_id.astype(str),
        "published_line_name": pos.line,
        "origin_aimed_departure_time": pos.aimed_utc.dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "latitude": pos.lat,
        "longitude": pos.lon,
    })
    db = os.path.join(a.out_dir, "archive_snapshot.sqlite")
    if os.path.exists(db):
        os.remove(db)
    con = sqlite3.connect(db)
    snap.to_sql("positions", con, index=False)
    con.execute("CREATE INDEX idx_pos_line ON positions(published_line_name)")
    con.commit()
    con.close()

    per_day = matched.groupby("service_date").size()
    print(f"\nruns per service day: min {per_day.min():,} | median {per_day.median():,.0f} | "
          f"max {per_day.max():,}")
    print(f"wrote {len(matched):,} runs -> {a.out_dir}/runs_matched.parquet")
    print(f"wrote {len(snap):,} positions -> {db}  ({time.time() - t0:.0f}s)")
    print("\nnext: python3 delay_engine/trip_matching/arrivals.py "
          f"--snapshot {db} --gtfs-dir {a.gtfs_dir} --out-dir {a.out_dir}")


if __name__ == "__main__":
    main()