#!/usr/bin/env python3
"""
archive_to_inputs.py - feed the BODS archive through the team's arrivals.py, unchanged.

The archive (bods_archive/gm_YYYYMMDD.parquet) is GTFS-realtime vehicle positions:
    trip_id, route_id, start_date, start_time, lat, lon, bearing, timestamp, vehicle_id
Every position already carries its timetable trip_id, so matcher.py isn't needed. This script
writes exactly the two inputs arrivals.py reads, so archive and live delays come from the SAME code:

    <out-dir>/archive_snapshot.sqlite   table "positions", same columns arrivals.py queries
    <out-dir>/runs_matched.parquet      one row per run, same columns matcher.py writes
    <out-dir>/route_filter.csv          every candidate route and whether it was kept

Usage (from the project root):

    # every bus route in Greater Manchester (default)
    python3 delay_engine/trip_matching/archive_to_inputs.py \
        --archive bods_archive/ --gtfs-dir data/ --out-dir <dir> --from 20260830 --to 20260905

    # or only some route numbers
    ... --lines 42,43,50,142,143

    then:  python3 delay_engine/trip_matching/arrivals.py --snapshot <dir>/archive_snapshot.sqlite \
               --gtfs-dir data/ --out-dir <dir>

If no archive positions match the timetable (e.g. weeks before the timetable was valid), it still
writes EMPTY outputs and exits normally; check runs_matched.parquet has rows before running
arrivals.py (process_archive.py does this).

Which routes ("Greater Manchester" filter)
------------------------------------------
The North West GTFS also covers Warrington, Lancashire, Cheshire, Merseyside... and route numbers
are shared between towns (there's a Warrington "43" as well as a Manchester one). A route is kept
if at least half of its stops lie inside GM_OUTLINE, a rough outline of Greater Manchester.
Every decision is saved to route_filter.csv - check it if a route you expect is missing.
Override with --route-ids.

How runs are defined (so arrivals.py's join works):
    run          = one bus (vehicle_id) running one trip_id on one start_date
    operator_ref = the route's agency_id (fleet numbers are only unique within an operator)
    aimed_utc    = scheduled trip start in UTC = service-day start + start_time
                   (service day starts at local noon minus 12 h, same rule as arrivals.py)
The archive has at most one position per bus per minute; arrivals.py interpolates between
positions and its default --max-gap of 120 s still keeps normal 60 s gaps.
"""
import argparse
import glob
import os
import re
import sqlite3
import time

import numpy as np
import pandas as pd
import pyarrow.compute as pc
import pyarrow.parquet as pq

TZ = "Europe/London"

# Rough outline of Greater Manchester, (lon, lat), going round clockwise from Wigan.
# Deliberately generous at the edges; the key job is excluding Warrington (south-west),
# Lancashire (north-west), Cheshire (south) and the Pennines/Yorkshire (east).
GM_OUTLINE = np.array([
    (-2.73, 53.48),   # west of Wigan
    (-2.73, 53.62),   # north-west of Wigan
    (-2.45, 53.66),   # north of Bolton
    (-2.30, 53.69),   # north of Bury / Ramsbottom
    (-2.10, 53.69),   # north of Rochdale
    (-1.91, 53.62),   # Saddleworth
    (-1.95, 53.50),   # Mossley / Stalybridge
    (-2.00, 53.40),   # Marple
    (-2.10, 53.33),   # Hazel Grove
    (-2.28, 53.34),   # Manchester Airport
    (-2.43, 53.40),   # Partington
    (-2.45, 53.43),   # Irlam / Cadishead
    (-2.60, 53.46),   # Leigh / Golborne (Warrington is south of this edge)
])
MIN_SHARE_INSIDE = 0.5


def day_of(path):
    m = re.search(r"(\d{8})", os.path.basename(path))
    return m.group(1) if m else ""


def service_day_start_utc(dates):
    """Naive service dates -> UTC start of each service day (local noon minus 12 h)."""
    noon = (dates + pd.Timedelta(hours=12)).dt.tz_localize(TZ)
    return (noon - pd.Timedelta(hours=12)).dt.tz_convert("UTC")


def inside_outline(lon, lat, poly=GM_OUTLINE):
    """Ray-casting point-in-polygon test, vectorised over points."""
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    inside = np.zeros(len(lon), bool)
    xs, ys = poly[:, 0], poly[:, 1]
    j = len(poly) - 1
    for i in range(len(poly)):
        crosses = (ys[i] > lat) != (ys[j] > lat)
        x_at = (xs[j] - xs[i]) * (lat - ys[i]) / np.where(ys[j] != ys[i], ys[j] - ys[i], 1) + xs[i]
        inside ^= crosses & (lon < x_at)
        j = i
    return inside


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


def select_trips(gtfs_dir, lines, route_ids, report_path):
    """Pick the bus routes to analyse and return trip_id -> line, operator.

    lines=None means every route. Routes are kept if >= MIN_SHARE_INSIDE of their stops are in
    Greater Manchester (or if listed in route_ids). Writes the decision for every route to CSV."""
    routes = pd.read_parquet(os.path.join(gtfs_dir, "routes.parquet"))
    routes["route_id"] = routes.route_id.astype(str)
    routes["route_short_name"] = routes.route_short_name.astype(str).str.strip()
    if "route_type" in routes:                                   # 3 = bus
        routes = routes[routes.route_type.astype(str) == "3"]
    if "agency_id" not in routes:
        routes["agency_id"] = ""
    if lines:
        routes = routes[routes.route_short_name.isin(lines)]

    trips = pd.read_parquet(os.path.join(gtfs_dir, "trips.parquet"), columns=["trip_id", "route_id"])
    trips["route_id"] = trips.route_id.astype(str)
    trips = trips[trips.route_id.isin(set(routes.route_id))]

    # Distinct stops served by each route -> share inside Greater Manchester
    st = pq.read_table(os.path.join(gtfs_dir, "stop_times.parquet"), columns=["trip_id", "stop_id"])
    st = st.filter(pc.is_in(st["trip_id"], value_set=pa_array(trips.trip_id))).to_pandas()
    route_stops = st.merge(trips, on="trip_id")[["route_id", "stop_id"]].drop_duplicates()
    stops = pd.read_parquet(os.path.join(gtfs_dir, "stops.parquet"),
                            columns=["stop_id", "stop_lat", "stop_lon"])
    for c in ("stop_lat", "stop_lon"):
        stops[c] = pd.to_numeric(stops[c], errors="coerce")
    stops["in_gm"] = inside_outline(stops.stop_lon, stops.stop_lat)
    share = route_stops.merge(stops, on="stop_id").groupby("route_id").in_gm.mean()

    info = routes.set_index("route_id")[["agency_id", "route_short_name"]].copy()
    info["share_stops_in_gm"] = share
    info["trips"] = trips.groupby("route_id").size()
    info = info.fillna({"share_stops_in_gm": 0, "trips": 0})
    if route_ids:
        info["keep"] = info.index.isin(route_ids)
    else:
        info["keep"] = info.share_stops_in_gm >= MIN_SHARE_INSIDE
    info.sort_values(["keep", "route_short_name"]).to_csv(report_path)

    kept = info[info.keep]
    dropped = info[~info.keep & (info.trips > 0)]
    print(f"routes: {len(info):,} candidates -> {len(kept):,} kept in Greater Manchester, "
          f"{len(dropped):,} outside (details: {report_path})")
    if len(dropped) and lines:
        print("  dropped:", ", ".join(f"{r.route_short_name} ({i}, {r.agency_id})"
                                      for i, r in dropped.head(10).iterrows()))

    t = trips[trips.route_id.isin(set(kept.index))].merge(
        kept[["agency_id", "route_short_name"]], left_on="route_id", right_index=True)
    print(f"GTFS: {len(t):,} trips on {kept.route_short_name.nunique():,} route numbers")
    return t.rename(columns={"route_short_name": "line", "agency_id": "operator_ref"})[
        ["trip_id", "line", "operator_ref"]]


def pa_array(values):
    import pyarrow as pa
    return pa.array(list(values), type=pa.string())


def read_day(path, trip_set, trip_array):
    """One day's positions for our trips (empty-string trip ids never match, so they're dropped)."""
    cols = ["trip_id", "start_date", "start_time", "lat", "lon", "timestamp", "vehicle_id"]
    t = pq.read_table(path, columns=cols)
    t = t.filter(pc.is_in(t["trip_id"], value_set=trip_array))
    df = t.to_pandas()
    return df[df.lat.notna() & df.lon.notna()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default="bods_archive/", help="folder of gm_YYYYMMDD.parquet")
    ap.add_argument("--gtfs-dir", required=True,
                    help="folder with the GTFS .parquet tables (trips, routes, stops, stop_times)")
    ap.add_argument("--out-dir", default="delay_engine/trip_matching/out_archive")
    ap.add_argument("--lines", default="all",
                    help="'all' (every Greater Manchester bus route) or comma-separated numbers")
    ap.add_argument("--route-ids", default=None,
                    help="comma-separated route_ids to use instead of the Greater Manchester filter")
    ap.add_argument("--from", dest="date_from", default="00000000", help="YYYYMMDD")
    ap.add_argument("--to", dest="date_to", default="99999999", help="YYYYMMDD")
    a = ap.parse_args()
    lines = None if a.lines.strip().lower() == "all" else [x.strip() for x in a.lines.split(",")]
    route_ids = [x.strip() for x in a.route_ids.split(",")] if a.route_ids else None
    os.makedirs(a.out_dir, exist_ok=True)
    done = os.path.join(a.out_dir, "CONVERTER_DONE")
    if os.path.exists(done):
        os.remove(done)
    t0 = time.time()

    files = sorted(f for f in glob.glob(os.path.join(a.archive, "*.parquet"))
                   if a.date_from <= day_of(f) <= a.date_to)
    if not files:
        raise SystemExit(f"no parquet files in {a.archive} for that date range")

    trip_info = select_trips(a.gtfs_dir, lines, route_ids,
                             os.path.join(a.out_dir, "route_filter.csv"))
    trip_array = pa_array(set(trip_info.trip_id))

    # ---- one day at a time: positions go straight into SQLite, only the (small) run table is
    # kept in memory. Holding a whole week of the full network at once runs out of memory. ----
    db = os.path.join(a.out_dir, "archive_snapshot.sqlite")
    if os.path.exists(db):
        os.remove(db)
    con = sqlite3.connect(db)
    # Explicit column types (an empty-DataFrame CREATE would make latitude/longitude TEXT)
    con.execute("CREATE TABLE positions (recorded_at TEXT, operator_ref TEXT, vehicle_ref TEXT, "
                "published_line_name TEXT, origin_aimed_departure_time TEXT, "
                "latitude REAL, longitude REAL)")

    run_key = ["operator_ref", "vehicle_id", "trip_id", "start_date"]
    first_dep = {}                      # timetable first departures, fetched only if needed
    run_parts, n_pos, n_bad_total = [], 0, 0
    print(f"\n{'file':8s} {'positions':>10s} {'runs':>7s}")
    for f in files:
        d = read_day(f, None, trip_array)
        d = d.drop_duplicates(["vehicle_id", "timestamp"]).merge(trip_info, on="trip_id")

        # Runs seen today, with their scheduled start (UTC)
        r = d.drop_duplicates(run_key)[run_key + ["start_time", "line"]].copy()
        r["service_dt"] = pd.to_datetime(r.start_date, format="%Y%m%d", errors="coerce")
        start_s = hhmmss_to_s(r.start_time)
        bad = start_s.isna()
        if bad.any():
            need = set(r.trip_id[bad]) - set(first_dep)
            if need:
                first_dep.update(first_departures(a.gtfs_dir, need).to_dict())
            start_s = start_s.fillna(pd.to_numeric(r.trip_id.map(first_dep), errors="coerce"))
            n_bad_total += int(bad.sum())
        r = r[r.service_dt.notna() & start_s.notna()].copy()
        start_s = start_s[r.index]
        r["aimed_utc"] = (service_day_start_utc(r.service_dt)
                          + pd.to_timedelta(start_s.astype(float), unit="s"))
        run_parts.append(r[run_key + ["line", "service_dt", "aimed_utc"]])

        # Today's positions, in the columns arrivals.py queries
        d = d.merge(r[run_key + ["aimed_utc"]], on=run_key)
        snap = pd.DataFrame({
            "recorded_at": pd.to_datetime(d.timestamp, unit="s", utc=True)
                             .dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "operator_ref": d.operator_ref.astype(str),
            "vehicle_ref": d.vehicle_id.astype(str),
            "published_line_name": d.line,
            "origin_aimed_departure_time": d.aimed_utc.dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "latitude": d.lat,
            "longitude": d.lon,
        })
        snap.to_sql("positions", con, index=False, if_exists="append", chunksize=200_000)
        n_pos += len(snap)
        print(f"{day_of(f):8s} {len(snap):10,d} {len(r):7,d}"
              + ("   <- none of our trips: timetable mismatch?" if len(r) == 0 else ""),
              flush=True)
        del d, snap, r

    con.execute("CREATE INDEX idx_pos_line ON positions(published_line_name)")
    con.commit()
    con.close()
    if n_bad_total:
        print(f"\n{n_bad_total:,} runs had a blank/malformed start_time -> used the timetable's "
              "first departure")

    # ---- runs: one per (operator, vehicle, trip, service date) -> matcher.py's format -----
    runs = pd.concat(run_parts, ignore_index=True).drop_duplicates(run_key)
    runs = runs.sort_values(["service_dt", "aimed_utc", "operator_ref", "vehicle_id"]) \
        .reset_index(drop=True)
    matched = pd.DataFrame({
        "run_id": runs.index.astype("int64"),
        "operator_ref": runs.operator_ref.astype(str),
        "vehicle_ref": runs.vehicle_id.astype(str),
        "aimed_utc": runs.aimed_utc,
        "trip_id": runs.trip_id,
        "line": runs.line,
        "service_date": runs.service_dt.dt.strftime("%Y-%m-%d"),
        "match_method": "archive_trip_id",
        "prev_day": False,
    })
    matched.to_parquet(os.path.join(a.out_dir, "runs_matched.parquet"), index=False)
    # Completion marker: written LAST, so a run that was killed part-way is never reused
    with open(os.path.join(a.out_dir, "CONVERTER_DONE"), "w") as fh:
        fh.write(f"{len(matched)} runs, {n_pos} positions\n")

    if matched.empty:
        print("\nNo runs matched the timetable in this date range - wrote EMPTY outputs.")
        print("Skip arrivals.py for this range.")
        return
    per_day = matched.groupby("service_date").size()
    print(f"\nruns per service day: min {per_day.min():,} | median {per_day.median():,.0f} | "
          f"max {per_day.max():,}  | routes: {matched.line.nunique():,}")
    print(f"wrote {len(matched):,} runs -> {a.out_dir}/runs_matched.parquet")
    print(f"wrote {n_pos:,} positions -> {db}  ({time.time() - t0:.0f}s)")
    print("\nnext: python3 delay_engine/trip_matching/arrivals.py "
          f"--snapshot {db} --gtfs-dir {a.gtfs_dir} --out-dir {a.out_dir}")


if __name__ == "__main__":
    main()