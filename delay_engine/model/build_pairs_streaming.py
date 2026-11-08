
#!/usr/bin/env python3

import argparse
import glob
import os
import sys
import warnings

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as F


MAX_STOPS_AHEAD = 15
DEFAULT_MAX_PAIRS = 2_000_000

# Smaller batches reduce peak Pandas memory usage.
RUN_CHUNK = 250


def sql_string(value):
    """Safely quote a path for DuckDB SQL."""
    return "'" + str(value).replace("'", "''") + "'"


def table_exists(con, name):
    """Check whether a table exists in the persistent DuckDB database."""
    result = con.execute("""
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_name = ?
    """, [name]).fetchone()

    return result[0] > 0


def prepare_database(con, weekly_files, gtfs_dir, rebuild=False):
    """
    Build the enriched arrivals table once.

    The DuckDB database is persisted to disk, so subsequent runs can
    reuse this table instead of rebuilding 35 million arrivals.
    """

    if table_exists(con, "arrivals") and not rebuild:
        print("\nReusing existing DuckDB arrivals table.")
        print("Use --rebuild-arrivals if the source data has changed.")

        result = con.execute("""
            SELECT
                COUNT(*),
                COUNT(DISTINCT run_id),
                MIN(actual_utc),
                MAX(actual_utc)
            FROM arrivals
        """).fetchone()

        print(f"Arrivals: {result[0]:,}")
        print(f"Runs: {result[1]:,}")
        print(f"Date range: {result[2]} to {result[3]}")
        return

    files_sql = "[" + ", ".join(
        sql_string(p) for p in weekly_files
    ) + "]"

    trips_path = sql_string(
        os.path.join(gtfs_dir, "trips.parquet")
    )
    stops_path = sql_string(
        os.path.join(gtfs_dir, "stops.parquet")
    )
    times_path = sql_string(
        os.path.join(gtfs_dir, "stop_times.parquet")
    )

    print("\nBuilding archive arrivals table in DuckDB...")
    print("This calculates run history and headways across weekly-file boundaries.")
    print("This may take some time on the first run.")

    query = f"""
    CREATE OR REPLACE TABLE arrivals AS

    WITH raw AS (
        SELECT
            CAST(service_date AS VARCHAR) AS service_date,

            COALESCE(CAST(operator_ref AS VARCHAR), '') AS operator_ref,
            COALESCE(CAST(vehicle_ref AS VARCHAR), 'nan') AS vehicle_ref,
            COALESCE(CAST(trip_id AS VARCHAR), 'nan') AS trip_id,

            COALESCE(CAST(line AS VARCHAR), 'nan') AS route_short_name,

            CAST(stop_sequence AS BIGINT) AS stop_sequence,
            CAST(stop_idx AS BIGINT) AS stop_idx,
            CAST(stop_id AS VARCHAR) AS stop_id,

            CAST(stop_lat AS DOUBLE) AS stop_lat,
            CAST(stop_lon AS DOUBLE) AS stop_lon,
            CAST(delay_s AS DOUBLE) AS delay_s,

            sched_arr_utc AS scheduled_utc,
            actual_arr_utc AS actual_utc

        FROM read_parquet({files_sql}, union_by_name=true)

        WHERE actual_arr_utc IS NOT NULL
          AND sched_arr_utc IS NOT NULL
          AND delay_s IS NOT NULL
    ),

    trip_ends AS (
        SELECT
            trip_id,
            MIN(stop_sequence) AS min_sequence,
            MAX(stop_sequence) AS max_sequence
        FROM read_parquet({times_path})
        GROUP BY trip_id
    ),

    base AS (
        SELECT
            r.*,

            r.service_date || '|' ||
                r.operator_ref || '|' ||
                r.vehicle_ref || '|' ||
                r.trip_id AS run_id,

            COALESCE(
                CAST(t.direction_id AS VARCHAR),
                'nan'
            ) AS direction_id,

            COALESCE(s.stop_name, r.stop_id) AS stop_name,

            CASE
                WHEN r.stop_sequence = e.min_sequence THEN 1
                ELSE 0
            END AS is_first_stop,

            CASE
                WHEN r.stop_sequence = e.max_sequence THEN 1
                ELSE 0
            END AS is_last_stop

        FROM raw r

        LEFT JOIN read_parquet({trips_path}) t
            ON r.trip_id = t.trip_id

        LEFT JOIN read_parquet({stops_path}) s
            ON r.stop_id = s.stop_id

        LEFT JOIN trip_ends e
            ON r.trip_id = e.trip_id
    ),

    sequenced AS (
        SELECT
            *,

            LAG(delay_s) OVER (
                PARTITION BY run_id
                ORDER BY stop_sequence
            ) AS previous_delay_s,

            LAG(stop_idx) OVER (
                PARTITION BY run_id
                ORDER BY stop_sequence
            ) AS previous_stop_idx,

            LAG(actual_utc) OVER (
                PARTITION BY route_short_name, direction_id, stop_id
                ORDER BY actual_utc
            ) AS previous_actual_utc,

            LAG(scheduled_utc) OVER (
                PARTITION BY route_short_name, direction_id, stop_id
                ORDER BY actual_utc
            ) AS previous_scheduled_utc

        FROM base
    )

    SELECT
        run_id,
        service_date,
        route_short_name,
        direction_id,
        stop_id,
        stop_name,
        stop_sequence,
        stop_idx,
        stop_lat,
        stop_lon,
        scheduled_utc,
        actual_utc,
        delay_s,
        is_first_stop,
        is_last_stop,

        CASE
            WHEN previous_stop_idx IS NOT NULL
             AND stop_idx = previous_stop_idx + 1
            THEN delay_s - previous_delay_s
            ELSE NULL
        END AS added_delay_s,

        CASE
            WHEN previous_actual_utc IS NOT NULL
            THEN DATE_DIFF(
                'microsecond',
                previous_actual_utc,
                actual_utc
            ) / 1000000.0
            ELSE NULL
        END AS gap_ahead_s,

        CASE
            WHEN previous_scheduled_utc IS NOT NULL
            THEN DATE_DIFF(
                'microsecond',
                previous_scheduled_utc,
                scheduled_utc
            ) / 1000000.0
            ELSE NULL
        END AS scheduled_gap_s,

        CASE
            WHEN previous_scheduled_utc IS NOT NULL
             AND previous_actual_utc IS NOT NULL
             AND scheduled_utc > previous_scheduled_utc
            THEN
                (
                    DATE_DIFF(
                        'microsecond',
                        previous_actual_utc,
                        actual_utc
                    ) / 1000000.0
                )
                /
                (
                    DATE_DIFF(
                        'microsecond',
                        previous_scheduled_utc,
                        scheduled_utc
                    ) / 1000000.0
                )
            ELSE NULL
        END AS headway_ratio

    FROM sequenced
    """

    con.execute(query)

    print("Creating service-date index...")
    con.execute("""
        CREATE INDEX IF NOT EXISTS arrivals_date_idx
        ON arrivals(service_date)
    """)

    result = con.execute("""
        SELECT
            COUNT(*),
            COUNT(DISTINCT run_id),
            MIN(actual_utc),
            MAX(actual_utc)
        FROM arrivals
    """).fetchone()

    print(f"Arrivals: {result[0]:,}")
    print(f"Runs: {result[1]:,}")
    print(f"Date range: {result[2]} to {result[3]}")
    print("Arrivals table saved in the DuckDB database.")


def count_all_pairs(con):
    """Count possible forward pairs, excluding first and last stops."""

    query = f"""
        SELECT COALESCE(
            SUM(GREATEST(n - ahead, 0)),
            0
        )
        FROM (
            SELECT
                service_date,
                run_id,
                COUNT(*) AS n
            FROM arrivals
            WHERE is_first_stop = 0
              AND is_last_stop = 0
            GROUP BY service_date, run_id
        ) runs
        CROSS JOIN range(1, {MAX_STOPS_AHEAD + 1}) AS offsets(ahead)
    """

    return int(con.execute(query).fetchone()[0])


def make_pairs_for_runs(sa):
    """
    Generate forward stop pairs using group shifts.

    Input must contain only eligible (non-terminus) stops and must
    be sorted by run_id and stop_sequence.
    """

    if sa.empty:
        return pd.DataFrame()

    sa = sa.sort_values(
        ["run_id", "stop_sequence"]
    ).reset_index(drop=True)

    left_columns = [
        "run_id",
        "route_short_name",
        "direction_id",
        "stop_id",
        "now_utc",
        "scheduled_utc",
        "delay_s",
        "gap_ahead_s",
        "headway_ratio",
        "recent_route_delay_s",
        "recent_added_delay_s",
    ]

    right_columns = [
        "stop_id",
        "scheduled_utc",
        "actual_utc",
        "delay_s",
        "stop_lat",
        "stop_lon",
    ]

    left_names = {
        "stop_id": "from_stop",
        "scheduled_utc": "sched_from",
        "delay_s": "delay_now_s",
        "route_short_name": "route",
        "direction_id": "direction",
    }

    right_names = {
        "stop_id": "to_stop",
        "scheduled_utc": "sched_to",
        "actual_utc": "actual_to",
        "delay_s": "target_delay_s",
        "stop_lat": "to_lat",
        "stop_lon": "to_lon",
    }

    grouped = sa.groupby("run_id", sort=False)

    positions = grouped.cumcount()
    sizes = grouped["run_id"].transform("size")

    parts = []

    for ahead in range(1, MAX_STOPS_AHEAD + 1):

        valid = positions + ahead < sizes

        if not valid.any():
            continue

        shifted = grouped[right_columns].shift(-ahead)

        left = (
            sa.loc[valid, left_columns]
            .rename(columns=left_names)
            .reset_index(drop=True)
        )

        right = (
            shifted.loc[valid]
            .rename(columns=right_names)
            .reset_index(drop=True)
        )

        pairs = pd.concat([left, right], axis=1)

        pairs["stops_ahead"] = ahead

        pairs["sched_travel_s"] = (
            pairs["sched_to"] - pairs["sched_from"]
        ).dt.total_seconds()

        pairs = pairs.drop(columns=["sched_from"])

        parts.append(pairs)

    if not parts:
        return pd.DataFrame()

    return pd.concat(parts, ignore_index=True)


def process_service_date(
    con,
    service_date,
    fraction,
    rng,
    context_hourly,
    events,
    writer_state,
    output_temp,
    max_remaining,
):
    """
    Process one service date, using the preceding 30 minutes
    for rolling live features.
    """

    day_min = con.execute(
        """
        SELECT MIN(actual_utc)
        FROM arrivals
        WHERE service_date = ?
        """,
        [service_date],
    ).fetchone()[0]

    if day_min is None:
        return 0

    history_start = day_min - pd.Timedelta(minutes=30)

    # The current service date plus its preceding 30 minutes.
    window = con.execute("""
        SELECT *
        FROM arrivals
        WHERE service_date = ?
           OR (
                actual_utc >= CAST(? AS TIMESTAMPTZ_NS)
                AND actual_utc < CAST(? AS TIMESTAMPTZ_NS)
           )
        ORDER BY run_id, stop_sequence
    """, [
        service_date,
        history_start,
        day_min,
    ]).fetchdf()

    if window.empty:
        return 0

    # DuckDB can return timezone-naive Pandas timestamps.
    # All source timestamps represent UTC, so explicitly restore UTC.
    for column in ("actual_utc", "scheduled_utc"):
        window[column] = pd.to_datetime(
            window[column],
            utc=True,
        )

    day = window[
        window["service_date"] == service_date
    ].copy()

    # Exclude termini from both starting and target stops.
    day = day[
        (day["is_first_stop"] == 0)
        & (day["is_last_stop"] == 0)
    ].copy()

    if day.empty:
        return 0

    day = day.sort_values(
        ["run_id", "stop_sequence"]
    ).reset_index(drop=True)

    # IMPORTANT:
    # Keep the starting timestamp as now_utc.
    # Keep a separate copy of the same timestamp for target calculations.
    #
    # Do not retain a column called actual_utc in this dataframe:
    # add_live_features uses actual_utc as the right-hand merge key.
    live_input = day.rename(
        columns={"actual_utc": "now_utc"}
    ).copy()

    live_input["target_actual_utc"] = live_input["now_utc"]

    # features.py expects route and direction, while the original
    # arrival columns must remain available for pair generation.
    live_input["route"] = live_input["route_short_name"]
    live_input["direction"] = live_input["direction_id"]

    live_starts = F.add_live_features(
        live_input,
        window,
        "now_utc",
    )

    # Restore the original arrival time under the name expected by
    # make_pairs_for_runs, without colliding with merge_asof.
    live_starts = live_starts.rename(
        columns={"target_actual_utc": "actual_utc"}
    )

    live_starts = live_starts.sort_values(
        ["run_id", "stop_sequence"]
    ).reset_index(drop=True)

    run_ids = (
        live_starts["run_id"]
        .drop_duplicates()
        .to_numpy()
    )

    written = 0

    for start in range(0, len(run_ids), RUN_CHUNK):

        if written >= max_remaining:
            break

        batch_ids = run_ids[start:start + RUN_CHUNK]

        starts = live_starts[
            live_starts["run_id"].isin(batch_ids)
        ].copy()

        starts = starts.sort_values(
            ["run_id", "stop_sequence"]
        ).reset_index(drop=True)

        pairs = make_pairs_for_runs(starts)

        if pairs.empty:
            continue

        # Randomly sample pairs across the archive.
        if fraction < 1:
            keep = rng.random(len(pairs)) < fraction
            pairs = pairs.loc[keep].reset_index(drop=True)

        if pairs.empty:
            continue

        # Enforce the requested maximum, including sampling variation.
        remaining = max_remaining - written

        if len(pairs) > remaining:
            selected = rng.choice(
                len(pairs),
                size=remaining,
                replace=False,
            )
            pairs = pairs.iloc[selected].reset_index(drop=True)

        if pairs.empty:
            continue

        pairs = F.add_time_features(
            pairs,
            "now_utc",
        )

        pairs = F.add_hourly_context(
            pairs,
            context_hourly,
            "now_utc",
        )

        pairs = F.add_events(
            pairs,
            events,
            "now_utc",
        )

        # Float32 is sufficient for the numerical model features.
        for column in pairs.select_dtypes("float64").columns:
            pairs[column] = pairs[column].astype("float32")

        table = pa.Table.from_pandas(
            pairs,
            preserve_index=False,
        )

        if writer_state["writer"] is None:

            writer_state["schema"] = table.schema

            writer_state["writer"] = pq.ParquetWriter(
                output_temp,
                writer_state["schema"],
                compression="snappy",
            )

        else:
            # Keep the output schema consistent across service dates.
            table = table.select(
                writer_state["schema"].names
            )

            table = table.cast(
                writer_state["schema"],
                safe=False,
            )

        writer_state["writer"].write_table(
            table,
            row_group_size=100_000,
        )

        written += len(pairs)

        del pairs, table

    return written


def main():

    parser = argparse.ArgumentParser(
        description="Build training pairs from the historical BODS archive."
    )

    parser.add_argument(
        "--weekly-dir",
        default="/tmp/bods_batches_working_copy",
    )

    parser.add_argument(
        "--gtfs",
        default="data/",
    )

    parser.add_argument(
        "--context",
        default="delay_engine/archival_data/data",
    )

    parser.add_argument(
        "--out",
        default="/tmp/archive_pairs.parquet",
    )

    parser.add_argument(
        "--max-pairs",
        type=int,
        default=DEFAULT_MAX_PAIRS,
    )

    parser.add_argument(
        "--memory-limit",
        default="1GB",
    )

    parser.add_argument(
        "--database",
        default="/tmp/bods_archive.duckdb",
        help="Persistent DuckDB database used to cache enriched arrivals.",
    )

    parser.add_argument(
        "--rebuild-arrivals",
        action="store_true",
        help="Force rebuilding the arrivals table from the weekly Parquet files.",
    )

    args = parser.parse_args()

    if args.max_pairs < 1:
        parser.error("--max-pairs must be at least 1")

    weekly_files = sorted(
        glob.glob(
            os.path.join(
                args.weekly_dir,
                "week_*",
                "stop_arrivals.parquet",
            )
        )
    )

    if not weekly_files:
        raise FileNotFoundError(
            f"No weekly arrivals found in {args.weekly_dir}"
        )

    for path in (
        os.path.join(args.gtfs, "trips.parquet"),
        os.path.join(args.gtfs, "stops.parquet"),
        os.path.join(args.gtfs, "stop_times.parquet"),
    ):
        if not os.path.exists(path):
            raise FileNotFoundError(f"Missing GTFS file: {path}")

    context_hourly_path = os.path.join(
        args.context,
        "context_hourly.parquet",
    )

    events_path = os.path.join(
        args.context,
        "events.csv",
    )

    print("=" * 65)
    print("STREAMING ARCHIVE PAIR GENERATION")
    print("=" * 65)

    print(f"Weekly files: {len(weekly_files)}")
    print(f"Maximum pairs: {args.max_pairs:,}")
    print(f"DuckDB database: {args.database}")

    temp_dir = "/tmp/duckdb_spill"
    os.makedirs(temp_dir, exist_ok=True)

    output_dir = os.path.dirname(args.out) or "."
    os.makedirs(output_dir, exist_ok=True)

    database_dir = os.path.dirname(args.database)

    if database_dir:
        os.makedirs(database_dir, exist_ok=True)

    output_temp = args.out + ".tmp"

    if os.path.exists(output_temp):
        os.remove(output_temp)

    # Do not delete an existing successful output here.
    # It is replaced only after the new output has completed.

    con = duckdb.connect(args.database)

    con.execute(f"SET memory_limit = '{args.memory_limit}'")
    con.execute(f"SET temp_directory = '{temp_dir}'")
    con.execute("SET preserve_insertion_order = false")
    con.execute("SET threads = 2")

    writer_state = {
        "writer": None,
        "schema": None,
    }

    try:

        prepare_database(
            con,
            weekly_files,
            args.gtfs,
            rebuild=args.rebuild_arrivals,
        )

        print("\nCounting possible training pairs...")

        total_pairs = count_all_pairs(con)

        print(f"Possible pairs: {total_pairs:,}")

        if total_pairs == 0:
            raise ValueError("No valid training pairs found.")

        fraction = min(
            1.0,
            args.max_pairs / total_pairs,
        )

        print(f"Sampling fraction: {fraction:.4%}")

        rng = np.random.default_rng(42)

        dates = [
            row[0]
            for row in con.execute("""
                SELECT DISTINCT service_date
                FROM arrivals
                ORDER BY service_date
            """).fetchall()
        ]

        context_hourly = F.load_context_hourly(
            context_hourly_path
        )

        events = F.load_events(
            events_path
        )

        print(f"\nProcessing {len(dates)} service dates...")

        total_written = 0

        for index, service_date in enumerate(dates, start=1):

            if total_written >= args.max_pairs:
                break

            print(
                f"\n[{index}/{len(dates)}] "
                f"Service date: {service_date}",
                flush=True,
            )

            written = process_service_date(
                con=con,
                service_date=service_date,
                fraction=fraction,
                rng=rng,
                context_hourly=context_hourly,
                events=events,
                writer_state=writer_state,
                output_temp=output_temp,
                max_remaining=args.max_pairs - total_written,
            )

            total_written += written

            print(
                f"Pairs written: {written:,} "
                f"(archive total: {total_written:,})",
                flush=True,
            )

        if writer_state["writer"] is not None:
            writer_state["writer"].close()
            writer_state["writer"] = None

        if total_written == 0:
            raise ValueError("No training pairs were written.")

        # Only replace the previous output after successful completion.
        os.replace(output_temp, args.out)

        print("\n" + "=" * 65)
        print("PAIR GENERATION COMPLETE")
        print("=" * 65)
        print(f"Total pairs: {total_written:,}")
        print(f"Output: {args.out}")
        print(f"DuckDB cache: {args.database}")

    except Exception:

        if writer_state["writer"] is not None:
            writer_state["writer"].close()
            writer_state["writer"] = None

        if os.path.exists(output_temp):
            os.remove(output_temp)

        raise

    finally:
        con.close()


if __name__ == "__main__":
    main()
