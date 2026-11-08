"""Step 5: build stop arrivals and delays from the BODS archive (gm_YYYYMMDD.parquet).

The archive already gives each bus fix a timetable trip_id, so no matching step is needed:
a run = vehicle_id + trip_id + start_date. For each run we find when it reached each stop
(same detection and cleaning as arrivals.py) and compare with the scheduled arrival.

Scheduled times come from the timetable(s) you pass with --gtfs-dir. Pass it several times, most
relevant first; each trip_id is looked up in the first timetable that contains it, so older
timetable versions can be added later to recover trips that have since changed.

Output: one file per day, out-dir/arrivals_YYYYMMDD.parquet, plus out-dir/summary.csv.
Days that already have an output file are skipped (use --force to redo, e.g. for a day
that was still being written when you last ran it).

Usage (from trip_matching/):
  python3 archive_arrivals.py --archive-dir ../../data/bods_archive --gtfs-dir ../.. \\
      --out-dir out/archive_arrivals [--from 20260827] [--to 20261106] [--workers 4]
"""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
import pandas as pd

# same detection as the live-logger pipeline
from arrivals import detect_run, EPOCH, TZ

COLS = ["trip_id", "route_id", "start_date",
        "lat", "lon", "timestamp", "vehicle_id"]


def load_stops(gtfs_dirs):
    parts = [pd.read_parquet(Path(d) / "stops.parquet", columns=["stop_id", "stop_lat", "stop_lon"])
             for d in gtfs_dirs]
    s = pd.concat(parts).drop_duplicates("stop_id")
    for c in ("stop_lat", "stop_lon"):
        s[c] = pd.to_numeric(s[c], errors="coerce")
    return s.dropna()


def load_stop_times(gtfs_dirs, trip_ids):
    """Stop times for the given trips, taking each trip from the first timetable that has it."""
    out, remaining = [], set(trip_ids)
    for i, d in enumerate(gtfs_dirs):
        if not remaining:
            break
        st = pd.read_parquet(Path(d) / "stop_times.parquet",
                             columns=["trip_id", "stop_sequence",
                                      "stop_id", "arr_s"],
                             filters=[("trip_id", "in", sorted(remaining))])
        st["timetable_src"] = i
        out.append(st)
        remaining -= set(st.trip_id)
    if not out:
        return pd.DataFrame(columns=["trip_id", "stop_sequence", "stop_id", "arr_s", "timetable_src"])
    return pd.concat(out, ignore_index=True)


def process_day(path, gtfs_dirs, out_dir, p):
    day = Path(path).stem.split("_")[1]
    d = pd.read_parquet(path, columns=COLS)
    n_rows = len(d)
    d = d[d.trip_id != ""].drop_duplicates(
        ["vehicle_id", "trip_id", "timestamp"])
    d = d.rename(columns={"lat": "latitude", "lon": "longitude"})
    d["t"] = d["timestamp"].astype(float)
    d = d.sort_values(["vehicle_id", "trip_id", "start_date", "t"])

    st = load_stop_times(gtfs_dirs, d.trip_id.unique())
    st = st.merge(load_stops(gtfs_dirs), on="stop_id").sort_values(
        ["trip_id", "stop_sequence"])
    trips = {k: g.reset_index(drop=True) for k, g in st.groupby("trip_id")}

    midnight = {}
    drops, rows, n_runs, n_with_tt = Counter(), [], 0, 0
    for (veh, trip, sdate), fx in d.groupby(["vehicle_id", "trip_id", "start_date"], sort=False):
        n_runs += 1
        ts = trips.get(trip)
        if ts is None:
            drops["run_trip_not_in_timetable"] += 1
            continue
        n_with_tt += 1
        if len(fx) < p.min_fixes:
            drops["run_too_few_fixes"] += 1
            continue
        if sdate not in midnight:
            midnight[sdate] = ((pd.Timestamp(sdate) + pd.Timedelta(hours=12)).tz_localize(TZ) - EPOCH).total_seconds() - 12 * 3600
        hits, n_jump = detect_run(fx, ts, p.radius, p.max_speed)
        drops["gps_jump_fixes_removed"] += n_jump
        first_seq = ts["stop_sequence"].iloc[0]
        route = fx["route_id"].iloc[0]
        for j, arr_t, md, gap in hits:
            s = ts.iloc[j]
            sched = midnight[sdate] + float(s.arr_s)
            rows.append((f"{veh}|{trip}|{sdate}", veh, trip, route, sdate, int(s.stop_sequence), s.stop_id,
                         s.stop_lat, s.stop_lon, sched, arr_t, arr_t - sched, md, gap,
                         s.stop_sequence == first_seq, int(s.timetable_src)))
        drops["stops_not_reached"] += len(ts) - len(hits)

    cols = ["run_key", "vehicle_id", "trip_id", "route_id", "start_date", "stop_sequence", "stop_id",
            "stop_lat", "stop_lon", "sched_t", "actual_t", "delay_s", "min_dist_m", "gap_s",
            "is_first_stop", "timetable_src"]
    df = pd.DataFrame(rows, columns=cols)
    n0 = len(df)
    df = df[~df.is_first_stop]
    drops["first_stop_terminal"] += n0 - len(df)
    n = len(df)
    df = df[df.gap_s <= p.max_gap]
    drops["gap_too_large"] += n - len(df)
    df = df.sort_values(["run_key", "stop_sequence"])
    prev = df.groupby("run_key")["actual_t"].cummax().groupby(
        df["run_key"]).shift(1)
    n = len(df)
    df = df[~(df.actual_t < prev)]
    drops["out_of_order"] += n - len(df)
    n = len(df)
    df = df[df.delay_s.between(p.min_delay, p.max_delay)]
    drops["implausible_delay"] += n - len(df)

    df["sched_arr_utc"] = pd.to_datetime(df.sched_t, unit="s", utc=True)
    df["actual_arr_utc"] = pd.to_datetime(df.actual_t, unit="s", utc=True)
    df["hour_utc"] = df["actual_arr_utc"].dt.floor(
        "h")      # join key for context_hourly
    df = df.drop(columns=["sched_t", "actual_t",
                 "is_first_stop"]).reset_index(drop=True)
    df.to_parquet(Path(out_dir) / f"arrivals_{day}.parquet", index=False)
    return {"day": day, "fix_rows": n_rows, "runs": n_runs,
            "pct_runs_in_timetable": round(100 * n_with_tt / max(n_runs, 1), 1),
            "arrivals_kept": len(df), "median_delay_s": float(df.delay_s.median()) if len(df) else np.nan,
            **{k: v for k, v in drops.items()}}


def main(a):
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(Path(a.archive_dir).glob("gm_*.parquet"))
    files = [f for f in files if (not a.start or f.stem[3:] >= a.start) and (
        not a.end or f.stem[3:] <= a.end)]
    todo = [f for f in files if a.force or not (
        out / f"arrivals_{f.stem[3:]}.parquet").exists()]
    print(f"{len(files)} archive days in range, {len(todo)} to process")
    summ_path = out / "summary.csv"
    summaries = []
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(process_day, str(f), a.gtfs_dir, str(out), a)
                for f in todo]
        for f, fut in zip(todo, futs):
            s = fut.result()
            summaries.append(s)
            print(f"  {s['day']}: {s['runs']:,} runs ({s['pct_runs_in_timetable']}% in timetable) "
                  f"-> {s['arrivals_kept']:,} arrivals, median delay {s['median_delay_s']:.0f}s")
    if summaries:
        new = pd.DataFrame(summaries)
        if summ_path.exists():
            old = pd.read_csv(summ_path, dtype={"day": str})
            new = pd.concat([old[~old.day.isin(new.day)], new],
                            ignore_index=True)
        new.sort_values("day").to_csv(summ_path, index=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive-dir", required=True,
                    help="folder with gm_YYYYMMDD.parquet")
    ap.add_argument("--gtfs-dir", action="append", required=True,
                    help="timetable folder (stop_times/stops parquet); repeat for older versions")
    ap.add_argument("--out-dir", default="out/archive_arrivals")
    ap.add_argument("--from", dest="start", help="first day, YYYYMMDD")
    ap.add_argument("--to", dest="end", help="last day, YYYYMMDD")
    ap.add_argument("--workers", type=int, default=1,
                    help="days processed in parallel")
    ap.add_argument("--force", action="store_true",
                    help="redo days that already have output")
    ap.add_argument("--radius", type=float, default=50)
    ap.add_argument("--max-gap", type=float, default=120)
    ap.add_argument("--min-fixes", type=int, default=5)
    ap.add_argument("--max-speed", type=float, default=35)
    ap.add_argument("--min-delay", type=float, default=-300)
    ap.add_argument("--max-delay", type=float, default=3600)
    main(ap.parse_args())
