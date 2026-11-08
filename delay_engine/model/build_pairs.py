
#!/usr/bin/env python3
"""
Build training pairs from stop arrivals without creating huge intermediate merges.

Each example asks:
    "A bus is at stop i right now, D seconds late.
     How late will it be at stop j further along?"

Pairs are generated in small batches and written incrementally to Parquet.
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as F  # noqa: E402


MAX_STOPS_AHEAD = 15
MAX_PAIRS = 2_000_000

# Much smaller than the previous 2,000-run chunks.
RUN_CHUNK = 100


def count_pairs(run_lengths):
    """Count the exact number of possible stop pairs."""
    n = np.asarray(run_lengths)
    total = 0

    for ahead in range(1, MAX_STOPS_AHEAD + 1):
        total += np.clip(n - ahead, 0, None).sum()

    return int(total)


def generate_pair_batches(sa, max_pairs, seed=0):
    """
    Yield sampled training pairs in batches.

    Avoids a many-to-many merge: for each starting stop, only looks
    at the next 15 stops on that same run.
    """

    # Terminus stops are unreliable as either starting or target stops.
    sa = sa[
        (sa.is_first_stop == 0) &
        (sa.is_last_stop == 0)
    ].copy()

    sa = sa.reset_index(drop=True)

    run_ids = sa["run_id"].drop_duplicates().to_numpy()
    run_lengths = sa.groupby("run_id", sort=False).size()

    total = count_pairs(run_lengths)

    if total == 0:
        raise ValueError("No valid stop pairs could be generated.")

    fraction = min(1.0, max_pairs / total)

    print(f"Possible pairs: {total:,}")

    if fraction < 1:
        print(
            f"Sampling {fraction:.2%} of pairs "
            f"to target a maximum of {max_pairs:,}"
        )
    else:
        print("All possible pairs will be retained.")

    rng = np.random.default_rng(seed)

    for start in range(0, len(run_ids), RUN_CHUNK):
        batch_ids = run_ids[start:start + RUN_CHUNK]

        chunk = sa[sa["run_id"].isin(batch_ids)].copy()
        chunk = chunk.reset_index(drop=True)

        pairs = _pairs_for(chunk)

        if len(pairs) == 0:
            continue

        # Apply the same sampling probability to every batch.
        if fraction < 1:
            keep = rng.random(len(pairs)) < fraction
            pairs = pairs.loc[keep].reset_index(drop=True)

        if len(pairs):
            yield pairs

        completed = min(start + RUN_CHUNK, len(run_ids))
        print(
            f"\rProcessed {completed:,}/{len(run_ids):,} runs",
            end="",
            flush=True
        )

    print()


def _pairs_for(sa):
    """
    Generate only valid forward pairs within each run.

    For each offset from 1 to MAX_STOPS_AHEAD, shift the target
    columns within each run and pair them with the starting stops.
    """

    left_columns = [
        "run_id",
        "route_short_name",
        "direction_id",
        "stop_id",
        "actual_utc",
        "scheduled_utc",
        "delay_s",
        "gap_ahead_s",
        "headway_ratio",
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
        "actual_utc": "now_utc",
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
    run_sizes = grouped["run_id"].transform("size")

    parts = []

    for ahead in range(1, MAX_STOPS_AHEAD + 1):

        # Only starting stops with a target at this offset.
        valid = positions + ahead < run_sizes

        if not valid.any():
            continue

        left = (
            sa.loc[valid, left_columns]
            .rename(columns=left_names)
            .reset_index(drop=True)
        )

        # Shift target-stop information within each run.
        shifted = (
            grouped[right_columns]
            .shift(-ahead)
        )

        right = (
            shifted.loc[valid]
            .rename(columns=right_names)
            .reset_index(drop=True)
        )

        p = pd.concat([left, right], axis=1)

        p["stops_ahead"] = ahead

        p["sched_travel_s"] = (
            p["sched_to"] - p["sched_from"]
        ).dt.total_seconds()

        p = p.drop(columns=["sched_from"])

        parts.append(p)

    if not parts:
        return pd.DataFrame()

    return pd.concat(parts, ignore_index=True)


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--arrivals",
        default="delay_engine/trip_matching/out/stop_arrivals.parquet"
    )

    ap.add_argument(
        "--gtfs",
        default="gtfs/"
    )

    ap.add_argument(
        "--context",
        default="context/"
    )

    ap.add_argument(
        "--out",
        default="delay_engine/model/out/pairs.parquet"
    )

    ap.add_argument(
        "--max-pairs",
        type=int,
        default=MAX_PAIRS
    )

    a = ap.parse_args()

    if a.max_pairs < 1:
        ap.error("--max-pairs must be at least 1")

    output_dir = os.path.dirname(a.out) or "."
    os.makedirs(output_dir, exist_ok=True)

    # Write to a temporary file so a failed run cannot leave a
    # seemingly complete training dataset behind.
    temp_out = a.out + ".tmp"

    if os.path.exists(temp_out):
        os.remove(temp_out)

    if os.path.exists(a.out):
        os.remove(a.out)

    writer = None
    total_written = 0
    batch_number = 0

    try:
        print("=" * 65)
        print("LOADING STOP ARRIVALS")
        print("=" * 65)

        sa = F.load_stop_arrivals(a.arrivals, a.gtfs)

        print(
            f"Stop arrivals: {len(sa):,} | "
            f"Runs: {sa.run_id.nunique():,}"
        )

        print(
            f"Date range: {sa.actual_utc.min()} "
            f"to {sa.actual_utc.max()}"
        )

        # Load context once, not once per batch.
        print("\nLoading context data...")

        context_hourly = F.load_context_hourly(
            os.path.join(a.context, "context_hourly.parquet")
        )

        events = F.load_events(
            os.path.join(a.context, "events.csv")
        )

        print("\n" + "=" * 65)
        print("GENERATING AND WRITING PAIRS")
        print("=" * 65)

        for p in generate_pair_batches(sa, a.max_pairs):

            batch_number += 1

            # Apply the existing feature engineering to this batch.
            p = F.add_time_features(p, "now_utc")

            p = F.add_live_features(p, sa, "now_utc")

            p = F.add_hourly_context(
                p, context_hourly, "now_utc"
            )

            p = F.add_events(
                p, events, "now_utc"
            )

            # Reduce memory and disk usage.
            for column in p.select_dtypes("float64").columns:
                p[column] = p[column].astype("float32")

            table = pa.Table.from_pandas(
                p,
                preserve_index=False
            )

            if writer is None:
                writer = pq.ParquetWriter(
                    temp_out,
                    table.schema,
                    compression="snappy"
                )
            else:
                # Keep the Parquet schema consistent across batches.
                table = table.cast(writer.schema)

            writer.write_table(table)

            total_written += len(p)

            print(
                f"Batch {batch_number}: "
                f"{len(p):,} pairs written "
                f"(total: {total_written:,})"
            )

            del p, table

        if writer is not None:
            writer.close()
            writer = None

        if total_written == 0:
            raise ValueError("No training pairs were generated.")

        os.replace(temp_out, a.out)

        print("\n" + "=" * 65)
        print("PAIR GENERATION COMPLETE")
        print("=" * 65)
        print(f"Total pairs: {total_written:,}")
        print(f"Output: {a.out}")

    except Exception:
        if writer is not None:
            writer.close()

        if os.path.exists(temp_out):
            os.remove(temp_out)

        raise


if __name__ == "__main__":
    main()
