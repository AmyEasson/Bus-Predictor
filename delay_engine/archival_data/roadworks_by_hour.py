"""Does the road-works penalty depend on the time of day? (peak-hour queues vs quiet-hour)

Compares excess delay (vs each stretch's normal away from works) for road-blocking works (signals, lane
closures, road closures: severity >= 4) with no works, hour by hour, weekdays and weekends separately.

Usage (from delay_engine/):
  python3 archival_data/roadworks_by_hour.py --rw-dir trip_matching/out/roadworks
"""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

COLS = ["seg_hash", "is_weekend", "hour",
        "delay_added_s", "rw_n", "rw_severity"]


def main(a):
    rw = Path(a.rw_dir)
    rng = np.random.default_rng(0)
    parts = []
    for f in sorted(rw.glob("rw_*.parquet")):
        d = pd.read_parquet(f, columns=COLS)
        parts.append(d[(d.rw_severity >= 4) | (d.rw_n == 0)
                     & (rng.random(len(d)) < a.sample)])
    df = pd.concat(parts, ignore_index=True)
    key = ["seg_hash", "is_weekend", "hour"]
    bt = df[df.rw_n == 0].groupby(key, sort=False)["delay_added_s"].agg(
        base="median", base_n="size").reset_index()
    df = df.merge(bt, on=key, how="inner")
    df = df[df.base_n >= a.min_baseline].copy()
    df["excess"] = df.delay_added_s - df.base
    df["big"] = df.excess > 60
    df["works"] = np.where(df.rw_severity >= 4, "blocking works", "none")
    t = df.groupby(["is_weekend", "hour", "works"]).agg(n=("excess", "size"), mean_excess_s=("excess", "mean"),
                                                        share_over_60s=("big", "mean")).unstack("works")
    t.columns = [f"{b.replace(' ', '_')}_{a_}" for a_, b in t.columns]
    t["penalty_s"] = t["blocking_works_mean_excess_s"] - t["none_mean_excess_s"]
    t = t[t.blocking_works_n >= a.min_obs].round(1)
    t.to_csv(rw / "roadworks_by_hour.csv")
    pd.set_option("display.width", 200)
    print(t[["blocking_works_n", "none_mean_excess_s", "blocking_works_mean_excess_s", "penalty_s",
             "none_share_over_60s", "blocking_works_share_over_60s"]].to_string())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rw-dir", required=True)
    ap.add_argument("--sample", type=float, default=0.5)
    ap.add_argument("--min-baseline", type=int, default=10)
    ap.add_argument("--min-obs", type=int, default=500)
    main(ap.parse_args())
