"""Step 6: enrich the daily archive arrivals with context, event proximity and per-stretch delay.

Reads  out/archive_arrivals/arrivals_YYYYMMDD.parquet   (from archive_arrivals.py)
       context_hourly.parquet                            (weather, calendar, city-wide event flag)
       events.csv                                        (venues, times, attendance)
Writes out/analysis/analysis_YYYYMMDD.parquet, one row per stop arrival:

  delay_s            lateness at this stop (cumulative along the trip)
  delay_added_s      delay at this stop minus delay at the previous stop = lateness gained on that
                     stretch. NaN unless the previous stop is the adjacent one and the pair passes the
                     same quality filters as segments.py (>=150 m apart, >=60 s scheduled, ...)
  seg_hash           id of the stretch (previous stop -> this stop), for grouping
  context columns   hour, weekday, is_weekend, is_rush, is_bank_holiday, is_school_term,
                     precipitation, temperature_2m, wind_speed_10m  (joined on the arrival's UTC hour)
  venue_nearest, venue_dist_km   nearest of the venues in events.csv to this stop (always filled)
  ev_*               the nearest ACTIVE event for this arrival, if any event is on (from --pre-h before
                     kick-off to --post-h after the end): ev_dist_km, ev_phase (pre/during/post),
                     ev_venue, ev_type, ev_attendance. All empty when no event is active.

Usage (from delay_engine/):
  python3 archival_data/build_analysis.py --arrivals-dir trip_matching/out/archive_arrivals \\
      --context PATH/context_hourly.parquet --events PATH/events.csv \\
      --out-dir trip_matching/out/analysis [--workers 4]
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
import pandas as pd

EPOCH = pd.Timestamp("1970-01-01", tz="UTC")
CTX_COLS = ["hour_utc", "weekday", "is_weekend", "hour", "is_rush", "is_bank_holiday", "is_school_term",
            "precipitation", "temperature_2m", "wind_speed_10m", "event_active", "event_attendance"]


def to_utc(s):
    s = pd.to_datetime(s)
    return s.dt.tz_localize("UTC") if s.dt.tz is None else s.dt.tz_convert("UTC")


def secs(s):
    return (to_utc(s) - EPOCH).dt.total_seconds().to_numpy()


def km(lat1, lon1, lat2, lon2):
    dy = (lat2 - lat1) * 110.54
    dx = (lon2 - lon1) * 111.32 * np.cos(np.radians((lat1 + lat2) / 2))
    return np.hypot(dx, dy)


def load_context(path):
    c = pd.read_parquet(path)
    c = c[CTX_COLS].copy()
    c["hkey"] = secs(c["hour_utc"]).astype("int64")
    return c.drop(columns="hour_utc").rename(columns={"event_active": "ctx_event_active",
                                                      "event_attendance": "ctx_event_attendance"})


def load_events(path):
    e = pd.read_csv(path)
    e["s"] = secs(e["start_utc"])
    e["e"] = secs(e["end_utc"])
    return e


def process_day(path, ctx_path, events_path, out_dir, a):
    day = Path(path).stem.split("_")[1]
    ctx, ev = load_context(ctx_path), load_events(events_path)
    d = pd.read_parquet(path).sort_values(
        ["run_key", "stop_sequence"]).reset_index(drop=True)
    d["actual_t"] = secs(d["actual_arr_utc"])
    d["sched_t"] = secs(d["sched_arr_utc"])

    # --- delay added on the stretch from the previous stop --------------------------------------
    g = d.groupby("run_key", sort=False)
    prev = {c: g[c].shift(1) for c in ["stop_sequence", "stop_id", "stop_lat", "stop_lon", "delay_s",
                                       "actual_t", "sched_t"]}
    travel = d.actual_t - prev["actual_t"]
    sched = d.sched_t - prev["sched_t"]
    added = d.delay_s - prev["delay_s"]
    gap_m = km(prev["stop_lat"], prev["stop_lon"],
               d.stop_lat, d.stop_lon) * 1000
    ok = ((d.stop_sequence - prev["stop_sequence"]) == 1) & (travel > 0) & (travel <= a.max_travel) \
        & (added.abs() <= a.max_added) & (gap_m >= a.min_gap) & (sched >= a.min_sched)
    d["delay_added_s"] = added.where(ok)
    d["travel_time_s"] = travel.where(ok)
    d["sched_time_s"] = sched.where(ok)
    d["seg_gap_m"] = gap_m.where(ok)
    seg = (prev["stop_id"].astype(str) + ">" +
           d["stop_id"].astype(str)).to_numpy(dtype=object)
    d["seg_hash"] = pd.util.hash_array(seg)

    # --- hourly context ---------------------------------------------------------------------------
    d["hkey"] = secs(d["hour_utc"]).astype("int64")
    d = d.merge(ctx, on="hkey", how="left").drop(columns="hkey")

    # --- nearest venue (always) and nearest active event (when one is on) -----------------------
    venues = ev.drop_duplicates(
        "venue")[["venue", "lat", "lon"]].reset_index(drop=True)
    stops = d[["stop_id", "stop_lat", "stop_lon"]].drop_duplicates(
        "stop_id").reset_index(drop=True)
    dist = np.stack([km(stops.stop_lat.to_numpy(), stops.stop_lon.to_numpy(), v.lat, v.lon)
                     for v in venues.itertuples()], axis=1)
    stops["venue_nearest"] = venues.venue.to_numpy()[dist.argmin(axis=1)]
    stops["venue_dist_km"] = dist.min(axis=1)
    d = d.merge(stops[["stop_id", "venue_nearest",
                "venue_dist_km"]], on="stop_id", how="left")

    t = d.actual_t.to_numpy()
    n = len(d)
    ev_dist = np.full(n, np.nan)
    ev_att = np.full(n, np.nan)
    ev_phase = np.full(n, None, dtype=object)
    ev_venue = np.full(n, None, dtype=object)
    ev_type = np.full(n, None, dtype=object)
    pre, post = a.pre_h * 3600, a.post_h * 3600
    for e in ev.itertuples():
        if e.e + post < t.min() or e.s - pre > t.max():
            continue
        dd = km(d.stop_lat.to_numpy(), d.stop_lon.to_numpy(), e.lat, e.lon)
        inwin = (t >= e.s - pre) & (t <= e.e + post)
        better = inwin & (np.isnan(ev_dist) | (dd < ev_dist))
        ev_dist[better] = dd[better]
        ev_att[better] = e.expected_attendance
        ev_phase[better] = np.where(t[better] < e.s, "pre", np.where(
            t[better] <= e.e, "during", "post"))
        ev_venue[better] = e.venue
        ev_type[better] = e.type
    d["ev_dist_km"], d["ev_attendance"] = ev_dist, ev_att
    d["ev_phase"], d["ev_venue"], d["ev_type"] = ev_phase, ev_venue, ev_type

    keep = ["run_key", "route_id", "start_date", "stop_sequence", "stop_id", "stop_lat", "stop_lon",
            "actual_arr_utc", "hour_utc", "delay_s", "delay_added_s", "travel_time_s", "sched_time_s",
            "seg_gap_m", "seg_hash", "weekday", "is_weekend", "hour", "is_rush", "is_bank_holiday",
            "is_school_term", "precipitation", "temperature_2m", "wind_speed_10m", "ctx_event_active",
            "ctx_event_attendance", "venue_nearest", "venue_dist_km", "ev_dist_km", "ev_phase",
            "ev_venue", "ev_type", "ev_attendance"]
    out = d[keep].copy()
    for c in ["delay_s", "delay_added_s", "travel_time_s", "sched_time_s", "seg_gap_m", "venue_dist_km",
              "ev_dist_km", "precipitation", "temperature_2m", "wind_speed_10m"]:
        out[c] = out[c].astype("float32")
    for c in ["venue_nearest", "ev_phase", "ev_venue", "ev_type", "route_id"]:
        out[c] = out[c].astype("category")
    out.to_parquet(Path(out_dir) / f"analysis_{day}.parquet", index=False)
    return day, len(out), int(out.delay_added_s.notna().sum()), int(out.ev_phase.notna().sum()), \
        float(out.hour.isna().mean())


def main(a):
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(Path(a.arrivals_dir).glob("arrivals_*.parquet"))
    todo = [f for f in files if a.force or not (
        out / f"analysis_{f.stem.split('_')[1]}.parquet").exists()]
    print(f"{len(files)} arrival days, {len(todo)} to process")
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(process_day, str(f), a.context,
                          a.events, str(out), a) for f in todo]
        for fut in futs:
            day, n, n_seg, n_ev, miss = fut.result()
            print(f"  {day}: {n:,} arrivals | {n_seg:,} usable stretches | {n_ev:,} in an event window "
                  f"| {miss:.1%} without context")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--arrivals-dir", required=True)
    ap.add_argument("--context", required=True, help="context_hourly.parquet")
    ap.add_argument("--events", required=True, help="events.csv")
    ap.add_argument("--out-dir", default="out/analysis")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--pre-h", type=float, default=2,
                    help="hours before kick-off counted as the event window")
    ap.add_argument("--post-h", type=float, default=2,
                    help="hours after the end counted as the event window")
    ap.add_argument("--max-added", type=float, default=600)
    ap.add_argument("--max-travel", type=float, default=1800)
    ap.add_argument("--min-gap", type=float, default=150)
    ap.add_argument("--min-sched", type=float, default=60)
    main(ap.parse_args())
