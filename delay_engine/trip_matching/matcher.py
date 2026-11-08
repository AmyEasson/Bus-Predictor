"""Step 2: match each live bus run to one timetable trip_id.

A run = operator_ref + vehicle_ref + origin_aimed_departure_time.
Three passes, strongest first. Each result records match_method:
  1 journey_ref : live dated_vehicle_journey_ref == trip vehicle_journey_code,
                  same line + service date, scheduled time within --jtol seconds, and unique
  2 exact       : same line + origin stop + service date, scheduled time within --tol seconds
  3 fallback    : same line + service date (+ direction if known), closest scheduled
                  departure within --ftol seconds, only if there is a clear single winner

Usage:
  python3 matcher.py --snapshot ../../data/snapshot.sqlite --out-dir out [--lines 42,43] [--tol 0] [--jtol 120] [--ftol 300]
Outputs in out-dir: runs_matched.parquet, runs_ambiguous.parquet, runs_unmatched.parquet
"""
import argparse
import sqlite3
from pathlib import Path
import pandas as pd

TZ = "Europe/London"
# checked against matched runs: 79/79 and 60/60
DIRECTION_MAP = {"outbound": "0", "inbound": "1"}
COLS = ["operator_ref", "vehicle_ref", "recorded_at", "published_line_name",
        "dated_vehicle_journey_ref", "data_frame_ref", "origin_ref",
        "origin_aimed_departure_time", "direction_ref"]


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
                   direction_ref=("direction_ref", "first"),
                   first_fix=("recorded_at", "min"),
                   last_fix=("recorded_at", "max"),
                   n_fixes=("recorded_at", "size"))
              .reset_index())
    runs["line"] = runs["line"].astype(str).str.strip()
    aimed_local = runs["aimed_utc"].dt.tz_convert(TZ)
    # service date: trust data_frame_ref if it is a real date, else local date of the aimed departure
    ok = runs["data_frame_ref"].fillna("").str[:4] >= "2000"
    sd = runs["data_frame_ref"].where(ok, aimed_local.dt.strftime("%Y-%m-%d"))
    runs["service_date"] = sd.astype(str).str[:10]
    midnight = pd.to_datetime(runs["service_date"])
    # seconds after local midnight of the service date (can exceed 86400, like GTFS)
    runs["dep_s"] = (aimed_local.dt.tz_localize(None) -
                     midnight).dt.total_seconds().round().astype(int)
    runs["dir_id"] = runs["direction_ref"].map(
        DIRECTION_MAP)   # None for clockwise / missing
    return runs


def pick(cand):
    """Best candidate per run; runs whose top two candidates tie are returned as ambiguous."""
    if cand.empty:
        return cand, cand
    cand = cand.sort_values(
        ["run_id", "gap_s", "dvj_match"], ascending=[True, True, False])
    cand["n_candidates"] = cand.groupby(
        "run_id")["trip_id"].transform("nunique")
    best = cand.drop_duplicates("run_id")
    top = cand.groupby("run_id").head(2)
    tie = top.groupby("run_id").agg(g=("gap_s", "nunique"), d=(
        "dvj_match", "nunique"), k=("trip_id", "nunique"))
    amb_ids = set(tie[(tie.k > 1) & (tie.g == 1) & (tie.d == 1)].index)
    return best[~best.run_id.isin(amb_ids)], cand[cand.run_id.isin(amb_ids)]


def with_gap(cand):
    cand["gap_s"] = (cand["dep_s"] - cand["sched_dep_s"]).abs()
    cand["dvj_match"] = cand["dated_ref"].fillna(
        "") == cand["vehicle_journey_code"].fillna("\x00")
    return cand


def run_passes(runs, trip_days, tol, jtol, ftol):
    """Journey-ref, exact, then fallback pass. Returns (matched, ambiguous, left_over_runs)."""
    matched, ambiguous = [], []

    # pass 1: journey ref
    r1 = runs[runs.dated_ref.fillna("") != ""]
    c1 = r1.merge(trip_days, left_on=["line", "service_date", "dated_ref"],
                  right_on=["route_short_name", "service_date", "vehicle_journey_code"])
    c1 = with_gap(c1)
    c1 = c1[c1.gap_s <= jtol]
    # journey codes are only unique per operator, so require exactly one trip left
    c1 = c1[c1.groupby("run_id")["trip_id"].transform("nunique") == 1]
    # the uniqueness filter above guarantees pick() never produces ambiguous rows here
    b1, _ = pick(c1)
    matched.append(b1.assign(match_method="journey_ref"))
    left = runs[~runs.run_id.isin(b1.run_id)]

    # pass 2: exact line + origin stop + date + time
    c2 = left.merge(trip_days, left_on=["line", "origin_ref", "service_date"],
                    right_on=["route_short_name", "first_stop_id", "service_date"])
    c2 = with_gap(c2)
    # tol=0 by default (exact second match); raise to ~60 s if pass-2 match rates look low,
    # e.g. if the live feed rounds aimed times to the minute but the timetable has odd seconds
    c2 = c2[c2.gap_s <= tol]
    b2, a2 = pick(c2)
    matched.append(b2.assign(match_method="exact"))
    ambiguous.append(a2.assign(match_method="exact"))
    left = left[~left.run_id.isin(set(b2.run_id) | set(a2.run_id))]

    # pass 3: fallback on line + date + direction, closest scheduled time
    c3 = left.merge(trip_days, left_on=["line", "service_date"],
                    right_on=["route_short_name", "service_date"])
    c3 = c3[c3.dir_id.isna() | (c3.dir_id == c3.direction_id)]
    c3 = with_gap(c3)
    c3 = c3[c3.gap_s <= ftol]
    b3, a3 = pick(c3)
    matched.append(b3.assign(match_method="fallback"))
    ambiguous.append(a3.assign(match_method="fallback"))
    left = left[~left.run_id.isin(set(b3.run_id) | set(a3.run_id))]
    return pd.concat(matched, ignore_index=True), pd.concat(ambiguous, ignore_index=True), left


def match(runs, trip_starts, service_days, tol=0, jtol=120, ftol=300, early_s=5 * 3600):
    dates = set(runs["service_date"])
    prev = set((pd.to_datetime(list(dates)) -
               pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
    sd = service_days[service_days["date"].isin(dates | prev)]
    trip_days = (trip_starts.rename(columns={"dep_s": "sched_dep_s"})
                 .merge(sd, on="service_id").rename(columns={"date": "service_date"}))
    runs = runs.reset_index(drop=True).rename_axis("run_id").reset_index()

    m, amb, left = run_passes(runs, trip_days, tol, jtol, ftol)
    m["prev_day"] = False

    # retry: early-morning leftovers may be after-midnight trips of the PREVIOUS service day
    # (GTFS writes them as 24:xx, 25:xx), while the live feed labels them with the calendar date
    early = left[left.dep_s < early_s].copy()
    if len(early):
        early["service_date"] = (pd.to_datetime(
            early["service_date"]) - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
        early["dep_s"] = early["dep_s"] + 86400
        m2, amb2, _ = run_passes(early, trip_days, tol, jtol, ftol)
        m2["prev_day"] = True
        m = pd.concat([m, m2], ignore_index=True)
        amb = pd.concat([amb, amb2], ignore_index=True)
        left = left[~left.run_id.isin(set(m2.run_id) | set(amb2.run_id))]

    um = left.copy()
    um["reason"] = unmatched_reason(um, trip_starts, trip_days)
    return m, amb, um


def unmatched_reason(um, trip_starts, trip_days):
    # diagnostic only — Python loop is fine since this runs once on the leftover set
    lines = set(trip_starts.route_short_name)
    line_day = set(zip(trip_days.route_short_name, trip_days.service_date))
    out = []
    for l, d in zip(um.line, um.service_date):
        if l not in lines:
            out.append("line_not_in_timetable")
        elif (l, d) not in line_day:
            out.append("no_service_running_that_date")
        else:
            out.append("no_trip_within_time_window")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--out-dir", default="out",
                    help="folder containing trip_starts/service_days parquet")
    ap.add_argument(
        "--lines", help="comma-separated line numbers, e.g. 42,43,50")
    ap.add_argument("--tol", type=int, default=0,
                    help="exact pass: allowed seconds off the scheduled departure")
    ap.add_argument("--jtol", type=int, default=120,
                    help="journey-ref pass: allowed seconds off")
    ap.add_argument("--ftol", type=int, default=300,
                    help="fallback pass: allowed seconds off")
    a = ap.parse_args()
    out = Path(a.out_dir)
    ts = pd.read_parquet(out / "trip_starts.parquet")
    sd = pd.read_parquet(out / "service_days.parquet")
    runs = load_runs(a.snapshot, a.lines.split(",") if a.lines else None)
    m, amb, um = match(runs, ts, sd, a.tol, a.jtol, a.ftol)
    m.to_parquet(out / "runs_matched.parquet", index=False)
    amb.to_parquet(out / "runs_ambiguous.parquet", index=False)
    um.to_parquet(out / "runs_unmatched.parquet", index=False)
    total = len(runs)
    print(f"runs: {total:,}")
    print(f"  matched   : {len(m):,} ({len(m)/total:.1%})")
    if len(m):
        print("    " + m.match_method.value_counts().to_string().replace("\n", "\n    "))
    print(
        f"    (of which previous-day after-midnight trips: {int(m.prev_day.sum())})")
    print(f"  ambiguous : {amb.run_id.nunique():,}")
    print(f"  unmatched : {len(um):,}")
    if len(um):
        print(um["reason"].value_counts().to_string())
