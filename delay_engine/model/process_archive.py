#!/usr/bin/env python3

"""
Process the full BODS historical archive in weekly batches.

Pipeline:
1. Discover daily archive files.
2. Process them in seven-day windows (every Greater Manchester bus route by default).
3. Reuse previously completed batches.
4. Extract stop arrivals (weeks where nothing matches the timetable are skipped, not crashed).
5. Record batch and route coverage.
6. Build training pairs straight from the weekly files (one week in memory at a time - the
   whole network is far too big to combine into one table in memory).
7. Optionally train a separate archive model.

Run from the project root:

    python3 delay_engine/model/process_archive.py --skip-training

Then, after checking the generated data:

    python3 delay_engine/model/process_archive.py
"""

import argparse
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]

ARCHIVE = ROOT / "bods_archive"
GTFS = ROOT / "data"
# Context (weather/calendar/events): the archival_data folder if it exists, otherwise context/
CONTEXT = ROOT / "delay_engine" / "archival_data" / "data"
if not (CONTEXT / "context_hourly.parquet").exists() and (ROOT / "context").exists():
    CONTEXT = ROOT / "context"

ARCHIVE_SCRIPT = ROOT / "delay_engine" / "trip_matching" / "archive_to_inputs.py"
ARRIVALS_SCRIPT = ROOT / "delay_engine" / "trip_matching" / "arrivals.py"
PAIRS_SCRIPT = ROOT / "delay_engine" / "model" / "build_pairs.py"
TRAIN_SCRIPT = ROOT / "delay_engine" / "model" / "train.py"

WORK = Path("/tmp/bods_batches_working_copy")

COMBINED_PAIRS = Path("/tmp/archive_pairs.parquet")

MODEL_OUTPUT = ROOT / "delay_engine" / "model" / "models_archive"

REPORT = WORK / "archive_processing_report.csv"
ROUTE_REPORT = WORK / "archive_route_coverage.csv"


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

# "all" = every bus route in Greater Manchester (archive_to_inputs.py filters out other towns'
# routes that share a number, e.g. Warrington's 43). Or a comma-separated list of route numbers.
LINES = "all"

DEFAULT_MAX_PAIRS = 3_000_000


# ---------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------

def run(command):
    """Run a command and stop if it fails."""
    print("\n>", " ".join(map(str, command)), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def archive_date(path):
    """Extract the date from gm_YYYYMMDD.parquet."""
    try:
        return datetime.strptime(
            path.stem.replace("gm_", ""),
            "%Y%m%d"
        ).date()
    except ValueError:
        return None


def discover_archive():
    """Find all valid daily archive files."""
    files = []

    for path in ARCHIVE.glob("gm_*.parquet"):
        date = archive_date(path)

        if date is not None:
            files.append((date, path))

    return sorted(files)


BATCH_DAYS = 7     # set from --days-per-batch in main()


def batch_folder_name(start):
    """week_YYYYMMDD for 7-day batches (the original names), batch_YYYYMMDD_Nd otherwise, so
    batches of different lengths never get mixed up when outputs are reused."""
    if BATCH_DAYS == 7:
        return f"week_{start.strftime('%Y%m%d')}"
    return f"batch_{start.strftime('%Y%m%d')}_{BATCH_DAYS}d"


def create_weekly_windows(files):
    """
    Create seven-day windows, starting from the first archive date.

    This produces the existing batch names:
        week_20260204
        week_20260211
        week_20260218
        ...
    """
    dates = sorted(date for date, _ in files)

    first_date = dates[0]
    last_date = dates[-1]

    windows = []
    week_start = first_date

    while week_start <= last_date:
        week_end = week_start + timedelta(days=BATCH_DAYS - 1)

        dates_in_window = [
            date for date in dates
            if week_start <= date <= week_end
        ]

        if dates_in_window:
            windows.append((week_start, week_end, dates_in_window))

        week_start += timedelta(days=BATCH_DAYS)

    return windows


# ---------------------------------------------------------------------
# Process one weekly batch
# ---------------------------------------------------------------------

def process_batch(index, total, week_start, week_end, dates_in_window):
    batch_name = batch_folder_name(week_start)
    out_dir = WORK / batch_name

    out_dir.mkdir(parents=True, exist_ok=True)

    snapshot = out_dir / "archive_snapshot.sqlite"
    matched = out_dir / "runs_matched.parquet"
    arrivals = out_dir / "stop_arrivals.parquet"

    print("\n" + "=" * 70)
    print(f"BATCH {index}/{total}: {week_start} to {week_end}")
    print(f"Archive days available: {len(dates_in_window)}")
    print("=" * 70, flush=True)

    # Reuse outputs only if the all-routes archive_to_inputs.py FINISHED for this batch: it writes
    # CONVERTER_DONE as its very last step. Folders from older route-list runs, or from a run that
    # was killed part-way, don't have it and are rebuilt from scratch.
    done = out_dir / "CONVERTER_DONE"
    arrivals_done = out_dir / "ARRIVALS_DONE"
    if done.exists() and matched.exists() and arrivals.exists() and arrivals_done.exists():
        print("Reusing existing matched runs and stop arrivals.")
    elif done.exists() and snapshot.exists() and matched.exists():
        print("Reusing existing snapshot and matched runs.")
        for f in (arrivals, arrivals_done):
            if f.exists():
                f.unlink()
    else:
        for f in (arrivals, arrivals_done, snapshot, matched):
            if f.exists():
                f.unlink()             # stale or partial - must be regenerated
        run([
            sys.executable,
            str(ARCHIVE_SCRIPT),
            "--archive", str(ARCHIVE),
            "--gtfs-dir", str(GTFS),
            "--out-dir", str(out_dir),
            "--lines", LINES,
            "--from", week_start.strftime("%Y%m%d"),
            "--to", week_end.strftime("%Y%m%d"),
        ])

    # Weeks where nothing matched the timetable: skip arrivals.py (it can't handle 0 runs)
    if pq.read_metadata(matched).num_rows == 0:
        print("No runs matched the timetable this week - skipping.")
        return {
            "batch": batch_name, "from": str(week_start), "to": str(week_end),
            "archive_days": len(dates_in_window), "arrival_rows": 0, "unique_runs": 0,
            "routes": 0, "status": "no_timetable_match",
        }, []

    # Generate stop arrivals if they do not already exist.
    if arrivals.exists() and arrivals_done.exists():
        print("Reusing existing stop arrivals.")
    else:
        run([
            sys.executable,
            str(ARRIVALS_SCRIPT),
            "--snapshot", str(snapshot),
            "--gtfs-dir", str(GTFS),
            "--out-dir", str(out_dir),
        ])
        if not arrivals.exists():
            raise RuntimeError(f"Missing arrivals output: {arrivals}")
        arrivals_done.write_text("ok\n")   # only after arrivals.py finished successfully

    # The week's positions snapshot is ~1 GB for the whole network and isn't needed once the
    # arrivals exist - delete it so /tmp doesn't fill up.
    if snapshot.exists():
        snapshot.unlink()

    df = pd.read_parquet(arrivals)

    if df.empty:
        print("WARNING: No stop arrivals in this batch.")

        return {
            "batch": batch_name,
            "from": str(week_start),
            "to": str(week_end),
            "archive_days": len(dates_in_window),
            "arrival_rows": 0,
            "unique_runs": 0,
            "routes": 0,
            "status": "empty",
        }, []

    required_columns = {
        "line",
        "service_date",
        "operator_ref",
        "vehicle_ref",
        "trip_id",
    }

    missing = required_columns - set(df.columns)

    if missing:
        raise RuntimeError(
            f"{arrivals} is missing columns: {sorted(missing)}"
        )

    unique_runs = df.drop_duplicates(
        ["service_date", "operator_ref", "vehicle_ref", "trip_id"]
    ).shape[0]

    route_counts = (
        df.groupby("line")
        .size()
        .reset_index(name="arrival_rows")
    )

    route_records = []

    for _, row in route_counts.iterrows():
        route_records.append({
            "batch": batch_name,
            "route": str(row["line"]),
            "arrival_rows": int(row["arrival_rows"]),
        })

    stats = {
        "batch": batch_name,
        "from": str(week_start),
        "to": str(week_end),
        "archive_days": len(dates_in_window),
        "arrival_rows": len(df),
        "unique_runs": unique_runs,
        "routes": df["line"].nunique(),
        "status": "complete",
    }

    print(f"\nArrival rows: {len(df):,}")
    print(f"Unique runs:  {unique_runs:,}")
    print(f"Routes:       {df['line'].nunique()}")

    print("\nRoute coverage:")
    print(
        route_counts
        .sort_values("arrival_rows", ascending=False)
        .to_string(index=False)
    )

    del df

    return stats, route_records


# ---------------------------------------------------------------------
# Weekly arrivals files (not combined: build_pairs.py reads them one at a time)
# ---------------------------------------------------------------------

def weekly_arrival_files(windows):
    files = []
    for week_start, _, _ in windows:
        path = WORK / batch_folder_name(week_start) / "stop_arrivals.parquet"
        if path.exists() and pq.read_metadata(path).num_rows > 0:
            files.append(path)
    if not files:
        raise RuntimeError("No non-empty stop_arrivals.parquet files found.")
    rows = sum(pq.read_metadata(p).num_rows for p in files)
    print(f"\n{len(files)} weekly arrivals files, {rows:,} stop arrivals in total")
    return files


# ---------------------------------------------------------------------
# Build training pairs
# ---------------------------------------------------------------------

def build_training_pairs(max_pairs, arrival_files):
    print("\n" + "=" * 70)
    print("BUILDING TRAINING PAIRS")
    print("=" * 70)

    if COMBINED_PAIRS.exists():
        COMBINED_PAIRS.unlink()

    run([
        sys.executable,
        str(PAIRS_SCRIPT),
        "--arrivals", *[str(p) for p in arrival_files],
        "--gtfs", str(GTFS) + "/",
        "--context", str(CONTEXT),
        "--out", str(COMBINED_PAIRS),
        "--max-pairs", str(max_pairs),
    ])

    if not COMBINED_PAIRS.exists():
        raise RuntimeError("Pair generation did not produce an output file.")

    metadata = pq.read_metadata(COMBINED_PAIRS)

    print(f"\nTraining pairs generated: {metadata.num_rows:,}")
    print(f"Saved to: {COMBINED_PAIRS}")


# ---------------------------------------------------------------------
# Train separate archive model
# ---------------------------------------------------------------------

def train_archive_model():
    print("\n" + "=" * 70)
    print("TRAINING ARCHIVE MODEL")
    print("=" * 70)

    MODEL_OUTPUT.mkdir(parents=True, exist_ok=True)

    run([
        sys.executable,
        str(TRAIN_SCRIPT),
        "--pairs", str(COMBINED_PAIRS),
        "--models", str(MODEL_OUTPUT),
    ])

    print(f"\nNew model saved to: {MODEL_OUTPUT}")
    print("The existing models/ directory has not been modified.")


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Process the complete BODS archive."
    )

    parser.add_argument(
        "--max-pairs",
        type=int,
        default=DEFAULT_MAX_PAIRS,
        help=f"Maximum training pairs (default: {DEFAULT_MAX_PAIRS:,}).",
    )

    parser.add_argument(
        "--from", dest="date_from", default="20260830",
        help="first archive date to use, YYYYMMDD (default 20260830: the timetable in data/ "
             "doesn't match earlier dates; use 00000000 for everything)",
    )

    parser.add_argument(
        "--to", dest="date_to", default="99999999",
        help="last archive date to use, YYYYMMDD",
    )

    parser.add_argument(
        "--days-per-batch", type=int, default=7,
        help="days of archive per batch (default 7). Use 2-3 if a batch runs out of memory.",
    )

    parser.add_argument(
        "--skip-training",
        action="store_true",
        help="Build combined data and training pairs without training.",
    )

    args = parser.parse_args()

    if args.max_pairs < 1:
        parser.error("--max-pairs must be greater than zero.")

    global BATCH_DAYS
    BATCH_DAYS = args.days_per_batch

    # Check required paths and scripts.
    if not ARCHIVE.exists():
        raise SystemExit(f"Archive directory not found: {ARCHIVE}")

    if not GTFS.exists():
        raise SystemExit(f"GTFS directory not found: {GTFS}")

    for script in (
        ARCHIVE_SCRIPT,
        ARRIVALS_SCRIPT,
        PAIRS_SCRIPT,
        TRAIN_SCRIPT,
    ):
        if not script.exists():
            raise SystemExit(f"Required script not found: {script}")

    WORK.mkdir(parents=True, exist_ok=True)

    files = [
        (d, p) for d, p in discover_archive()
        if args.date_from <= d.strftime("%Y%m%d") <= args.date_to
    ]

    if not files:
        raise SystemExit(f"No daily Parquet files found in {ARCHIVE}")

    windows = create_weekly_windows(files)

    print("\nFULL ARCHIVE PROCESSING")
    print("-" * 50)
    print(f"Archive files:  {len(files)}")
    print(f"First date:     {files[0][0]}")
    print(f"Last date:      {files[-1][0]}")
    print(f"Batches:        {len(windows)} x {BATCH_DAYS} days")
    print(f"Working folder: {WORK}")
    print(f"Pair limit:     {args.max_pairs:,}")

    batch_stats = []
    route_stats = []

    # Process every weekly window.
    for index, (week_start, week_end, dates) in enumerate(windows, 1):
        stats, routes = process_batch(
            index,
            len(windows),
            week_start,
            week_end,
            dates,
        )

        batch_stats.append(stats)
        route_stats.extend(routes)

        # Save reports after every batch.
        pd.DataFrame(batch_stats).to_csv(REPORT, index=False)
        pd.DataFrame(route_stats).to_csv(ROUTE_REPORT, index=False)

    print("\nAll weekly batches completed.")
    print(f"Batch report: {REPORT}")
    print(f"Route report: {ROUTE_REPORT}")

    # Weekly arrivals files (skipping empty weeks).
    arrival_files = weekly_arrival_files(windows)

    # Build training pairs, one week in memory at a time.
    build_training_pairs(args.max_pairs, arrival_files)

    # Train only after all processing succeeds.
    if not args.skip_training:
        train_archive_model()
    else:
        print("\nTraining skipped (--skip-training).")

    print("\n" + "=" * 70)
    print("ARCHIVE PIPELINE COMPLETED")
    print("=" * 70)
    print(f"Weekly arrivals:   {WORK}/week_*/stop_arrivals.parquet")
    print(f"Training pairs:    {COMBINED_PAIRS}")
    print(f"Batch report:      {REPORT}")
    print(f"Route report:      {ROUTE_REPORT}")

    if not args.skip_training:
        print(f"New model:         {MODEL_OUTPUT}")
    print("\nCharts + headline numbers:")
    print(f'  python3 delay_engine/model/explore.py --arrivals "{WORK}/week_*/stop_arrivals.parquet" '
          f'--gtfs data/ --models {MODEL_OUTPUT}')


if __name__ == "__main__":
    main()