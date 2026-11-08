"""Export road works for the API: which works are on (or planned) and how much they slow buses.

Reads
  Street Manager permit events (filter_roadworks.py output, permits_full/roadworks_gm.parquet)
  the road-works analysis (roadworks_flag.py / roadworks_explain.py / roadworks_by_hour.py output dir)
Writes (to --out-dir, default ../backend/data/delay)
  roadworks.parquet        one row per permit that is in progress or planned and touches the carriageway:
                           position (WGS84), street, town, traffic management, category, window, status, and
                             measured_s   extra delay per bus stretch measured while it was active (roadworks_explain),
                                          only for works the analysis saw with enough buses (n >= --min-obs)
                             expected_s   what works of this traffic-management type typically add per stretch
                                          (type mean excess minus the no-works mean), used when not measured
  roadworks_effects.json   the analysis tables (by traffic management, concurrent works, distance, category,
                           hour of day), for the UI and for scaling an effect to the hour of travel

Which works count: the latest event per permit says work is "in progress", or "planned" with the permit granted
(not cancelled / refused / revoked); traffic management other than "No carriageway incursion". Window: from the
real WORK_START (else the proposed start) to the proposed end; the permit data ends on the last event in the file,
so "in progress" means "in progress as of then".

Usage (from delay_engine/):
  python3 export_roadworks.py [--permits trip_matching/out/permits_full/roadworks_gm.parquet]
                              [--rw-dir trip_matching/out/roadworks] [--out-dir ../backend/data/delay]
Needs pyproj.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer

NO_ROAD = "No carriageway incursion"
PERMIT_COLS = ["permit_reference_number", "event_type", "event_time", "easting", "northing", "street_name", "town",
               "traffic_management_type", "work_category", "work_status", "permit_status",
               "proposed_start_date", "proposed_end_date"]


def table(rw_dir, name):
    p = Path(rw_dir) / f"{name}.csv"
    return pd.read_csv(p) if p.exists() else None


def export(permits, rw_dir, out_dir, min_obs=50):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    d = pd.read_parquet(permits, columns=PERMIT_COLS).dropna(subset=["easting", "northing"])
    d = d.sort_values("event_time")
    data_until = d.event_time.max()
    latest = d.groupby("permit_reference_number").tail(1).set_index("permit_reference_number")
    started = d[d.event_type == "WORK_START"].groupby("permit_reference_number").event_time.max()

    in_progress = latest.work_status == "Works in progress"
    planned = (latest.work_status == "Works planned") & latest.permit_status.isin(
        ["granted", "progressed", "permit_modification_request"])
    tm = latest.traffic_management_type.astype(object)
    w = latest[(in_progress | planned) & tm.notna() & (tm != NO_ROAD)].copy()
    w["status"] = np.where(w.work_status == "Works in progress", "in_progress", "planned")

    start = pd.to_datetime(w.proposed_start_date, utc=True, errors="coerce")
    w["start"] = started.reindex(w.index).fillna(start)
    w["end"] = pd.to_datetime(w.proposed_end_date, utc=True, errors="coerce")
    w = w[w.start.notna() & w.end.notna() & (w.end >= data_until - pd.Timedelta(days=1))]
    w = w[w.end - w.start <= pd.Timedelta(days=400)]  # drop runaway multi-year permits

    to_wgs = Transformer.from_crs(27700, 4326, always_xy=True)
    lon, lat = to_wgs.transform(w.easting.to_numpy(), w.northing.to_numpy())
    w["lat"], w["lon"] = np.round(lat, 6), np.round(lon, 6)

    # measured impact per permit, where the analysis saw enough buses near it while it was active
    imp = table(rw_dir, "permit_impact")
    if imp is not None:
        imp = imp[imp.n >= min_obs].set_index("rw_ref")
        w["measured_s"] = imp.mean_excess_s.reindex(w.index)
        w["measured_n"] = imp.n.reindex(w.index)
    else:
        w["measured_s"], w["measured_n"] = np.nan, np.nan

    # typical effect of this kind of works: type mean excess minus the no-works mean
    by_tm = table(rw_dir, "by_traffic_management")
    if by_tm is not None:
        base = float(by_tm.loc[by_tm.tm == "none", "mean_excess_s"].iloc[0])
        type_pen = (by_tm.set_index("tm").mean_excess_s - base).clip(lower=0)
        w["expected_s"] = w.traffic_management_type.map(type_pen)
    else:
        w["expected_s"] = np.nan
    # a measured value is relative to the stretch's normal too, so remove the same no-works offset
    if by_tm is not None:
        w["measured_s"] = (w.measured_s - base).clip(lower=0)

    keep = w.reset_index()[["permit_reference_number", "lat", "lon", "street_name", "town",
                            "traffic_management_type", "work_category", "status", "start", "end",
                            "measured_s", "measured_n", "expected_s"]]
    keep.to_parquet(out / "roadworks.parquet", index=False)

    effects = {"permits_until": str(data_until)}
    for name in ["blocking_vs_other", "by_traffic_management", "by_number_of_works", "by_distance_to_works",
                 "by_work_category", "roadworks_by_hour", "works_vs_none"]:
        t = table(rw_dir, name)
        if t is not None:
            effects[name] = t.round(2).to_dict(orient="records")
    (out / "roadworks_effects.json").write_text(json.dumps(effects, indent=1, default=str))

    print(f"roadworks.parquet: {len(keep):,} works ({(keep.status == 'in_progress').sum():,} in progress, "
          f"{(keep.status == 'planned').sum():,} planned; {keep.measured_s.notna().sum():,} with a measured impact) "
          f"| permits up to {data_until:%Y-%m-%d}")
    return keep


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--permits", default="trip_matching/out/permits_full/roadworks_gm.parquet")
    ap.add_argument("--rw-dir", default="trip_matching/out/roadworks")
    ap.add_argument("--out-dir", default="../backend/data/delay")
    ap.add_argument("--min-obs", type=int, default=50, help="bus passes needed to trust a permit's measured impact")
    a = ap.parse_args()
    export(a.permits, a.rw_dir, a.out_dir, a.min_obs)
