"""Which routes are historically the most reliable?

For every route (overall and by time band) from the analysed arrivals: share on time, share more than 5 minutes
late, share early, mean / median / 90th-percentile delay. "On time" follows the UK convention: from 1 minute early
up to 5 minutes 59 seconds late. First stops of a run are excluded (a bus is never late leaving its terminus
in the data). Routes need at least --min-n arrivals to be ranked.

Outputs in --out-dir: route_reliability.csv (overall) and route_reliability_by_band.csv.

Usage (from delay_engine/):
  python3 archival_data/route_reliability.py --analysis-dir trip_matching/out/analysis \\
      --out-dir trip_matching/out/reliability --routes ../routes.parquet
"""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

# delay histogram: bins of 30 s from -10 min to +60 min
LO, HI, STEP = -600, 3600, 30
ON_FROM, ON_TO = -60, 300               # on time: [-60 s, 300 s)


def band(hour, weekend):
    b = np.select([hour.isin([7, 8]), hour.isin(range(9, 16)), hour.isin([16, 17])],
                  ["AM peak (07-09)", "midday (09-16)", "PM peak (16-18)"], "evening/early")
    return np.where(weekend, "weekend", b)


def main(a):
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tabs, sums = [], []
    for f in sorted(Path(a.analysis_dir).glob("analysis_*.parquet")):
        d = pd.read_parquet(
            f, columns=["route_id", "stop_sequence", "delay_s", "hour", "is_weekend"])
        d = d[(d.stop_sequence > 1) & d.delay_s.notna()]
        d = pd.DataFrame({"route_id": d.route_id.astype(str).to_numpy(),
                          "band": band(d.hour.reset_index(drop=True), d.is_weekend.to_numpy()),
                          "bin": ((d.delay_s.clip(LO, HI - 1).to_numpy() - LO) // STEP).astype(int),
                          "delay_s": d.delay_s.to_numpy(dtype="float64")})
        tabs.append(d.groupby(["route_id", "band", "bin"]
                              ).size().rename("n").reset_index())
        sums.append(d.groupby(["route_id", "band"]
                              ).delay_s.sum().rename("sum").reset_index())
    h = pd.concat(tabs).groupby(
        ["route_id", "band", "bin"]).n.sum().reset_index()
    sm = pd.concat(sums).groupby(["route_id", "band"])["sum"].sum()
    edges = LO + h.bin * STEP
    h["on"] = h.n.where((edges >= ON_FROM) & (edges < ON_TO), 0)
    h["late"] = h.n.where(edges >= ON_TO, 0)
    h["early"] = h.n.where(edges < ON_FROM, 0)

    def summarize(keys):
        g = h.sort_values(keys + ["bin"]).copy()
        g["cum"] = g.groupby(keys).n.cumsum() / \
            g.groupby(keys).n.transform("sum")
        t = g.groupby(keys).agg(n=("n", "sum"), on=("on", "sum"),
                                late=("late", "sum"), early=("early", "sum"))
        s_ = sm.groupby(level=keys).sum() if len(keys) == 1 else sm
        t["mean_delay_s"] = s_.reindex(t.index) / t.n
        for q, name in [(0.5, "median_delay_s"), (0.9, "p90_delay_s")]:
            t[name] = LO + g[g.cum >=
                             q].groupby(keys).bin.min() * STEP + STEP / 2
        for c in ["on", "late", "early"]:
            t[f"{c}_pct"] = 100 * t[c] / t.n
        return t.drop(columns=["on", "late", "early"]).round(1)

    allr = summarize(["route_id"])
    allr = allr[allr.n >= a.min_n]
    if a.routes and Path(a.routes).exists():
        r = pd.read_parquet(a.routes)
        r["route_id"] = r.route_id.astype(str)
        names = r.drop_duplicates("route_id").set_index("route_id")[[c for c in ["route_short_name", "route_long_name"]
                                                                     if c in r.columns]]
        allr = allr.join(names)
    allr = allr.sort_values("on_pct", ascending=False)
    allr.to_csv(out / "route_reliability.csv")
    byb = summarize(["route_id", "band"])
    byb = byb[byb.n >= a.min_n // 2]
    byb.to_csv(out / "route_reliability_by_band.csv")
    pd.set_option("display.width", 220)
    print(f"{len(allr)} routes with >= {a.min_n} arrivals\n\n== most reliable (on_pct = share on time, late_pct = more than 5 min late) ==")
    print(allr.head(a.top).to_string())
    print("\n== least reliable ==")
    print(allr.tail(a.top).iloc[::-1].to_string())
    print("\non time = 1 min early to 5:59 late. Bins are 30 s wide, so medians/p90 are approximate.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis-dir", required=True)
    ap.add_argument("--out-dir", default="out/reliability")
    ap.add_argument("--routes", default=None,
                    help="routes.parquet, to show route names")
    ap.add_argument("--min-n", type=int, default=2000,
                    help="arrivals needed to rank a route")
    ap.add_argument("--top", type=int, default=15)
    main(ap.parse_args())
