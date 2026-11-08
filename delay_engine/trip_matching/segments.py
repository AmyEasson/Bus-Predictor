"""Step 4: aggregate stop arrivals into road segments (stop A -> next stop B).

For each run, every pair of consecutive stops that both have a clean arrival gives:
  delay_added_s  = delay at B - delay at A      (how much lateness this stretch added; + = lost time)
  travel_time_s  = actual arrival B - actual arrival A
  sched_time_s   = scheduled arrival B - scheduled arrival A
Pairs are grouped by (from_stop, to_stop, time_band) across all lines, plus an "all" band
that pools every time of day (more observations, so it is the better fallback when data is thin).

Time bands (local time of the scheduled arrival at stop A, by service-date weekday):
  weekday_am_peak 07:00-09:30 | weekday_interpeak 09:30-16:00 | weekday_pm_peak 16:00-18:30
  weekday_off_peak (other) | weekend (Sat/Sun)

Usage (from trip_matching/):
  python3 segments.py --gtfs-dir ../../data --out-dir out [--min-n 5]
Outputs: out/segments.parquet and out/segments.csv
"""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

TZ = "Europe/London"


def time_band(sched_utc, service_date):
    local = sched_utc.dt.tz_convert(TZ)
    h = local.dt.hour + local.dt.minute / 60
    weekend = pd.to_datetime(service_date).dt.day_of_week >= 5
    band = np.select(
        [weekend, (h >= 7) & (h < 9.5), (h >= 9.5) &
         (h < 16), (h >= 16) & (h < 18.5)],
        ["weekend", "weekday_am_peak", "weekday_interpeak", "weekday_pm_peak"],
        default="weekday_off_peak")
    return pd.Series(band, index=sched_utc.index)


def build_pairs(arr, max_added, max_travel, min_gap=150.0, min_sched=60.0):
    if "stop_idx" not in arr:
        raise SystemExit("stop_arrivals.parquet has no stop_idx column; re-run arrivals.py first")
    arr = arr.sort_values(["run_id", "stop_idx"]).reset_index(drop=True)
    nxt = arr.groupby("run_id").shift(-1)
    # only truly adjacent stops; stop_idx is contiguous even when stop_sequence has gaps
    ok = nxt["stop_idx"] == arr["stop_idx"] + 1
    p = pd.DataFrame({
        "run_id": arr.run_id, "line": arr.line,
        "from_stop_id": arr.stop_id, "to_stop_id": nxt.stop_id,
        "from_lat": arr.stop_lat, "from_lon": arr.stop_lon,
        "to_lat": nxt.stop_lat, "to_lon": nxt.stop_lon,
        "delay_added_s": nxt.delay_s - arr.delay_s,
        "travel_time_s": (nxt.actual_arr_utc - arr.actual_arr_utc).dt.total_seconds(),
        "sched_time_s": (nxt.sched_arr_utc - arr.sched_arr_utc).dt.total_seconds(),
        "sched_utc": arr.sched_arr_utc, "service_date": arr.service_date,
    })[ok].copy()
    n0 = len(p)
    p = p[(p.travel_time_s > 0) & (p.travel_time_s <= max_travel)]
    p = p[p.delay_added_s.abs() <= max_added]
    # short stretches and zero/one-minute scheduled gaps are dominated by timetable rounding (1-min resolution)
    dy = (p.to_lat - p.from_lat) * 110540.0
    dx = (p.to_lon - p.from_lon) * 111320.0 * np.cos(np.radians(p.from_lat))
    p["gap_m"] = np.hypot(dx, dy)
    p = p[(p.gap_m >= min_gap) & (p.sched_time_s >= min_sched)]
    p["time_band"] = time_band(p.sched_utc, p.service_date)
    return p, n0 - len(p)


def aggregate(p, min_n):
    both = pd.concat([p, p.assign(time_band="all")], ignore_index=True)
    key = ["from_stop_id", "to_stop_id", "time_band"]
    g = both.groupby(key)
    seg = g.agg(
        n=("run_id", "size"),
        n_lines=("line", "nunique"),
        lines=("line", lambda s: ",".join(sorted(set(s)))),
        median_delay_added_s=("delay_added_s", "median"),
        p90_delay_added_s=("delay_added_s", lambda s: s.quantile(0.9)),
        median_travel_s=("travel_time_s", "median"),
        median_sched_s=("sched_time_s", "median"),
        from_lat=("from_lat", "first"), from_lon=("from_lon", "first"),
        to_lat=("to_lat", "first"), to_lon=("to_lon", "first"),
    ).reset_index()
    seg["reliable"] = seg.n >= min_n
    return seg


def main(a):
    out = Path(a.out_dir)
    arr = pd.read_parquet(out / "stop_arrivals.parquet")
    p, dropped = build_pairs(arr, a.max_added, a.max_travel, a.min_gap, a.min_sched)
    seg = aggregate(p, a.min_n)

    st = pd.read_parquet(Path(a.gtfs_dir) / "stops.parquet",
                         columns=["stop_id", "stop_name"])
    names = st.drop_duplicates("stop_id").set_index("stop_id")["stop_name"]
    seg["from_name"] = seg.from_stop_id.map(names)
    seg["to_name"] = seg.to_stop_id.map(names)

    seg.to_parquet(out / "segments.parquet", index=False)
    seg.to_csv(out / "segments.csv", index=False)

    alls = seg[seg.time_band == "all"]
    print(f"stop pairs used: {len(p):,} (dropped {dropped:,} implausible) | segments (all-day): {len(alls):,} "
          f"| reliable (n>={a.min_n}): {int(alls.reliable.sum()):,}")
    print("pairs per time band:", p.time_band.value_counts().to_dict())
    top = alls[alls.reliable].sort_values(
        "median_delay_added_s", ascending=False).head(10)
    if len(top):
        print("\nTop segments by median delay added (reliable only):")
        print(top[["from_name", "to_name", "n", "lines", "median_delay_added_s", "p90_delay_added_s"]]
              .round(0).to_string(index=False))
    else:
        print(
            "\nNo segment has enough observations yet; lower --min-n or collect more data.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gtfs-dir", required=True)
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--min-n", type=int, default=5,
                    help="observations needed to call a segment reliable")
    ap.add_argument("--max-added", type=float, default=600,
                    help="drop pairs adding more than this many seconds")
    ap.add_argument("--max-travel", type=float, default=1800,
                    help="drop pairs taking longer than this (s)")
    ap.add_argument("--min-gap", type=float, default=150, help="drop stop pairs closer than this many metres")
    ap.add_argument("--min-sched", type=float, default=60, help="drop pairs with less scheduled time than this (s)")
    main(ap.parse_args())
