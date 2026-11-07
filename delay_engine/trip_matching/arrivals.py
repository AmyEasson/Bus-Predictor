"""Step 3: detect when each matched bus run reached each stop, and compute delay.

For every matched run we take its GPS fixes (time-ordered) and the stops of its trip
(in stop_sequence order). A stop counts as reached when the bus's path passes within
--radius metres of it. The arrival time is interpolated between the two fixes either
side of the closest approach, so a bus that "jumps" past a stop between two fixes is still caught.

  delay_s = actual arrival - scheduled arrival   (positive = late)

Cleaning is built in (counts printed at the end):
  - GPS jumps (implied speed > --max-speed) are removed before detection
  - runs with fewer than --min-fixes fixes are skipped
  - the first stop of each trip is skipped (buses waiting at the terminal look late)
  - arrivals interpolated across a fix gap > --max-gap seconds are dropped
  - arrivals earlier than the previous stop's arrival are dropped
  - delays outside [--min-delay, --max-delay] seconds are dropped

Usage (from trip_matching/):
  python3 arrivals.py --snapshot ../../snapshot.sqlite --gtfs-dir ../.. --out-dir out
Output: out/stop_arrivals.parquet
"""
import argparse
import sqlite3
from collections import Counter
from pathlib import Path
import numpy as np
import pandas as pd

TZ = "Europe/London"
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def to_seconds(ts):
    return (ts - EPOCH).dt.total_seconds().to_numpy()


def load_fixes(snapshot, matched):
    lines = sorted(matched["line"].unique())
    q = ("SELECT operator_ref, vehicle_ref, recorded_at, latitude, longitude, origin_aimed_departure_time "
         f"FROM positions WHERE published_line_name IN ({','.join('?' * len(lines))}) "
         "AND latitude IS NOT NULL AND longitude IS NOT NULL "
         "AND origin_aimed_departure_time IS NOT NULL AND origin_aimed_departure_time != ''")
    with sqlite3.connect(snapshot) as con:
        df = pd.read_sql(q, con, params=lines)
    df["t"] = to_seconds(pd.to_datetime(
        df["recorded_at"], utc=True, format="ISO8601"))
    df["aimed_utc"] = pd.to_datetime(
        df["origin_aimed_departure_time"], utc=True, format="ISO8601")
    df = df.merge(matched[["run_id", "operator_ref", "vehicle_ref", "aimed_utc"]],
                  on=["operator_ref", "vehicle_ref", "aimed_utc"])
    return df[["run_id", "t", "latitude", "longitude"]].sort_values(["run_id", "t"])


def remove_jumps(t, x, y, max_speed):
    """Drop fixes that imply an impossible speed from the previous kept fix."""
    keep = [0]
    for i in range(1, len(t)):
        j = keep[-1]
        dt = t[i] - t[j]
        if dt <= 0:
            continue  # duplicate timestamp
        if np.hypot(x[i] - x[j], y[i] - y[j]) / dt <= max_speed:
            keep.append(i)
    return np.array(keep)


def detect_run(fx, stops, radius, max_speed):
    """fx: fixes (t, latitude, longitude); stops: DataFrame sorted by stop_sequence.
    Returns list of (stop_row_index, arrival_t, min_dist, gap_s)."""
    lat0, lon0 = stops["stop_lat"].mean(), stops["stop_lon"].mean()
    ky, kx = 110540.0, 111320.0 * np.cos(np.radians(lat0))
    t = fx["t"].to_numpy()
    x = (fx["longitude"].to_numpy() - lon0) * kx
    y = (fx["latitude"].to_numpy() - lat0) * ky
    keep = remove_jumps(t, x, y, max_speed)
    t, x, y = t[keep], x[keep], y[keep]
    if len(t) < 2:
        return [], len(fx) - len(t)
    sx = (stops["stop_lon"].to_numpy() - lon0) * kx
    sy = (stops["stop_lat"].to_numpy() - lat0) * ky

    dx, dy = np.diff(x), np.diff(y)
    L2 = dx * dx + dy * dy
    wx, wy = sx[:, None] - x[None, :-1], sy[:, None] - y[None, :-1]
    u = np.where(L2 > 0, (wx * dx + wy * dy) / np.where(L2 > 0, L2, 1), 0.0)
    u = np.clip(u, 0, 1)
    dist = np.hypot(wx - u * dx, wy - u * dy)          # stops x segments

    out, start = [], 0
    for j in range(len(stops)):
        hit = np.nonzero(dist[j, start:] <= radius)[0]
        if hit.size == 0:
            # stop not reached (or fixes missed it)
            continue
        # first segment that comes within radius
        k = start + hit[0]
        gap = t[k + 1] - t[k]
        out.append((j, t[k] + u[j, k] * gap, dist[j, k], gap))
        # later stops must be reached at/after here
        start = k
    return out, len(fx) - len(t)


def main(a):
    out_dir = Path(a.out_dir)
    matched = pd.read_parquet(out_dir / "runs_matched.parquet")
    fixes = load_fixes(a.snapshot, matched)

    st = pd.read_parquet(Path(a.gtfs_dir) / "stop_times.parquet",
                         columns=["trip_id", "stop_sequence", "stop_id", "arr_s"])
    st = st[st.trip_id.isin(set(matched.trip_id))]
    stops = pd.read_parquet(Path(a.gtfs_dir) / "stops.parquet",
                            columns=["stop_id", "stop_lat", "stop_lon"])
    for c in ("stop_lat", "stop_lon"):
        stops[c] = pd.to_numeric(stops[c])
    st = st.merge(stops, on="stop_id").sort_values(
        ["trip_id", "stop_sequence"])
    trips = {k: g.reset_index(drop=True) for k, g in st.groupby("trip_id")}
    fixes_by_run = {k: g for k, g in fixes.groupby("run_id")}

    # GTFS times count from "noon minus 12 h" local, not midnight: on clock-change days
    # these differ by an hour. Subtracting 12 h from a tz-aware timestamp is absolute time.
    day_start = {d: (pd.Timestamp(d) + pd.Timedelta(hours=12)).tz_localize(TZ) - pd.Timedelta(hours=12)
                 for d in matched.service_date.unique()}
    day_start = {d: (s - EPOCH).total_seconds() for d, s in day_start.items()}

    drops, rows = Counter(), []
    for r in matched.itertuples(index=False):
        fx = fixes_by_run.get(r.run_id)
        ts = trips.get(r.trip_id)
        if fx is None or ts is None:
            drops["run_no_fixes_or_stops"] += 1
            continue
        if len(fx) < a.min_fixes:
            drops["run_too_few_fixes"] += 1
            continue
        hits, n_jump = detect_run(fx, ts, a.radius, a.max_speed)
        drops["gps_jump_fixes_removed"] += n_jump
        first_seq = ts["stop_sequence"].iloc[0]
        for j, arr_t, md, gap in hits:
            s = ts.iloc[j]
            sched = day_start[r.service_date] + float(s.arr_s)
            # j = position in the trip's sorted stop list (0, 1, 2, ...), always contiguous,
            # unlike stop_sequence which GTFS only guarantees to increase
            rows.append((r.run_id, r.operator_ref, r.vehicle_ref, r.trip_id, r.line, r.service_date,
                         r.match_method, bool(getattr(r, "prev_day", False)),
                         int(s.stop_sequence), j, s.stop_id, s.stop_lat, s.stop_lon,
                         sched, arr_t, arr_t - sched, md, gap, s.stop_sequence == first_seq))
        drops["stops_not_reached"] += len(ts) - len(hits)

    cols = ["run_id", "operator_ref", "vehicle_ref", "trip_id", "line", "service_date", "match_method",
            "prev_day", "stop_sequence", "stop_idx", "stop_id", "stop_lat", "stop_lon",
            "sched_t", "actual_t", "delay_s", "min_dist_m", "gap_s", "is_first_stop"]
    df = pd.DataFrame(rows, columns=cols)
    n0 = len(df)
    df = df[~df.is_first_stop]
    drops["first_stop_terminal"] += n0 - len(df)
    n = len(df)
    df = df[df.gap_s <= a.max_gap]
    drops["gap_too_large"] += n - len(df)
    # arrival must not be earlier than the previous stop's arrival on the same run
    df = df.sort_values(["run_id", "stop_sequence"])
    prev = df.groupby("run_id")["actual_t"].cummax().groupby(
        df["run_id"]).shift(1)
    n = len(df)
    df = df[~(df.actual_t < prev)]
    drops["out_of_order"] += n - len(df)
    n = len(df)
    df = df[df.delay_s.between(a.min_delay, a.max_delay)]
    drops["implausible_delay"] += n - len(df)

    df["sched_arr_utc"] = pd.to_datetime(df.sched_t, unit="s", utc=True)
    df["actual_arr_utc"] = pd.to_datetime(df.actual_t, unit="s", utc=True)
    df = df.drop(columns=["sched_t", "actual_t",
                 "is_first_stop"]).reset_index(drop=True)
    df.to_parquet(out_dir / "stop_arrivals.parquet", index=False)

    print(
        f"matched runs: {len(matched):,} | arrivals kept: {len(df):,} from {df.run_id.nunique():,} runs")
    print("dropped/removed:", dict(drops))
    if len(df):
        d = df.delay_s
        print(
            f"delay_s: median {d.median():.0f} | mean {d.mean():.0f} | p10 {d.quantile(.1):.0f} | p90 {d.quantile(.9):.0f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--gtfs-dir", required=True)
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--radius", type=float, default=50,
                    help="metres from stop that counts as reached")
    ap.add_argument("--max-gap", type=float, default=120,
                    help="drop arrivals interpolated over a bigger fix gap (s)")
    ap.add_argument("--min-fixes", type=int, default=5)
    ap.add_argument("--max-speed", type=float, default=35,
                    help="m/s; faster implied jumps are removed")
    ap.add_argument("--min-delay", type=float, default=-300)
    ap.add_argument("--max-delay", type=float, default=3600)
    main(ap.parse_args())
