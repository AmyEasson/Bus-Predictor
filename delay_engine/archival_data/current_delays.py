"""Find the buses that are running late right now, and say why.

Takes the analysed arrivals (build_analysis.py output) up to a moment in time (--as-of, default: the newest arrival
in the data) and looks at every bus that has passed a stop in the last --window-min minutes:
  * how late it is at its latest stop, and how late buses usually are at that stop, hour and day type
  * where it lost the most time recently (the stretch whose delay beat that stretch's normal by the most)
  * what is going on there: road works near the stretch that usually cost buses time (with the permit, street
    and how much), or a football match / concert nearby. Rush hour and heavy rain are shown as context only
    (rush hour is already part of each stretch's normal for that hour; rain showed no link to delay)
Normals come from days BEFORE the as-of day, so it can be tested on past days exactly as it would run live.

Outputs in --out-dir: current_delays.csv and current_delays.json (for the UI), plus a printed summary.

Usage (from delay_engine/):
  python3 archival_data/current_delays.py --analysis-dir trip_matching/out/analysis \\
      --rw-dir trip_matching/out/roadworks [--as-of "2026-11-06 08:30"] [--stops ../stops.parquet] [--routes ../routes.parquet]
"""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd

COLS = ["run_key", "route_id", "stop_sequence", "stop_id", "actual_arr_utc", "delay_s", "delay_added_s", "seg_hash",
        "is_weekend", "hour", "is_rush", "precipitation", "ev_phase", "ev_venue", "ev_type", "ev_dist_km"]


def day_of(f):
    return Path(f).stem.split("_")[1]


def utc(x):
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def main(a):
    adir, rwdir = Path(a.analysis_dir), Path(a.rw_dir) if a.rw_dir else None
    files = sorted(adir.glob("analysis_*.parquet"))
    if a.as_of:
        asof = utc(a.as_of)
    else:
        asof = pd.to_datetime(pd.read_parquet(
            files[-1], columns=["actual_arr_utc"]).actual_arr_utc, utc=True).max()
    d0 = asof.strftime("%Y%m%d")
    d1 = (asof - pd.Timedelta(days=1)).strftime("%Y%m%d")
    print(f"as of {asof:%Y-%m-%d %H:%M} UTC")

    # ---- recent arrivals (as-of day and the day before: late-night trips belong to the previous service day)
    recent = []
    for f in files:
        if day_of(f) in (d0, d1):
            d = pd.read_parquet(f, columns=COLS)
            d["service_day"] = day_of(f)
            if rwdir is not None and (rwdir / f"rw_{day_of(f)}.parquet").exists():
                rw = pd.read_parquet(rwdir / f"rw_{day_of(f)}.parquet",
                                     columns=["run_key", "stop_sequence", "rw_n", "rw_tm", "rw_category", "rw_ref"])
                d = d.merge(rw, on=["run_key", "stop_sequence"], how="left")
            recent.append(d)
    if not recent:
        raise SystemExit(f"no analysis file for {d0} or {d1}")
    r = pd.concat(recent, ignore_index=True)
    r["t"] = pd.to_datetime(r.actual_arr_utc, utc=True)
    r = r[(r.t <= asof) & (r.t > asof - pd.Timedelta(minutes=a.lookback_min))]
    active = r[r.t > asof -
               pd.Timedelta(minutes=a.window_min)].run_key.unique()
    r = r[r.run_key.isin(active)]
    for c in ["rw_n", "rw_tm", "rw_category", "rw_ref"]:
        if c not in r:
            r[c] = np.nan
    print(f"{len(active):,} buses seen in the last {a.window_min} min")

    # ---- normals from earlier days
    past = [f for f in files if day_of(f) < d0] or [
        f for f in files if day_of(f) != d0]
    rng = np.random.default_rng(0)
    parts = []
    for f in past:
        d = pd.read_parquet(f, columns=[
                            "seg_hash", "stop_id", "is_weekend", "hour", "delay_added_s", "delay_s"])
        parts.append(d[rng.random(len(d)) < a.sample])
    p = pd.concat(parts, ignore_index=True)
    seg = p.groupby(["seg_hash", "is_weekend", "hour"], sort=False).delay_added_s.agg(
        seg_base="median", seg_n="size")
    seg = seg[seg.seg_n >= a.min_baseline].seg_base.reset_index()
    stp = p.groupby(["stop_id", "is_weekend", "hour"], sort=False).delay_s.agg(
        usual_delay_s="median", st_n="size")
    stp = stp[stp.st_n >= a.min_baseline].usual_delay_s.reset_index()
    del p, parts

    # ---- each active bus: latest stop, delay, usual delay
    r = r.merge(seg, on=["seg_hash", "is_weekend", "hour"], how="left")
    r["lost_s"] = r.delay_added_s - r.seg_base
    last = r.sort_values("stop_sequence").groupby("run_key").tail(1).copy()
    last = last.merge(stp, on=["stop_id", "is_weekend", "hour"], how="left")
    first = r.sort_values("t").groupby("run_key").head(1).set_index("run_key")
    late = last[last.delay_s >= a.late_s].copy()
    print(f"{len(late):,} running {a.late_s / 60:.0f}+ min late")

    # ---- where did each late bus lose the most time, and why
    perm = None
    if rwdir is not None and (rwdir / "permit_impact.csv").exists():
        perm = pd.read_csv(rwdir / "permit_impact.csv").set_index("rw_ref")
    worst = r[r.lost_s.notna()].sort_values("lost_s").groupby(
        "run_key").tail(1).set_index("run_key")
    rows = []
    for x in late.itertuples():
        w = worst.loc[x.run_key] if x.run_key in worst.index else None
        causes, context, lost, where = [], [], np.nan, None
        if w is not None and w.lost_s >= a.lost_s:
            lost, where = float(w.lost_s), w.stop_id
            if w.rw_n and w.rw_n > 0:
                known = perm is not None and w.rw_ref in perm.index
                pr = perm.loc[w.rw_ref] if known else None
                if known and pr.mean_excess_s < a.works_min_s:
                    context.append(f"{str(w.rw_tm).lower()} works on {str(pr.street_name).title()} nearby "
                                   f"(these usually cost buses little)")
                elif known:
                    causes.append(f"{str(w.rw_tm).lower()} on {str(pr.street_name).title()}, {str(pr.town).title()} "
                                  f"({w.rw_category} works {pr.start} to {pr.end}); buses there usually lose "
                                  f"{pr.mean_excess_s:.0f} s")
                else:
                    causes.append(
                        f"road works nearby ({w.rw_tm}, {w.rw_category}; typical impact not measured)")
            if isinstance(w.ev_phase, str):
                causes.append(
                    f"{w.ev_type} at {w.ev_venue} ({w.ev_phase}-event, {w.ev_dist_km:.1f} km away)")
            if not causes:
                causes.append(
                    "no known cause (general congestion or an incident)")
        else:
            f0 = first.loc[x.run_key] if x.run_key in first.index else None
            ago = 0 if f0 is None else (x.t - f0.t).total_seconds() / 60
            if f0 is None or ago < 5:
                causes.append(
                    "only seen at one stop recently, so can't tell where the delay began")
            elif f0.delay_s >= 0.8 * a.late_s and f0.delay_s >= 0.7 * x.delay_s:
                causes.append(f"already {f0.delay_s / 60:.0f} min late {ago:.0f} min earlier, so the delay started "
                              f"before this part of the route")
            else:
                causes.append(
                    "delay built up gradually along the route, no single stretch stands out")
        w0 = w if w is not None else last[last.run_key == x.run_key].iloc[0]
        if bool(w0.is_rush):
            context.append("rush hour (already part of the usual delay)")
        if w0.precipitation is not None and w0.precipitation >= 2:
            context.append("heavy rain (no clear link to delay in the data)")
        rows.append(dict(run_key=x.run_key, route_id=str(x.route_id), at_stop=x.stop_id,
                         last_arrival_utc=x.t.strftime("%Y-%m-%d %H:%M:%S"), delay_min=round(x.delay_s / 60, 1),
                         usual_delay_min=None if pd.isna(
                             x.usual_delay_s) else round(x.usual_delay_s / 60, 1),
                         lost_s=None if np.isnan(lost) else round(lost), lost_at_stop=where,
                         why="; ".join(causes), context="; ".join(context)))
    out = pd.DataFrame(rows).sort_values(
        "delay_min", ascending=False) if rows else pd.DataFrame()

    if a.stops and Path(a.stops).exists() and len(out):
        sn = pd.read_parquet(
            a.stops, columns=["stop_id", "stop_name"]).drop_duplicates("stop_id")
        sn["stop_id"] = sn.stop_id.astype(str)
        for c in ["at_stop", "lost_at_stop"]:
            out[c + "_name"] = out[c].astype(str).map(
                sn.set_index("stop_id").stop_name)
    if a.routes and Path(a.routes).exists() and len(out):
        rt = pd.read_parquet(a.routes, columns=[
                             "route_id", "route_short_name"]).drop_duplicates("route_id")
        rt["route_id"] = rt.route_id.astype(str)
        out["route"] = out.route_id.map(
            rt.set_index("route_id").route_short_name)

    od = Path(a.out_dir)
    od.mkdir(parents=True, exist_ok=True)
    out.to_csv(od / "current_delays.csv", index=False)
    (od / "current_delays.json").write_text(json.dumps(
        {"as_of_utc": asof.strftime("%Y-%m-%dT%H:%M:%SZ"), "buses_seen": int(len(active)),
         "late_buses": json.loads(out.to_json(orient="records"))}, indent=1))
    if len(out):
        print("\n== latest late buses ==")
        for x in out.head(a.top).itertuples():
            name = getattr(x, "route", None) or x.route_id
            stop = getattr(x, "at_stop_name", None) or x.at_stop
            usual = "" if pd.isna(
                x.usual_delay_min) else f" (usually {x.usual_delay_min:.0f})"
            lost = "" if pd.isna(
                x.lost_s) else f" Lost {x.lost_s:.0f} s extra near {getattr(x, 'lost_at_stop_name', None) or x.lost_at_stop}."
            print(
                f"  route {name} at {stop}: {x.delay_min:.0f} min late{usual}.{lost} Why: {x.why}{' [' + x.context + ']' if x.context else ''}")
    print(f"\nwrote {od / 'current_delays.csv'} and current_delays.json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis-dir", required=True)
    ap.add_argument("--rw-dir", default=None,
                    help="roadworks_flag.py --out-dir (adds the road-works explanation)")
    ap.add_argument("--out-dir", default="out/current")
    ap.add_argument("--as-of", default=None,
                    help='UTC time, e.g. "2026-11-06 08:30" (default: newest arrival)')
    ap.add_argument("--window-min", type=float, default=30,
                    help="a bus counts if seen within this many minutes")
    ap.add_argument("--lookback-min", type=float, default=90,
                    help="how far back to look for where time was lost")
    ap.add_argument("--late-s", type=float, default=300,
                    help="late = this many seconds behind schedule")
    ap.add_argument("--lost-s", type=float, default=60,
                    help="a stretch counts as the cause if it lost this much")
    ap.add_argument("--works-min-s", type=float, default=30,
                    help="road works only count as the cause if buses usually lose at least this much there")
    ap.add_argument("--min-baseline", type=int, default=10)
    ap.add_argument("--sample", type=float, default=0.3)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--stops", default=None,
                    help="stops.parquet, to print stop names")
    ap.add_argument("--routes", default=None,
                    help="routes.parquet, to print route numbers")
    main(ap.parse_args())
