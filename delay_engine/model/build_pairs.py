#!/usr/bin/env python3
"""
build_pairs.py - turn stop_arrivals into training examples for the delay model.

The question the model answers:
    "A bus is at stop i right now, D seconds late. How late will it be at stop j further along?"

Every observed run gives many examples: each pair of stops (i, j) on the same run with j after i,
up to MAX_STOPS_AHEAD apart. Target = delay at j. Features = what you'd know at stop i
(see features.py).

Usage (from the project root):
    python3 delay_engine/model/build_pairs.py
    python3 delay_engine/model/build_pairs.py --arrivals delay_engine/trip_matching/out/stop_arrivals.parquet --context context/ \
        --out delay_engine/model/out/pairs.parquet

Context (from the context teammate) is read from --context if present:
    context_hourly.parquet  weather, school term, bank holiday, city-wide events (per hour)
    events.csv              individual events with venue location (for "event near this stop")
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as F  # noqa: E402

import numpy as np  # noqa: E402

MAX_STOPS_AHEAD = 15     # predict up to 15 stops ahead (~15-25 min on a city route)
MAX_PAIRS = 2_000_000    # cap on training examples: weeks of archive data would otherwise give
                         # tens of millions of pairs and run out of memory. A random sample of
                         # 2M covers every route, stop, hour and day type many times over.
RUN_CHUNK = 2_000        # build pairs this many runs at a time to keep memory flat


def count_pairs(run_lengths):
    """Exact number of pairs make_pairs would create, so we know how much to sample."""
    n = np.asarray(run_lengths)
    total = 0
    for ahead in range(1, MAX_STOPS_AHEAD + 1):
        total += np.clip(n - ahead, 0, None).sum()
    return int(total)


def make_pairs(sa, max_pairs=MAX_PAIRS, seed=0):
    """(i, j) stop pairs within each run, j after i, at most MAX_STOPS_AHEAD apart.

    Built RUN_CHUNK runs at a time; if the total would exceed max_pairs, each chunk is randomly
    sampled down by the same fraction, so the sample is spread evenly over the whole period."""
    # Terminus stops are unreliable (waiting / padded schedules): never use them as start or target
    sa = sa[(sa.is_first_stop == 0) & (sa.is_last_stop == 0)].copy()
    sa["k"] = sa.groupby("run_id").cumcount()          # 0, 1, 2... along each run

    total = count_pairs(sa.groupby("run_id").size())
    frac = min(1.0, max_pairs / max(total, 1))
    if frac < 1:
        print(f"pairs available: {total:,} -> sampling {frac:.1%} (cap {max_pairs:,})")
    rng = np.random.default_rng(seed)

    runs = sa.run_id.unique()
    parts = []
    for i in range(0, len(runs), RUN_CHUNK):
        chunk = sa[sa.run_id.isin(runs[i:i + RUN_CHUNK])]
        p = _pairs_for(chunk)
        if frac < 1:
            p = p[rng.random(len(p)) < frac]
        parts.append(p)
    return pd.concat(parts, ignore_index=True)


def _pairs_for(sa):

    left = sa[["run_id", "k", "route_short_name", "direction_id", "stop_id", "actual_utc",
               "scheduled_utc", "delay_s", "gap_ahead_s", "headway_ratio"]] \
        .rename(columns={"stop_id": "from_stop", "actual_utc": "now_utc",
                         "scheduled_utc": "sched_from", "delay_s": "delay_now_s",
                         "route_short_name": "route", "direction_id": "direction"})
    right = sa[["run_id", "k", "stop_id", "scheduled_utc", "actual_utc", "delay_s",
                "stop_lat", "stop_lon"]] \
        .rename(columns={"k": "k_to", "stop_id": "to_stop", "scheduled_utc": "sched_to",
                         "actual_utc": "actual_to", "delay_s": "target_delay_s",
                         "stop_lat": "to_lat", "stop_lon": "to_lon"})

    p = left.merge(right, on="run_id")
    p = p[(p.k_to > p.k) & (p.k_to - p.k <= MAX_STOPS_AHEAD)].copy()
    p["stops_ahead"] = p.k_to - p.k
    p["sched_travel_s"] = (p.sched_to - p.sched_from).dt.total_seconds()
    return p.drop(columns=["k", "k_to", "sched_from"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arrivals", default="delay_engine/trip_matching/out/stop_arrivals.parquet",
                    help="arrivals.py output (.parquet), or compute_delays.py output (.sqlite)")
    ap.add_argument("--gtfs", default="gtfs/", help="GTFS folder (for direction, stop names, last stops)")
    ap.add_argument("--context", default="context/")
    ap.add_argument("--out", default="delay_engine/model/out/pairs.parquet")
    ap.add_argument("--max-pairs", type=int, default=MAX_PAIRS,
                    help="cap on training examples (lower it if memory runs out)")
    a = ap.parse_args()

    # Remove any old output first, so a crash later can never leave a stale file for train.py
    if os.path.exists(a.out):
        os.remove(a.out)

    sa = F.load_stop_arrivals(a.arrivals, a.gtfs)
    print(f"stop arrivals: {len(sa):,}  runs: {sa.run_id.nunique():,}  "
          f"from {sa.actual_utc.min()} to {sa.actual_utc.max()}")

    p = make_pairs(sa, a.max_pairs)
    print(f"pairs: {len(p):,}")

    # Feature groups (see features.py)
    p = F.add_time_features(p, "now_utc")
    p = F.add_live_features(p, sa, "now_utc")
    p = F.add_hourly_context(p, F.load_context_hourly(
        os.path.join(a.context, "context_hourly.parquet")), "now_utc")
    p = F.add_events(p, F.load_events(os.path.join(a.context, "events.csv")), "now_utc")

    # Report which optional context made it in, so nobody trains on silently-empty features
    for name, cols in [("weather", F.WEATHER), ("calendar", F.CALENDAR),
                       ("events", ["event_active"]), ("live", F.LIVE)]:
        filled = p[cols].notna().mean().mean()
        extra = ""
        if name == "events":
            extra = (f", {int((p.event_active == 1).sum()):,} pairs during a city event, "
                     f"{int(p.event_nearby.sum()):,} near the venue")
        print(f"  {name:9s}: {filled:.0%} filled{extra}")

    # Halve memory/disk: 32-bit floats are plenty for seconds, metres and degrees
    for c in p.select_dtypes("float64").columns:
        p[c] = p[c].astype("float32")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    p.to_parquet(a.out, index=False)
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()