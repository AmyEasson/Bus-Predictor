"""Step 8: flag bus stretches that had road works on them, and compare delay with and without.

1. Turns the Street Manager permit events (filter_roadworks.py output) into one working period per permit:
     start = the WORK_START event time (works actually began; a later WORK_START_REVERTED cancels it)
     end   = the WORK_STOP event time, or the permit's latest planned end if no stop was recorded
   Permits that never started (refused, cancelled, no WORK_START) are ignored.
   Only permits that touch the carriageway are kept (everything except "No carriageway incursion").
2. For each bus arrival on a usable stretch (previous stop -> this stop), finds permits that were active at that
   moment and lie within --radius-m of the line between the two stops.
3. Compares delay on flagged vs unflagged arrivals: excess = delay added on the stretch minus that stretch's own
   median for the same hour and day type, measured on observations away from works.

Outputs (in --out-dir): rw_YYYYMMDD.parquet (one per day; keyed by run_key + stop_sequence so it can be joined
back to the analysis table), tables as CSV, and roadworks_by_stretch.csv.

Usage (from delay_engine/):
  python3 archival_data/roadworks_flag.py --permits trip_matching/out/permits_full/roadworks_gm.parquet \\
      --analysis-dir trip_matching/out/analysis --out-dir trip_matching/out/roadworks --workers 2
Needs scipy (pip install scipy).
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree

EPOCH = pd.Timestamp("1970-01-01", tz="UTC")
# how much a traffic-management type is likely to hold a bus up (used to pick the worst one at a stretch)
SEVERITY = {"Road closure": 5, "Contra-flow": 4, "Lane closure": 4, "Two-way signals": 4, "Multi-way signals": 4,
            "Stop/go boards": 4, "Temp obstruction 15 minute delay": 4, "Give and take": 3, "Priority working": 3,
            "Some carriageway incursion": 2}
NO_ROAD = "No carriageway incursion"
PERMIT_COLS = ["permit_reference_number", "event_type", "event_time", "easting", "northing",
               "traffic_management_type", "work_category", "proposed_end_date", "street_name", "town"]
DAY_COLS = ["run_key", "stop_sequence", "stop_lat", "stop_lon", "actual_arr_utc", "delay_added_s", "seg_hash",
            "is_weekend", "hour"]


def build_periods(path, max_days):
    d = pd.read_parquet(path, columns=PERMIT_COLS)
    d = d[d.easting.notna()].sort_values("event_time")
    def last(ev): return d[d.event_type == ev].groupby(
        "permit_reference_number").event_time.max()
    latest = d.groupby("permit_reference_number").tail(
        1).set_index("permit_reference_number")
    p = latest[["easting", "northing", "traffic_management_type", "work_category", "proposed_end_date",
                "street_name", "town"]].copy()
    p["ws"], p["wsr"] = last("WORK_START"), last("WORK_START_REVERTED")
    p["wp"], p["wpr"] = last("WORK_STOP"), last("WORK_STOP_REVERTED")
    n0 = len(p)
    started = p.ws.notna() & ~(p.wsr.notna() & (p.wsr > p.ws))
    p = p[started].copy()
    stopped = p.wp.notna() & (p.wp >= p.ws) & ~(p.wpr.notna() & (p.wpr > p.wp))
    planned_end = pd.to_datetime(
        p.proposed_end_date, utc=True, errors="coerce")
    end = p.wp.where(stopped, planned_end)
    # no stop and no plan: assume one day
    end = end.fillna(p.ws + pd.Timedelta(days=1))
    end = pd.concat([end, p.ws + pd.Timedelta(hours=1)],
                    axis=1).max(axis=1)   # never shorter than an hour
    end = pd.concat([end, p.ws + pd.Timedelta(days=max_days)],
                    axis=1).min(axis=1)  # cap runaway permits
    p["start_s"] = (p.ws - EPOCH).dt.total_seconds()
    p["end_s"] = (end - EPOCH).dt.total_seconds()
    p["open_ended"] = ~stopped
    tm = p.traffic_management_type.astype(object)
    p = p[tm.notna() & (tm != NO_ROAD)].copy()
    p["severity"] = p.traffic_management_type.map(
        SEVERITY).fillna(2).astype(int)
    print(f"{n0:,} permits in file | {started.sum():,} actually started | {len(p):,} touch the carriageway "
          f"| {p.open_ended.sum():,} with no recorded stop (planned end used)")
    return p.reset_index().rename(columns={"index": "permit_reference_number"})


def process_day(path, periods, out_dir, radius):
    day = Path(path).stem.split("_")[1]
    d = pd.read_parquet(path, columns=DAY_COLS).sort_values(
        ["run_key", "stop_sequence"]).reset_index(drop=True)
    to_bng = Transformer.from_crs(4326, 27700, always_xy=True)
    bx, by = to_bng.transform(d.stop_lon.to_numpy(), d.stop_lat.to_numpy())
    d["bx"], d["by"] = bx, by
    d["ax"], d["ay"] = d.groupby("run_key", sort=False).bx.shift(
        1), d.groupby("run_key", sort=False).by.shift(1)
    d["t"] = (pd.to_datetime(d.actual_arr_utc, utc=True) -
              EPOCH).dt.total_seconds()
    d = d[d.delay_added_s.notna() & d.ax.notna()].reset_index(drop=True)
    for c in ["rw_n", "rw_severity"]:
        d[c] = 0
    d["rw_dist_m"], d["rw_tm"], d["rw_category"], d["rw_ref"] = np.nan, None, None, None
    if len(d):
        pp = periods[(periods.end_s >= d.t.min()) & (
            periods.start_s <= d.t.max())].reset_index(drop=True)
    else:
        pp = periods.iloc[:0]
    if len(pp):
        A = d[["ax", "ay"]].to_numpy()
        B = d[["bx", "by"]].to_numpy()
        M = (A + B) / 2
        half = np.hypot(*(B - A).T) / 2
        tree = cKDTree(pp[["easting", "northing"]].to_numpy())
        cand = tree.query_ball_point(M, r=half + radius)
        ai = np.repeat(np.arange(len(d)), [len(c) for c in cand])
        pi = np.fromiter((j for c in cand for j in c),
                         dtype=int, count=len(ai))
        t = d.t.to_numpy()[ai]
        live = (pp.start_s.to_numpy()[pi] <= t) & (
            t <= pp.end_s.to_numpy()[pi])
        ai, pi = ai[live], pi[live]
        P = pp[["easting", "northing"]].to_numpy()[pi]
        a_, b_ = A[ai], B[ai]
        ab = b_ - a_
        frac = np.clip(((P - a_) * ab).sum(1) /
                       np.maximum((ab * ab).sum(1), 1e-9), 0, 1)
        dist = np.hypot(*(a_ + ab * frac[:, None] - P).T)
        near = dist <= radius
        pr = pd.DataFrame({"i": ai[near], "p": pi[near], "dist": dist[near]})
        pr["sev"] = pp.severity.to_numpy()[pr.p]
        if len(pr):
            pr = pr.sort_values(["i", "sev", "dist"],
                                ascending=[True, False, True])
            first = pr.groupby("i").head(1).set_index("i")
            cnt = pr.groupby("i").size()
            d.loc[cnt.index, "rw_n"] = cnt.to_numpy()
            d.loc[first.index, "rw_severity"] = first.sev.to_numpy()
            d.loc[first.index, "rw_dist_m"] = pr.groupby(
                "i").dist.min().loc[first.index].to_numpy()
            pj = first.p.to_numpy()
            d.loc[first.index, "rw_tm"] = pp.traffic_management_type.to_numpy()[
                pj]
            d.loc[first.index, "rw_category"] = pp.work_category.to_numpy()[pj]
            d.loc[first.index, "rw_ref"] = pp.permit_reference_number.to_numpy()[
                pj]
    keep = ["run_key", "stop_sequence", "stop_lat", "stop_lon", "seg_hash", "is_weekend", "hour", "delay_added_s",
            "rw_n", "rw_severity", "rw_dist_m", "rw_tm", "rw_category", "rw_ref"]
    out = d[keep].copy()
    for c in ["delay_added_s", "rw_dist_m"]:
        out[c] = out[c].astype("float32")
    for c in ["rw_tm", "rw_category"]:
        out[c] = out[c].astype("category")
    out.to_parquet(Path(out_dir) / f"rw_{day}.parquet", index=False)
    return day, len(out), int((out.rw_n > 0).sum()), int(len(pp))


def summarize(df, by):
    df = df.assign(big=df.excess > 60)
    t = df.groupby(by, observed=True).agg(n=("excess", "size"), mean_excess_s=("excess", "mean"),
                                          median_excess_s=("excess", "median"), sd=("excess", "std"),
                                          share_over_60s=("big", "mean"))
    t["ci95_s"] = 1.96 * t["sd"] / np.sqrt(t["n"])
    t["share_over_60s"] = (t["share_over_60s"] * 100).round(1)
    return t.drop(columns="sd").round(1)


def main(a):
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    periods = build_periods(a.permits, a.max_days)
    files = sorted(Path(a.analysis_dir).glob("analysis_*.parquet"))
    todo = [f for f in files if a.force or not (
        out / f"rw_{f.stem.split('_')[1]}.parquet").exists()]
    print(f"{len(files)} analysis days, {len(todo)} to flag")
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(process_day, str(f), periods,
                          str(out), a.radius_m) for f in todo]
        for fut in futs:
            day, n, nrw, npp = fut.result()
            print(f"  {day}: {n:,} usable stretches | {nrw:,} near active works ({nrw / max(n, 1):.1%}) "
                  f"| {npp:,} permits live that day")

    parts, xys = [], []
    cols = ["seg_hash", "is_weekend", "hour", "delay_added_s", "rw_n", "rw_severity", "rw_dist_m", "rw_tm",
            "rw_category", "stop_lat", "stop_lon"]
    rng = np.random.default_rng(0)
    for f in sorted(out.glob("rw_*.parquet")):
        d = pd.read_parquet(f, columns=cols)
        xys.append(d[["seg_hash", "stop_lat", "stop_lon"]
                     ].drop_duplicates("seg_hash"))
        d = d.drop(columns=["stop_lat", "stop_lon"])
        if a.sample < 1:   # keep every observation near works, sample the rest
            d = d[(d.rw_n > 0) | (rng.random(len(d)) < a.sample)]
        parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    del parts

    # each stretch's normal = its median delay at that hour and day type on observations AWAY from works
    key = ["seg_hash", "is_weekend", "hour"]
    clean = df[df.rw_n == 0]
    bt = clean.groupby(key, sort=False)["delay_added_s"].agg(
        base="median", base_n="size").reset_index()
    df = df.merge(bt, on=key, how="inner")
    df = df[df.base_n >= a.min_baseline].copy()
    df["excess"] = df.delay_added_s - df.base
    df["works"] = np.where(df.rw_n > 0, "road works", "none")
    df["blocking"] = np.where(df.rw_severity >= 4, "signals/lane/closure",
                              np.where(df.rw_n > 0, "other works", "none"))
    print(f"\n{len(df):,} observations with a baseline | {(df.rw_n > 0).sum():,} near road works\n")

    tables = {"works_vs_none": summarize(df, "works")}
    tables["blocking_vs_other"] = summarize(df, "blocking")
    w = df[df.rw_n > 0].copy()
    tables["by_traffic_management"] = summarize(
        df.assign(tm=df.rw_tm.astype(object).fillna("none")), "tm")
    tables["by_work_category"] = summarize(
        df.assign(cat=df.rw_category.astype(object).fillna("none")), "cat")
    w["distance_m"] = pd.cut(
        w.rw_dist_m, [-1, 25, 50, 1e9], labels=["<25", "25-50", "50+"])
    tables["by_distance_to_works"] = summarize(w, "distance_m")
    w["concurrent"] = pd.cut(w.rw_n, [0, 1, 2, 1e9], labels=["1", "2", "3+"])
    tables["by_number_of_works"] = summarize(w, "concurrent")
    cnt = df.groupby("seg_hash").rw_n.apply(lambda s: (s > 0).sum())
    same = df[df.seg_hash.isin(cnt[cnt >= a.min_flagged].index)]
    tables["same_stretches_only"] = summarize(same, "works")
    for name, t in tables.items():
        print(f"== {name} ==\n{t.to_string()}\n")
        t.to_csv(out / f"{name}.csv")

    s = same.groupby(["seg_hash", "works"]).excess.agg(
        ["size", "mean"]).unstack("works")
    s.columns = [f"{b}_{'n' if a_ == 'size' else 'mean_excess_s'}".replace(
        " ", "_") for a_, b in s.columns]
    xy = pd.concat(xys).drop_duplicates("seg_hash").set_index("seg_hash")
    s = s.join(xy)
    if "road_works_mean_excess_s" in s and "none_mean_excess_s" in s:
        s["works_penalty_s"] = (
            s.road_works_mean_excess_s - s.none_mean_excess_s).round(1)
        s = s[(s.none_n >= 30) & (s.road_works_n >= a.min_flagged)]
        s = s.sort_values("works_penalty_s", ascending=False)
        print(
            f"== stretches with the biggest slowdown near works (>= {a.min_flagged} flagged, >= 30 normal) ==")
        print(s.head(15).round(1).to_string(), "\n")
    s.to_csv(out / "roadworks_by_stretch.csv")
    print("Notes: excess is vs each stretch's own normal (hour and day type) on observations away from works. Works\n"
          "are only counted from their recorded WORK_START, so jobs that began before the permit data starts are\n"
          "missed (which pushes results toward zero). Observations on the same run are not independent, so treat\n"
          "ci95 as optimistic.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--permits", required=True,
                    help="roadworks_gm.parquet from filter_roadworks.py (permits)")
    ap.add_argument("--analysis-dir", required=True)
    ap.add_argument("--out-dir", default="out/roadworks")
    ap.add_argument("--radius-m", type=float, default=75,
                    help="works within this distance of the stretch count")
    ap.add_argument("--max-days", type=float, default=90,
                    help="cap on how long one permit is assumed active")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--sample", type=float, default=0.5)
    ap.add_argument("--min-baseline", type=int, default=10)
    ap.add_argument("--min-flagged", type=int, default=20,
                    help="flagged observations needed to list a stretch")
    ap.add_argument("--force", action="store_true")
    main(ap.parse_args())
