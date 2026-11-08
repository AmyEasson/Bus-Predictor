"""Step 10: export small lookup tables from the archive analysis for the backend API.

The analysis tables (archival_data/build_analysis.py output) are ~1 GB, far too big to query per request.
This boils them down into a few small files in --out-dir (default: ../backend/data/delay):

  segments.parquet       one row per stretch (stop A -> next stop B) x day type x local hour, n >= --min-n:
                           late_med_s      median lateness at B (how far behind timetable buses are there)
                           added_med_s / added_p90_s   delay gained on the stretch itself
                           late_allday_s   median lateness at B over all hours (same day type)
                           rain_effect_s   mean extra delay gained on the stretch when it rains (>= 0.5 mm/h),
                                           vs dry, both measured against the stretch's own hour normal
                           event_effect_s  same, for an event within --venue-km being on (2 h before to 2 h after)
                           (effects are NaN when there are fewer than --min-cond observations in the condition)
                           plus stop names, coordinates and the route numbers that use the stretch
  stop_typical.parquet   typical lateness of buses arriving at each stop, by day type x local hour (n >= 10):
                         the backend's estimate of "how late is the bus when you board" for the delay model
  network_hourly.parquet one row per day type x local hour: pct on time (-1 to +5 min, UK convention),
                         pct >5 min late, mean delay, and how many buses are >5 min late in that hour on a typical day
  route_reliability.csv, route_reliability_by_band.csv   copied from archival_data/route_reliability.py output
  current_delays.json    copied from archival_data/current_delays.py output
  events.csv             copied from --events (venue, time, attendance), for "what's on" on the map
  meta.json              data window, row counts, and network-wide factor effects from the correlation and
                         road-works tables (for the factor descriptions in the UI)

First stops of each run are left out of lateness numbers (buses waiting at the terminus look late or early).

Usage (from delay_engine/):
  python3 export_for_api.py --analysis-dir trip_matching/out/analysis --gtfs-dir ../data \\
      --results-dir trip_matching/out [--out-dir ../backend/data/delay]
Needs duckdb (in requirements.txt). Built to fit in ~2 GB of RAM: it works one day / one slice of\nstretches at a time and keeps its scratch tables on disk in --tmp-dir.
"""
import argparse
import json
import shutil
import tempfile
from pathlib import Path

import duckdb
import pandas as pd


def q(path):
    """Quote a path as a SQL string literal."""
    return "'" + str(path).replace("'", "''") + "'"


def slim_days(con, a, tmp):
    """Per day file: keep the columns we need and add the previous stop on the same run.
    One day at a time, because a window over all 69 days at once needs far more memory than a laptop has.
    (A run never spans two files: run_key includes the service date.)"""
    files = sorted(Path(a.analysis_dir).glob("analysis_*.parquet"))
    if not files:
        raise SystemExit(f"no analysis_*.parquet in {a.analysis_dir}")
    for i, f in enumerate(files, 1):
        con.execute(f"""
            COPY (
                SELECT run_key, CAST(route_id AS VARCHAR) AS route_id, stop_sequence, stop_id, stop_lat, stop_lon,
                       delay_s, delay_added_s, is_weekend, hour, precipitation,
                       CAST(ev_phase AS VARCHAR) AS ev_phase, ev_dist_km,
                       CAST(timezone('Europe/London', actual_arr_utc) AS DATE) AS local_day,
                       LAG(stop_id)  OVER w AS from_stop_id,
                       LAG(stop_lat) OVER w AS from_lat,
                       LAG(stop_lon) OVER w AS from_lon
                FROM read_parquet({q(f)})
                WINDOW w AS (PARTITION BY run_key ORDER BY stop_sequence)
            ) TO {q(Path(tmp) / f"arr_{f.stem.split('_')[1]}.parquet")} (FORMAT parquet)
        """)
        print(f"\r  slimmed {i}/{len(files)} days", end="", flush=True)
    print()


def build_tables(con, a, tmp):
    slim_days(con, a, tmp)
    con.execute(f"CREATE VIEW arr AS SELECT * FROM read_parquet({q(Path(tmp) / 'arr_*.parquet')})")

    # usable stretches only (build_analysis already applied the adjacency and quality filters)
    con.execute("""
        CREATE TABLE st AS
        SELECT * EXCLUDE (local_day) FROM arr WHERE delay_added_s IS NOT NULL AND from_stop_id IS NOT NULL
    """)

    def bucketed(name, body):
        """Exact medians must hold every value of every group in memory at once, which doesn't fit.
        So build each table in --buckets passes, each over a slice of stretches (by from-stop hash).
        `body` reads from `sb` (this pass's slice of st) and may add more CTEs after it."""
        for i in range(a.buckets):
            head = f"CREATE TABLE {name} AS" if i == 0 else f"INSERT INTO {name}"
            body_sql = body.lstrip()
            sb = f"sb AS (SELECT * FROM st WHERE hash(from_stop_id) % {a.buckets} = {i})"
            # merge our CTE with the body's own WITH clause, if it has one
            if body_sql.upper().startswith("WITH "):
                sql = f"{head} WITH {sb}, {body_sql[5:]}"
            else:
                sql = f"{head} WITH {sb} {body_sql}"
            con.execute(sql)

    bucketed("seg", """
        SELECT from_stop_id, stop_id AS to_stop_id, is_weekend, hour,
               count(*) AS n,
               median(delay_s) AS late_med_s,
               median(delay_added_s) AS added_med_s,
               quantile_cont(delay_added_s, 0.9) AS added_p90_s
        FROM sb GROUP BY ALL
    """)

    # condition effects: excess = delay gained minus that stretch's normal for the same hour and day type
    bucketed("eff", f"""
        WITH x AS (
            SELECT sb.from_stop_id, sb.stop_id AS to_stop_id, sb.is_weekend,
                   sb.delay_added_s - seg.added_med_s AS excess,
                   coalesce(sb.precipitation >= 0.5, false) AS wet,
                   sb.ev_phase IS NOT NULL AND sb.ev_dist_km <= {a.venue_km} AS near_event,
                   sb.ev_phase IS NULL AS no_event
            FROM sb JOIN seg ON sb.from_stop_id = seg.from_stop_id AND sb.stop_id = seg.to_stop_id
                           AND sb.is_weekend = seg.is_weekend AND sb.hour = seg.hour
            WHERE seg.n >= {a.min_n}
        )
        SELECT from_stop_id, to_stop_id, is_weekend,
               CASE WHEN count(*) FILTER (wet) >= {a.min_cond} AND count(*) FILTER (NOT wet) >= {a.min_cond}
                    THEN avg(excess) FILTER (wet) - avg(excess) FILTER (NOT wet) END AS rain_effect_s,
               CASE WHEN count(*) FILTER (near_event) >= {a.min_cond} AND count(*) FILTER (no_event) >= {a.min_cond}
                    THEN avg(excess) FILTER (near_event) - avg(excess) FILTER (no_event) END AS event_effect_s
        FROM x GROUP BY ALL
    """)

    bucketed("allday", """
        SELECT from_stop_id, stop_id AS to_stop_id, is_weekend, median(delay_s) AS late_allday_s
        FROM sb GROUP BY ALL
    """)

    routes = q(Path(a.gtfs_dir) / "routes.parquet")
    con.execute(f"""
        CREATE TABLE route_names AS
        SELECT CAST(route_id AS VARCHAR) AS route_id, any_value(route_short_name) AS route_short_name
        FROM read_parquet({routes}) GROUP BY ALL
    """)
    bucketed("lines", """
        SELECT from_stop_id, sb.stop_id AS to_stop_id,
               string_agg(DISTINCT coalesce(r.route_short_name, sb.route_id), ',') AS lines,
               count(DISTINCT sb.route_id) AS n_lines,
               any_value(from_lat) AS from_lat, any_value(from_lon) AS from_lon,
               any_value(stop_lat) AS to_lat, any_value(stop_lon) AS to_lon
        FROM sb LEFT JOIN route_names r USING (route_id)
        GROUP BY ALL
    """)

    stops = q(Path(a.gtfs_dir) / "stops.parquet")
    segments = con.execute(f"""
        WITH names AS (SELECT CAST(stop_id AS VARCHAR) AS stop_id, any_value(stop_name) AS stop_name
                       FROM read_parquet({stops}) GROUP BY ALL)
        SELECT seg.from_stop_id, seg.to_stop_id, fn.stop_name AS from_name, tn.stop_name AS to_name,
               l.from_lat, l.from_lon, l.to_lat, l.to_lon, l.lines, l.n_lines,
               seg.is_weekend::TINYINT AS is_weekend, seg.hour::TINYINT AS hour, seg.n::INTEGER AS n,
               seg.late_med_s::FLOAT AS late_med_s, ad.late_allday_s::FLOAT AS late_allday_s,
               seg.added_med_s::FLOAT AS added_med_s, seg.added_p90_s::FLOAT AS added_p90_s,
               eff.rain_effect_s::FLOAT AS rain_effect_s, eff.event_effect_s::FLOAT AS event_effect_s
        FROM seg
        JOIN lines l USING (from_stop_id, to_stop_id)
        LEFT JOIN allday ad USING (from_stop_id, to_stop_id, is_weekend)
        LEFT JOIN eff USING (from_stop_id, to_stop_id, is_weekend)
        LEFT JOIN names fn ON fn.stop_id = seg.from_stop_id
        LEFT JOIN names tn ON tn.stop_id = seg.to_stop_id
        WHERE seg.n >= {a.min_n}
        ORDER BY from_stop_id, to_stop_id, is_weekend, hour
    """).df()

    network = con.execute("""
        WITH a AS (SELECT * FROM arr WHERE from_stop_id IS NOT NULL),   -- not the first stop of a run
        lat AS (
            SELECT is_weekend, hour,
                   count(*) AS n,
                   100 * avg(CASE WHEN delay_s >= -60 AND delay_s < 300 THEN 1 ELSE 0 END) AS pct_on_time,
                   100 * avg(CASE WHEN delay_s >= 300 THEN 1 ELSE 0 END) AS pct_late_5min,
                   avg(delay_s) / 60 AS avg_delay_min,
                   median(delay_added_s) AS added_med_s   -- typical delay gained per stop (model input proxy)
            FROM a GROUP BY ALL
        ),
        per_day AS (
            SELECT local_day, is_weekend, hour, count(DISTINCT run_key) FILTER (delay_s >= 300) AS late_runs,
                   count(DISTINCT run_key) AS runs
            FROM a GROUP BY ALL
        ),
        typical AS (
            SELECT is_weekend, hour, avg(late_runs) AS late_buses, avg(runs) AS buses
            FROM per_day GROUP BY ALL
        )
        SELECT lat.is_weekend::TINYINT AS is_weekend, lat.hour::TINYINT AS hour, lat.n::INTEGER AS n,
               lat.pct_on_time::FLOAT AS pct_on_time, lat.pct_late_5min::FLOAT AS pct_late_5min,
               lat.avg_delay_min::FLOAT AS avg_delay_min,
               typical.late_buses::FLOAT AS late_buses, typical.buses::FLOAT AS buses,
               lat.added_med_s::FLOAT AS added_med_s
        FROM lat JOIN typical USING (is_weekend, hour)
        ORDER BY is_weekend, hour
    """).df()

    # Typical lateness of buses ARRIVING at each stop (not their first stop) by day type and hour. This is the
    # backend's best estimate of "how late is the bus when you board" for a future trip, the model's main input.
    # On held-out days it cuts the error of that input by ~18% vs assuming the bus is on time.
    stop_typical = bucketed_df(con, a, """
        SELECT stop_id, is_weekend::TINYINT AS is_weekend, hour::TINYINT AS hour, count(*)::INTEGER AS n,
               median(delay_s)::FLOAT AS late_med_s
        FROM sa WHERE from_stop_id IS NOT NULL GROUP BY ALL HAVING count(*) >= 10
    """, table="arr", key="stop_id")

    window = con.execute("""
        SELECT min(local_day), max(local_day), count(DISTINCT local_day), count(*),
               (SELECT count(*) FROM st) FROM arr
    """).fetchone()
    return segments, network, stop_typical, window


def bucketed_df(con, a, body, table, key):
    """Run an aggregate over `table` in --buckets slices of `key` (exact medians don't fit in memory at once).
    `body` reads from `sa`."""
    parts = []
    for i in range(a.buckets):
        parts.append(con.execute(
            f"WITH sa AS (SELECT * FROM {table} WHERE hash({key}) % {a.buckets} = {i}) {body}").df())
    return pd.concat(parts, ignore_index=True)


def read_effects(results):
    """Network-wide effects already measured by correlations.py and roadworks_flag.py (mean excess, seconds)."""
    out = {}
    def table(path, key):
        p = results / path
        if p.exists():
            t = pd.read_csv(p)
            out[key] = t.round(1).to_dict(orient="records")
    table("correlations/rain.csv", "rain")
    table("correlations/near_venue_1.5km_by_phase.csv", "events_near_venue")
    table("correlations/bank_holiday.csv", "bank_holiday")
    table("correlations/school_term.csv", "school_term")
    table("roadworks/blocking_vs_other.csv", "roadworks")
    return out


def main(a):
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results = Path(a.results_dir)

    # scratch space on real disk (not /tmp, which is often a small RAM-backed filesystem)
    Path(a.tmp_dir).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=a.tmp_dir) as tmp:
        con = duckdb.connect(str(Path(tmp) / "work.duckdb"))  # on disk, so big tables can page out
        con.execute(f"SET memory_limit = '{a.memory}'")
        con.execute(f"SET threads = {a.threads}")
        con.execute(f"SET temp_directory = {q(Path(tmp) / 'spill')}")
        con.execute("SET preserve_insertion_order = false")
        segments, network, stop_typical, window = build_tables(con, a, tmp)
        con.close()

    segments.to_parquet(out / "segments.parquet", index=False, compression="zstd")
    network.to_parquet(out / "network_hourly.parquet", index=False)
    stop_typical.to_parquet(out / "stop_typical.parquet", index=False, compression="zstd")

    copied = []
    for src in ["reliability/route_reliability.csv", "reliability/route_reliability_by_band.csv",
                "current/current_delays.json"]:
        p = results / src
        if p.exists():
            shutil.copy(p, out / p.name)
            copied.append(p.name)
        else:
            print(f"  (skipped {p}: not found - run the script that makes it first)")
    if Path(a.events).exists():   # event calendar, so the map can show what's on today
        shutil.copy(a.events, out / "events.csv")
        copied.append("events.csv")

    if Path(a.permits).exists():   # road works on now / planned, with their measured or typical effect
        from export_roadworks import export as export_roadworks
        export_roadworks(a.permits, results / "roadworks", out)
        copied.append("roadworks")
    else:
        print(f"  (skipped road works: {a.permits} not found)")

    first, last, days, n_arr, n_st = window
    meta = {
        "data_from": str(first), "data_to": str(last), "days": int(days),
        "arrivals": int(n_arr), "stretch_observations": int(n_st),
        "segments": int(len(segments)), "unique_stretches": int(segments[["from_stop_id", "to_stop_id"]]
                                                               .drop_duplicates().shape[0]),
        "min_n": a.min_n, "venue_km": a.venue_km,
        "effects": read_effects(results),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1))

    print(f"data {first} to {last} ({days} days): {n_arr:,} arrivals, {n_st:,} stretch observations")
    print(f"segments.parquet: {len(segments):,} rows ({meta['unique_stretches']:,} stretches)"
          f" | network_hourly.parquet: {len(network)} rows | copied: {', '.join(copied) or 'nothing'}")
    print(f"wrote {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis-dir", required=True)
    ap.add_argument("--gtfs-dir", required=True, help="folder with stops.parquet and routes.parquet")
    ap.add_argument("--results-dir", default="trip_matching/out",
                    help="folder holding correlations/, roadworks/, reliability/, current/")
    ap.add_argument("--out-dir", default="../backend/data/delay")
    ap.add_argument("--min-n", type=int, default=10, help="observations needed per stretch x day type x hour")
    ap.add_argument("--min-cond", type=int, default=20,
                    help="observations needed in a condition (rain / event) to estimate its effect on a stretch")
    ap.add_argument("--venue-km", type=float, default=1.5)
    ap.add_argument("--events", default="archival_data/data/events.csv")
    ap.add_argument("--permits", default="trip_matching/out/permits_full/roadworks_gm.parquet",
                    help="Street Manager permit events (filter_roadworks.py output), for export_roadworks.py")
    ap.add_argument("--memory", default="1500MB", help="duckdb memory limit; it spills to disk beyond this")
    ap.add_argument("--threads", type=int, default=4, help="fewer threads = less memory")
    ap.add_argument("--buckets", type=int, default=8, help="more buckets = less memory for the median steps")
    ap.add_argument("--tmp-dir", default="trip_matching/out/_export_tmp",
                    help="scratch folder on disk (cleaned up afterwards)")
    main(ap.parse_args())
