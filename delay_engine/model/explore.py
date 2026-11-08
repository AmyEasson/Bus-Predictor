#!/usr/bin/env python3
"""
explore.py - data exploration: summary tables + charts for analysis and the pitch.

Reads stop_arrivals (from the team's arrivals.py) and, if they exist, the trained model's results.
Writes PNG charts to delay_engine/model/figures/ and prints the key numbers.

Usage (from the project root):
    python3 delay_engine/model/explore.py
    python3 delay_engine/model/explore.py --arrivals delay_engine/trip_matching/out/stop_arrivals.parquet

Charts
  01_coverage.png          stop arrivals per hour (how much data we have, and any gaps)
  02_delay_by_hour.png     median delay by hour of day, one line per route
  03_route_reliability.png share of stop arrivals 5+ min late, per route
  04_hotspots.png          stretches of road where buses LOSE the most time
  05_sample_runs.png       delay along 6 individual journeys (sanity check: should be smooth)
  06_bunching.png          how often buses arrive bunched or with big gaps
  07_model_vs_baselines.png  (after train.py) prediction error: model vs simple rules
  08_drivers.png             (after train.py) what drives the model's predictions
"""
import argparse
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")                       # no display needed (works in the dev container)
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as F  # noqa: E402

# ---- chart style: light surface, recessive grid, ink-coloured text, fixed series order ------
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4",
          "#008300", "#6250d6", "#e34948"]   # categorical slots, always used in this order
ACCENT = SERIES[0]
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.titlecolor": INK, "axes.titleweight": "bold",
    "axes.titlesize": 12, "axes.titlelocation": "left", "font.size": 10,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 2,
    "legend.frameon": False,
})


def save(fig, folder, name):
    fig.tight_layout()
    path = os.path.join(folder, name)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    print(f"  saved {path}")


def route_colors(routes):
    """Colour follows the route, not its rank: sorted route names -> fixed slots."""
    return {r: SERIES[i % len(SERIES)] for i, r in enumerate(sorted(routes, key=str))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arrivals", default="delay_engine/trip_matching/out/stop_arrivals.parquet",
                    help="arrivals.py output (.parquet), or compute_delays.py output (.sqlite)")
    ap.add_argument("--gtfs", default="gtfs/", help="GTFS folder (for direction, stop names, last stops)")
    ap.add_argument("--models", default="delay_engine/model/models/")
    ap.add_argument("--figures", default="delay_engine/model/figures/")
    a = ap.parse_args()
    os.makedirs(a.figures, exist_ok=True)

    sa = F.load_stop_arrivals(a.arrivals, a.gtfs)
    sa["local"] = sa.actual_utc.dt.tz_convert(F.TZ)
    sa["hour"] = sa.local.dt.hour
    mid = sa[(sa.is_first_stop == 0) & (sa.is_last_stop == 0)].copy()   # exclude termini
    mid["delay_min"] = mid.delay_s / 60
    colors = route_colors(sa.route_short_name.unique())

    # ---- headline numbers ------------------------------------------------------------------
    print("\n=== Headline numbers (excluding first/last stops) ===")
    print(f"period: {sa.local.min():%a %H:%M} -> {sa.local.max():%a %H:%M}  "
          f"| {sa.run_id.nunique():,} journeys | {len(mid):,} stop arrivals")
    print(f"median delay {mid.delay_min.median():.1f} min | "
          f"90th percentile {mid.delay_min.quantile(.9):.1f} min | "
          f"5+ min late: {(mid.delay_s >= 300).mean():.0%} | "
          f"early (1+ min): {(mid.delay_s <= -60).mean():.0%}")
    by_route = mid.groupby("route_short_name").agg(
        journeys=("run_id", "nunique"), median_min=("delay_min", "median"),
        p90_min=("delay_min", lambda s: s.quantile(.9)),
        late5=("delay_s", lambda s: (s >= 300).mean())).round(2)
    print("\nBy route:\n" + by_route.to_string())

    # ---- 01 coverage -------------------------------------------------------------------
    per_hour = sa.set_index("local").resample("h").size()
    fig, ax = plt.subplots(figsize=(9, 3.2))
    ax.bar(per_hour.index, per_hour.values, width=0.035, color=ACCENT)
    ax.set_title("Stop arrivals recorded per hour")
    ax.set_ylabel("stop arrivals")
    ax.grid(axis="x", visible=False)
    # Empty hours overnight are normal (few or no buses); only daytime gaps suggest missing data
    gaps = per_hour[(per_hour == 0) & (per_hour.index.hour >= 6)]
    if len(gaps):
        days = sorted({t.strftime("%a %d %b") for t in gaps.index})
        print(f"\ndaytime hours with NO data: {len(gaps)} hours, on {', '.join(days[:12])}"
              + (" ..." if len(days) > 12 else ""))
    save(fig, a.figures, "01_coverage.png")

    # ---- 02 delay by hour, per route --------------------------------------------------------
    hr = mid.groupby(["route_short_name", "hour"]).delay_min.median().unstack(0)
    fig, ax = plt.subplots(figsize=(9, 4))
    for r in sorted(hr.columns, key=str):
        s = hr[r].dropna()
        ax.plot(s.index, s.values, color=colors[r], marker="o", markersize=4, label=f"Route {r}")
    ax.axhline(0, color=INK2, linewidth=1)
    ax.set_title("Median delay by hour of day")
    ax.set_xlabel("hour (UK time)")
    ax.set_ylabel("minutes late")
    ax.legend(ncol=min(5, len(hr.columns)), loc="upper left")
    save(fig, a.figures, "02_delay_by_hour.png")

    # ---- 03 route reliability --------------------------------------------------------------
    rel = (mid.groupby("route_short_name").delay_s.apply(lambda s: (s >= 300).mean())
              .sort_values())
    fig, ax = plt.subplots(figsize=(7, 0.5 * len(rel) + 1.2))
    ax.barh([f"Route {r}" for r in rel.index], rel.values * 100, color=ACCENT, height=0.6)
    for y, v in enumerate(rel.values):
        ax.text(v * 100 + 0.5, y, f"{v:.0%}", va="center", color=INK2)
    ax.set_title("Share of stop arrivals 5+ minutes late")
    ax.set_xlabel("% of stop arrivals")
    ax.grid(axis="y", visible=False)
    save(fig, a.figures, "03_route_reliability.png")

    # ---- 04 hotspots: where delay is CREATED -------------------------------------------------
    seg = mid.dropna(subset=["added_delay_s"]).copy()
    # previous stop name from the FULL arrivals table (added_delay_s is only set when the
    # previous stop is the adjacent one, see features.load_stop_arrivals)
    prev_name = sa.sort_values(["run_id", "stop_sequence"]).groupby("run_id").stop_name.shift()
    seg["prev_stop"] = prev_name.reindex(seg.index)
    seg = seg.dropna(subset=["prev_stop"])
    seg["stretch"] = seg.prev_stop + " → " + seg.stop_name
    hot = (seg.groupby("stretch").added_delay_s.agg(["median", "count"])
              .query("count >= 5").sort_values("median").tail(12))
    if len(hot):
        fig, ax = plt.subplots(figsize=(9, 0.42 * len(hot) + 1.4))
        # Delay added per stretch is usually tens of seconds, so show seconds
        vals = hot["median"].values
        ax.barh(hot.index, vals, color=SERIES[1], height=0.6)
        pad = max(abs(vals).max(), 1) * 0.015
        for y, (v, n) in enumerate(zip(vals, hot["count"].values)):
            ax.text(v + pad, y, f"{v:.0f} s  (n={n})", va="center", color=INK2, fontsize=8)
        ax.set_xlim(right=max(vals.max(), 1) * 1.25)
        ax.set_title("Where buses lose the most time (median delay added per stretch)")
        ax.set_xlabel("seconds added between the two stops")
        ax.grid(axis="y", visible=False)
        ax.tick_params(axis="y", labelsize=8)
        save(fig, a.figures, "04_hotspots.png")
        print("\nTop delay-creating stretches (median seconds added):")
        print(hot["median"].round(0).iloc[::-1].head(8).to_string())

    # ---- 05 sample runs (sanity check) -------------------------------------------------------
    long_runs = mid.groupby("run_id").size()
    long_runs = long_runs[long_runs >= 8].index
    if len(long_runs):
        pick = pd.Series(long_runs).sample(min(6, len(long_runs)), random_state=0)
        fig, axes = plt.subplots(2, 3, figsize=(11, 5.5), sharey=True)
        for ax, rid in zip(axes.flat, pick):
            r = mid[mid.run_id == rid].sort_values("stop_sequence")
            route = r.route_short_name.iloc[0]
            ax.plot(r.stop_sequence, r.delay_min, color=colors[route], marker="o", markersize=4)
            ax.axhline(0, color=INK2, linewidth=1)
            ax.set_title(f"Route {route}, {r.local.iloc[0]:%a %H:%M}", fontsize=10)
            ax.set_xlabel("stop number along trip")
        for ax in axes[:, 0]:
            ax.set_ylabel("minutes late")
        for ax in list(axes.flat)[len(pick):]:
            ax.set_visible(False)
        fig.suptitle("Delay along individual journeys (should change smoothly)",
                     x=0.01, ha="left", fontweight="bold")
        save(fig, a.figures, "05_sample_runs.png")

    # ---- 06 bunching ----------------------------------------------------------------------
    hw = mid.headway_ratio.replace([np.inf, -np.inf], np.nan).dropna().clip(0, 3)
    if len(hw):
        fig, ax = plt.subplots(figsize=(8, 3.6))
        ax.hist(hw, bins=30, color=ACCENT, edgecolor=SURFACE, linewidth=2)
        ax.axvline(1, color=INK2, linewidth=1)
        ax.text(1.03, ax.get_ylim()[1] * 0.92, "as timetabled", color=INK2, fontsize=9)
        ax.set_title("Gap to the bus in front, relative to the timetable")
        ax.set_xlabel("actual gap ÷ scheduled gap   (<0.5 = bunched, >1.5 = long wait)")
        ax.set_ylabel("stop arrivals")
        ax.grid(axis="x", visible=False)
        save(fig, a.figures, "06_bunching.png")
        print(f"\nbunched (gap < half the timetabled gap): {(hw < 0.5).mean():.0%} | "
              f"long gap (> 1.5x): {(hw > 1.5).mean():.0%}")

    # ---- 07/08 model results (only after train.py has run) ------------------------------------
    meta_path = os.path.join(a.models, "metadata.json")
    if os.path.exists(meta_path):
        meta = json.load(open(meta_path))
        res = pd.Series(meta["mae_s"]).sort_values(ascending=False) / 60
        fig, ax = plt.subplots(figsize=(8, 0.55 * len(res) + 1.2))
        cols = [SERIES[1] if k == "MODEL (P50)" else GRID for k in res.index]
        ax.barh(res.index, res.values, color=cols, height=0.6)
        for y, v in enumerate(res.values):
            ax.text(v + 0.02, y, f"{v:.2f} min", va="center", color=INK2)
        ax.set_title("Prediction error on unseen data (lower is better)")
        ax.set_xlabel("mean absolute error, minutes")
        ax.grid(axis="y", visible=False)
        save(fig, a.figures, "07_model_vs_baselines.png")

        imp = pd.Series(meta["importance_s"]).sort_values().tail(10)
        fig, ax = plt.subplots(figsize=(8, 0.45 * len(imp) + 1.2))
        ax.barh(imp.index, imp.values, color=ACCENT, height=0.6)
        ax.set_title("What drives the model's predictions")
        ax.set_xlabel("average effect on predicted delay (seconds)")
        ax.grid(axis="y", visible=False)
        save(fig, a.figures, "08_drivers.png")
        cal = meta["calibration"]
        print(f"\nmodel: {res['MODEL (P50)']:.2f} min error | real delay above P90 "
              f"{cal['above_p90']:.0%} of the time (target ~10%)")
    else:
        print("\n(no trained model yet - run train.py to add charts 07 and 08)")


if __name__ == "__main__":
    main()