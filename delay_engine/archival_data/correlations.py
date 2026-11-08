"""Step 7: first-pass correlations between delay and context (rain, holidays, events).

Fair comparison: every stretch has its own normal. For each observation we compute
    excess = delay_added_s - median delay_added_s of the SAME stretch at the SAME hour of day
             on the same kind of day (weekday/weekend)
so that a busy city-centre stretch isn't blamed for being busy, only for being worse than usual.
Tables show the average excess under each condition (positive = slower than that stretch's normal).

Usage (from delay_engine/):
  python3 archival_data/correlations.py --analysis-dir trip_matching/out/analysis \\
      --out-dir trip_matching/out/correlations [--sample 0.3] [--venue-km 1.5]
"""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

COLS = ["seg_hash", "delay_added_s", "is_weekend", "hour", "precipitation", "is_bank_holiday",
        "is_school_term", "ev_dist_km", "ev_phase", "ev_venue", "ev_type", "venue_dist_km", "venue_nearest"]


def summarize(df, by):
    g = df.groupby(by, observed=True)["excess"]
    t = g.agg(n="size", mean_excess_s="mean",
              median_excess_s="median", sd="std")
    t["ci95_s"] = 1.96 * t["sd"] / np.sqrt(t["n"])
    return t.drop(columns="sd").round(1)


def main(a):
    parts = []
    for f in sorted(Path(a.analysis_dir).glob("analysis_*.parquet")):
        d = pd.read_parquet(f, columns=COLS)
        d = d[d.delay_added_s.notna()]
        if a.sample < 1:
            d = d.sample(frac=a.sample, random_state=0)
        parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    print(f"{len(df):,} stretch observations from {len(parts)} days")

    key = ["seg_hash", "is_weekend", "hour"]
    grp = df.groupby(key, sort=False)["delay_added_s"]
    df["base"] = grp.transform("median")
    df["base_n"] = grp.transform("size")
    df = df[df.base_n >= a.min_baseline].copy()
    df["excess"] = df.delay_added_s - df.base
    print(f"{len(df):,} observations with a baseline of >= {a.min_baseline} (typical excess = {df.excess.median():.1f}s)\n")

    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tables = {}

    df["rain"] = pd.cut(df.precipitation, [-1, 0, 0.5, 2, 1e9],
                        labels=["dry", "light (<0.5mm/h)", "moderate (0.5-2)", "heavy (>2)"])
    tables["rain"] = summarize(df, "rain")
    tables["bank_holiday"] = summarize(df, "is_bank_holiday")
    tables["school_term"] = summarize(df, "is_school_term")

    near = df[df.venue_dist_km <= a.venue_km].copy()
    near["event_state"] = near.ev_phase.astype(
        object).where(near.ev_phase.notna(), "no event")
    tables[f"near_venue_{a.venue_km}km_by_phase"] = summarize(
        near, "event_state")
    tables[f"near_venue_{a.venue_km}km_by_venue_phase"] = summarize(
        near, ["venue_nearest", "event_state"])

    act = df[df.ev_phase.notna()].copy()
    act["ring_km"] = pd.cut(act.ev_dist_km, [0, 1, 2, 4, 1e9], labels=[
                            "<1", "1-2", "2-4", "4+"])
    tables["by_distance_from_active_event"] = summarize(
        act, ["ev_phase", "ring_km"])

    for name, t in tables.items():
        print(f"== {name} ==")
        print(t.to_string(), "\n")
        t.to_csv(out / f"{name}.csv")
    print("Notes: excess is vs each stretch's own normal for that hour and day type. Observations from the same\n"
          "bus run are not independent, so treat the ci95 as optimistic. Weekends and event days overlap, so these\n"
          "show association, not proof of cause.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis-dir", required=True)
    ap.add_argument("--out-dir", default="out/correlations")
    ap.add_argument("--sample", type=float, default=1.0,
                    help="fraction of rows to use (lower it if memory runs out)")
    ap.add_argument("--venue-km", type=float, default=1.5)
    ap.add_argument("--min-baseline", type=int, default=10,
                    help="obs needed per stretch/hour/day-type baseline")
    main(ap.parse_args())
