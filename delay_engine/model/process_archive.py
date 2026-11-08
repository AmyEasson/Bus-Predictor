
#!/usr/bin/env python3

"""
Process the full BODS historical archive in weekly batches.

Pipeline:
1. Discover daily archive files.
2. Process them in seven-day windows.
3. Reuse previously completed batches.
4. Extract stop arrivals.
5. Record batch and route coverage.
6. Combine all weekly arrivals.
7. Build training pairs.
8. Optionally train a separate archive model.

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
CONTEXT = ROOT / "delay_engine" / "archival_data" / "data"

ARCHIVE_SCRIPT = ROOT / "delay_engine" / "trip_matching" / "archive_to_inputs.py"
ARRIVALS_SCRIPT = ROOT / "delay_engine" / "trip_matching" / "arrivals.py"
PAIRS_SCRIPT = ROOT / "delay_engine" / "model" / "build_pairs.py"
TRAIN_SCRIPT = ROOT / "delay_engine" / "model" / "train.py"

WORK = Path("/tmp/bods_batches_working_copy")

COMBINED_ARRIVALS = Path("/tmp/archive_stop_arrivals.parquet")
COMBINED_PAIRS = Path("/tmp/archive_pairs.parquet")

MODEL_OUTPUT = ROOT / "delay_engine" / "model" / "models_archive"

REPORT = WORK / "archive_processing_report.csv"
ROUTE_REPORT = WORK / "archive_route_coverage.csv"


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

LINES = (
    "1,10,100,101,103,11,111,112,114,118,119,135,142,143,147,"
    "15,150,156,163,17,172,18,182,192,197,199,2,201,202,203,"
    "205,21,216,219,22,23,230,231,245,247,249,25,250,255,256,"
    "263,30,313,314,325,33,330,346,347,348,35,36,368,37,370,"
    "382,383,384,388,389,409,41,42,425,42A,42B,43,50,52,53,"
    "541,56,59,66,67,7,76,8,81,82,83,84,85,85A,86,93,95,97,"
    "98,V1,V2,X43"
)

DEFAULT_MAX_PAIRS = 2_000_000


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
        week_end = week_start + timedelta(days=6)

        dates_in_window = [
            date for date in dates
            if week_start <= date <= week_end
        ]

        if dates_in_window:
            windows.append((week_start, week_end, dates_in_window))

        week_start += timedelta(days=7)

    return windows


# ---------------------------------------------------------------------
# Process one weekly batch
# ---------------------------------------------------------------------

def process_batch(index, total, week_start, week_end, dates_in_window):
    batch_name = f"week_{week_start.strftime('%Y%m%d')}"
    out_dir = WORK / batch_name

    out_dir.mkdir(parents=True, exist_ok=True)

    snapshot = out_dir / "archive_snapshot.sqlite"
    matched = out_dir / "runs_matched.parquet"
    arrivals = out_dir / "stop_arrivals.parquet"

    print("\n" + "=" * 70)
    print(f"BATCH {index}/{total}: {week_start} to {week_end}")
    print(f"Archive days available: {len(dates_in_window)}")
    print("=" * 70, flush=True)

    # Reuse existing converter outputs if both are present.
    if snapshot.exists() and matched.exists():
        print("Reusing existing snapshot and matched runs.")
    else:
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

    # Generate stop arrivals if they do not already exist.
    if arrivals.exists():
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
# Combine weekly arrivals
# ---------------------------------------------------------------------

def combine_arrivals(windows):
    print("\n" + "=" * 70)
    print("COMBINING WEEKLY ARRIVALS")
    print("=" * 70)

    arrival_files = []

    for week_start, _, _ in windows:
        path = (
            WORK
            / f"week_{week_start.strftime('%Y%m%d')}"
            / "stop_arrivals.parquet"
        )

        if path.exists() and pq.read_metadata(path).num_rows > 0:
            arrival_files.append(path)

    if not arrival_files:
        raise RuntimeError("No non-empty stop_arrivals.parquet files found.")

    schema = pq.read_schema(arrival_files[0])

    if COMBINED_ARRIVALS.exists():
        COMBINED_ARRIVALS.unlink()

    total_rows = 0

    with pq.ParquetWriter(COMBINED_ARRIVALS, schema) as writer:
        for index, path in enumerate(arrival_files, 1):
            print(f"[{index}/{len(arrival_files)}] Adding {path.parent.name}")

            current_schema = pq.read_schema(path)

            if not current_schema.equals(schema, check_metadata=False):
                raise RuntimeError(
                    f"Parquet schema differs in {path}. "
                    "Stopping rather than combining incompatible data."
                )

            table = pq.read_table(path)
            writer.write_table(table)

            total_rows += table.num_rows
            del table

    print(f"\nCombined arrival rows: {total_rows:,}")
    print(f"Saved to: {COMBINED_ARRIVALS}")

    return total_rows


# ---------------------------------------------------------------------
# Build training pairs
# ---------------------------------------------------------------------

def build_training_pairs(max_pairs):
    print("\n" + "=" * 70)
    print("BUILDING TRAINING PAIRS")
    print("=" * 70)

    if COMBINED_PAIRS.exists():
        COMBINED_PAIRS.unlink()

    run([
        sys.executable,
        str(PAIRS_SCRIPT),
        "--arrivals", str(COMBINED_ARRIVALS),
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
        "--skip-training",
        action="store_true",
        help="Build combined data and training pairs without training.",
    )

    args = parser.parse_args()

    if args.max_pairs < 1:
        parser.error("--max-pairs must be greater than zero.")

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

    files = discover_archive()

    if not files:
        raise SystemExit(f"No daily Parquet files found in {ARCHIVE}")

    windows = create_weekly_windows(files)

    print("\nFULL ARCHIVE PROCESSING")
    print("-" * 50)
    print(f"Archive files:  {len(files)}")
    print(f"First date:     {files[0][0]}")
    print(f"Last date:      {files[-1][0]}")
    print(f"Weekly batches: {len(windows)}")
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

    # Combine weekly arrivals.
    total_arrivals = combine_arrivals(windows)

    if total_arrivals == 0:
        raise RuntimeError("Combined arrivals file is empty.")

    # Build training pairs.
    build_training_pairs(args.max_pairs)

    # Train only after all processing succeeds.
    if not args.skip_training:
        train_archive_model()
    else:
        print("\nTraining skipped (--skip-training).")

    print("\n" + "=" * 70)
    print("ARCHIVE PIPELINE COMPLETED")
    print("=" * 70)
    print(f"Combined arrivals: {COMBINED_ARRIVALS}")
    print(f"Training pairs:    {COMBINED_PAIRS}")
    print(f"Batch report:      {REPORT}")
    print(f"Route report:      {ROUTE_REPORT}")

    if not args.skip_training:
        print(f"New model:         {MODEL_OUTPUT}")


if __name__ == "__main__":
    main()
