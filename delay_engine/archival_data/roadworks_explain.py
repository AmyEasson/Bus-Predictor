"""Step 9: which road works actually slowed buses, and where? (the "why" for a delay)

Reads the per-day files from roadworks_flag.py. For every permit it reports how much extra delay buses had on
stretches near it while it was active (excess vs each stretch's normal away from works), with street, town,
traffic management type, work category and dates. Also breaks the worst stretches down by permit.

Each observation is attributed to the most severe permit near it (nearest if tied), so where several jobs overlap,
the credit goes to that one.

Outputs in --rw-dir: permit_impact.csv, worst_stretches_by_permit.csv.

Usage (from delay_engine/):
  python3 archival_data/roadworks_explain.py --permits trip_matching/out/permits_full/roadworks_gm.parquet \\
      --rw-dir trip_matching/out/roadworks
"""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from roadworks_flag import build_periods

COLS = ["seg_hash", "is_weekend", "hour", "delay_added_s", "rw_n", "rw_ref"]


def main(a):
    rw = Path(a.rw_dir)
    periods = build_periods(a.permits, a.max_days).set_index("permit_reference_number")
    rng = np.random.default_rng(0)
    parts = []
    for f in sorted(rw.glob("rw_*.parquet")):
        d = pd.read_parquet(f, columns=COLS)
        parts.append(d[(d.rw_n > 0) | (rng.random(len(d)) < a.sample)])
    df = pd.concat(parts, ignore_index=True)
    del parts
    key = ["seg_hash", "is_weekend", "hour"]
    bt = df[df.rw_n == 0].groupby(key, sort=False)["delay_added_s"].agg(base="median", base_n="size").reset_index()
    df = df.merge(bt, on=key, how="inner")
    df = df[df.base_n >= a.min_baseline].copy()
    df["excess"] = df.delay_added_s - df.base
    df["big"] = df.excess > 60
    fl = df[df.rw_ref.notna()].copy()
    fl["rw_ref"] = fl.rw_ref.astype(str)
    print(f"{len(fl):,} observations near works, {fl.rw_ref.nunique():,} permits involved")

    g = fl.groupby("rw_ref").agg(n=("excess", "size"), stretches=("seg_hash", "nunique"),
                                 mean_excess_s=("excess", "mean"), median_excess_s=("excess", "median"),
                                 share_over_60s=("big", "mean"))
    g["share_over_60s"] = (g.share_over_60s * 100).round(1)
    g = g[g.n >= a.min_obs]
    info = periods[["street_name", "town", "traffic_management_type", "work_category"]].copy()
    info["start"] = periods.ws.dt.strftime("%Y-%m-%d")
    info["end"] = pd.to_datetime(periods.end_s, unit="s", utc=True).dt.strftime("%Y-%m-%d")
    g = g.join(info).sort_values("mean_excess_s", ascending=False).round(1)
    g.to_csv(rw / "permit_impact.csv")
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 20)
    print(f"\n== works with the biggest slowdown (>= {a.min_obs} observations) ==")
    print(g.head(a.top).to_string(), "\n")

    # worst stretches (from roadworks_by_stretch.csv), broken down by permit
    sp = rw / "roadworks_by_stretch.csv"
    if sp.exists():
        s = pd.read_csv(sp, dtype={"seg_hash": "uint64"})
        top = s.sort_values("works_penalty_s", ascending=False).seg_hash.head(a.stretches).to_numpy()
        b = fl[fl.seg_hash.isin(top)].groupby(["seg_hash", "rw_ref"]).agg(
            n=("excess", "size"), mean_excess_s=("excess", "mean")).reset_index()
        b = b[b.n >= 5].join(info, on="rw_ref").sort_values(["seg_hash", "mean_excess_s"], ascending=[True, False])
        b.round(1).to_csv(rw / "worst_stretches_by_permit.csv", index=False)
        print("== worst stretches, by permit ==")
        print(b.round(1).to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--permits", required=True)
    ap.add_argument("--rw-dir", required=True, help="the --out-dir used for roadworks_flag.py")
    ap.add_argument("--sample", type=float, default=0.5)
    ap.add_argument("--min-baseline", type=int, default=10)
    ap.add_argument("--min-obs", type=int, default=50, help="observations needed to list a permit")
    ap.add_argument("--max-days", type=float, default=90)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--stretches", type=int, default=5, help="how many worst stretches to break down")
    main(ap.parse_args())