"""Match each live bus run to one timetable trip_id.

A run = operator_ref + vehicle_ref + origin_aimed_departure_time.
Match key = line + first stop + scheduled departure (+ service runs that date).

Usage:
  python3 match_runs.py --snapshot snapshot.sqlite --out-dir out [--lines 42,43] [--tol 0]
Outputs in out-dir: runs_matched.parquet, runs_ambiguous.parquet, runs_unmatched.parquet
"""
import argparse
import sqlite3
from pathlib import Path
import pandas as pd

TZ = "Europe/London"
COLS = ["operator_ref", "vehicle_ref", "recorded_at", "published_line_name",
        "dated_vehicle_journey_ref", "data_frame_ref", "origin_ref",
        "origin_aimed_departure_time"]


def load_runs(snapshot, lines=None):
    q = f"SELECT {', '.join(COLS)} FROM positions " \
        "WHERE published_line_name IS NOT NULL AND published_line_name != '' " \
        "AND origin_aimed_departure_time IS NOT NULL AND origin_aimed_departure_time != ''"
    params = []
    if lines:
        q += f" AND published_line_name IN ({','.join('?' * len(lines))})"
        params = lines
    with sqlite3.connect(snapshot) as con:
        df = pd.read_sql(q, con, params=params)
    df["recorded_at"] = pd.to_datetime(
        df["recorded_at"], utc=True, format="ISO8601")
    df["aimed_utc"] = pd.to_datetime(
        df["origin_aimed_departure_time"], utc=True, format="ISO8601")
    runs = (df.groupby(["operator_ref", "vehicle_ref", "aimed_utc"], dropna=False)
              .agg(line=("published_line_name", "first"),
                   origin_ref=("origin_ref", "first"),
                   dated_ref=("dated_vehicle_journey_ref", "first"),
                   data_frame_ref=("data_frame_ref", "first"),
                   first_fix=("recorded_at", "min"),
                   last_fix=("recorded_at", "max"),
                   n_fixes=("recorded_at", "size"))
              .reset_index())
    runs["line"] = runs["line"].astype(str).str.strip()
    aimed_local = runs["aimed_utc"].dt.tz_convert(TZ)
    # service date: trust data_frame_ref, else local date (after-midnight trips belong to the previous day)
    sd = runs["data_frame_ref"].where(runs["data_frame_ref"].fillna(
        "") != "", aimed_local.dt.strftime("%Y-%m-%d"))
    runs["service_date"] = sd.astype(str).str[:10]
    midnight = pd.to_datetime(runs["service_date"])
    # seconds after local midnight of the service date (can exceed 86400, like GTFS)
    runs["dep_s"] = (aimed_local.dt.tz_localize(None) -
                     midnight).dt.total_seconds().round().astype(int)
    return runs


def match(runs, trip_starts, service_days, tol=0):
    dates = set(runs["service_date"])
    sd = service_days[service_days["date"].isin(dates)]
    trip_days = trip_starts.merge(sd, on="service_id").rename(
        columns={"date": "service_date"})
    cand = runs.reset_index(names="run_id").merge(
        trip_days, left_on=["line", "origin_ref", "service_date"],
        right_on=["route_short_name", "first_stop_id", "service_date"], how="inner")
    cand["gap_s"] = (cand["dep_s_x"] - cand["dep_s_y"]).abs()
    cand = cand[cand["gap_s"] <= tol]
    cand["dvj_match"] = (cand["dated_ref"].fillna(
        "") == cand["vehicle_journey_code"].fillna("x"))
    # best candidate per run: smallest time gap, then journey-code agreement
    cand = cand.sort_values(
        ["run_id", "gap_s", "dvj_match"], ascending=[True, True, False])
    n = cand.groupby("run_id")["trip_id"].transform("nunique")
    cand["n_candidates"] = n
    best = cand.drop_duplicates("run_id")
    # still ambiguous if the top two candidates tie on gap and journey-code agreement
    top = cand.groupby("run_id").head(2)
    tie = top.groupby("run_id").agg(g=("gap_s", "nunique"), d=(
        "dvj_match", "nunique"), k=("trip_id", "nunique"))
    ambiguous_ids = set(tie[(tie.k > 1) & (tie.g == 1) & (tie.d == 1)].index)
    matched = best[~best.run_id.isin(ambiguous_ids)]
    ambiguous = cand[cand.run_id.isin(ambiguous_ids)]
    um = runs.reset_index(names="run_id")
    um = um[~um.run_id.isin(best.run_id)].copy()
    um["reason"] = unmatched_reason(um, trip_starts, trip_days)
    return matched, ambiguous, um


def unmatched_reason(um, trip_starts, trip_days):
    lines = set(trip_starts.route_short_name)
    line_stop = set(zip(trip_starts.route_short_name,
                    trip_starts.first_stop_id))
    line_stop_day = set(zip(trip_days.route_short_name,
                        trip_days.first_stop_id, trip_days.service_date))
    out = []
    for l, o, d in zip(um.line, um.origin_ref, um.service_date):
        if l not in lines:
            out.append("line_not_in_timetable")
        elif (l, o) not in line_stop:
            out.append("origin_stop_not_a_trip_start_for_line")
        elif (l, o, d) not in line_stop_day:
            out.append("no_service_running_that_date")
        else:
            out.append("no_trip_at_that_departure_time")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--out-dir", default="out",
                    help="folder containing trip_starts/service_days parquet")
    ap.add_argument(
        "--lines", help="comma-separated line numbers, e.g. 42,43,50")
    ap.add_argument("--tol", type=int, default=0,
                    help="allowed seconds between aimed and scheduled departure")
    a = ap.parse_args()
    out = Path(a.out_dir)
    ts = pd.read_parquet(out / "trip_starts.parquet")
    sd = pd.read_parquet(out / "service_days.parquet")
    runs = load_runs(a.snapshot, a.lines.split(",") if a.lines else None)
    m, amb, um = match(runs, ts, sd, a.tol)
    m.to_parquet(out / "runs_matched.parquet", index=False)
    amb.to_parquet(out / "runs_ambiguous.parquet", index=False)
    um.to_parquet(out / "runs_unmatched.parquet", index=False)
    total = len(runs)
    print(f"runs: {total:,}")
    print(f"  matched   : {len(m):,} ({len(m)/total:.1%})")
    print(f"  ambiguous : {amb.run_id.nunique():,}")
    print(f"  unmatched : {len(um):,}")
    if len(um):
        print(um["reason"].value_counts().to_string())
