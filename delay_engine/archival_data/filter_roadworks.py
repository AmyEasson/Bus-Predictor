import argparse
import json
import os
import re
import shutil
import zipfile
from collections import Counter
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import Transformer

GM_AUTHORITIES = ["MANCHESTER", "SALFORD", "TRAFFORD", "STOCKPORT", "TAMESIDE", "OLDHAM", "ROCHDALE",
                  "BURY", "BOLTON", "WIGAN", "GREATER MANCHESTER"]
FIELDS = ["activity_reference_number", "permit_reference_number", "work_reference_number", "usrn",
          "street_name", "area_name", "town", "road_category", "activity_type", "activity_name",
          "permit_status", "work_status", "work_category", "start_date", "end_date", "start_time", "end_time",
          "proposed_start_date", "proposed_end_date", "actual_start_date", "actual_end_date",
          "traffic_management_required", "traffic_management_type", "activity_location_type",
          "collaborative_working", "cancelled", "highway_authority", "highway_authority_swa_code",
          "promoter_organisation"]
NUM = re.compile(r"-?\d+(?:\.\d+)?")


def location(data):
    """Representative (easting, northing) of any '*coordinates'/'*geometry' WKT in object_data, else None."""
    for k, v in data.items():
        if (k.endswith("coordinates") or k.endswith("geometry")) and isinstance(v, str):
            nums = [float(x) for x in NUM.findall(v)]
            if len(nums) >= 2:
                xy = np.array(nums[: len(nums) // 2 * 2]).reshape(-1, 2)
                return float(xy[:, 0].mean()), float(xy[:, 1].mean())
    return None


def events_in(raw):
    try:
        obj = json.loads(raw)
    except ValueError:
        obj = [json.loads(line) for line in raw.splitlines() if line.strip()]
    return obj if isinstance(obj, list) else [obj]


def walk(root):
    """Yield file paths one at a time (no giant lists, so huge folders stay cheap)."""
    with os.scandir(root) as it:
        for e in it:
            if e.is_dir(follow_symlinks=False):
                yield from walk(e.path)
            elif e.is_file():
                yield Path(e.path)


def iter_sources(root, seen, max_files=0, every=1):
    """Yield (source_name, raw_text) for JSON files and JSON zip members under root, streaming.
    every=N reads only every Nth file (spread across all dates); max_files stops after that many files read."""
    k = 0
    for p in walk(root):
        low = p.suffix.lower()
        if low in (".json", ".jsonl", ".ndjson"):
            k += 1
            if k % every:
                continue
            seen["files"] += 1
            try:
                yield p.name, p.read_text(encoding="utf-8")
            except Exception:
                seen["unreadable_member"] += 1
            if max_files and seen["files"] >= max_files:
                return
        elif low == ".zip":
            with zipfile.ZipFile(p) as z:
                for n in z.namelist():
                    if n.endswith("/"):
                        continue
                    if not n.lower().endswith((".json", ".jsonl", ".ndjson")):
                        seen["skipped_non_json_member"] += 1
                        continue
                    k += 1
                    if k % every:
                        continue
                    seen["files"] += 1
                    try:
                        yield f"{p.name}:{n}", z.read(n).decode("utf-8")
                    except Exception:
                        seen["unreadable_member"] += 1
                    if max_files and seen["files"] >= max_files:
                        return


def to_frame(rows, to_wgs):
    df = pd.DataFrame(rows)
    ok = df.easting.notna()
    df["lat"], df["lon"] = np.nan, np.nan
    if ok.any():
        lon, lat = to_wgs.transform(
            df.loc[ok, "easting"].to_numpy(), df.loc[ok, "northing"].to_numpy())
        df.loc[ok, "lat"], df.loc[ok, "lon"] = lat, lon
    df["event_time"] = pd.to_datetime(df.event_time, utc=True, errors="coerce")
    for c in df.columns:
        if c in ("easting", "northing", "lat", "lon", "event_time", "no_coords"):
            continue
        df[c] = df[c].astype(str).where(df[c].notna(), None).astype("string")
    df["no_coords"] = df.no_coords.astype(bool)
    for c in ("easting", "northing", "lat", "lon"):
        df[c] = df[c].astype(float)
    return df


def main(a):
    stops = pd.read_parquet(a.stops, columns=["stop_lat", "stop_lon"])
    to_bng = Transformer.from_crs(4326, 27700, always_xy=True)
    xs, ys = to_bng.transform([stops.stop_lon.min(), stops.stop_lon.max()], [
                              stops.stop_lat.min(), stops.stop_lat.max()])
    m = a.margin_km * 1000
    x0, x1, y0, y1 = min(xs) - m, max(xs) + m, min(ys) - m, max(ys) + m
    print(
        f"keeping events inside easting {x0:,.0f}-{x1:,.0f}, northing {y0:,.0f}-{y1:,.0f}")

    to_wgs = Transformer.from_crs(27700, 4326, always_xy=True)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "_chunks"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    rows, seen, nchunk = [], Counter(), 0

    def flush():
        nonlocal rows, nchunk
        if rows:
            to_frame(rows, to_wgs).to_parquet(
                tmp / f"part_{nchunk:05d}.parquet", index=False)
            nchunk += 1
            rows = []

    for src, raw in iter_sources(a.data_dir, seen, a.max_files, a.every):
        try:
            evs = events_in(raw)
        except Exception:
            seen["unreadable_member"] += 1
            continue
        for ev in evs:
            seen["events_total"] += 1
            d = ev.get("object_data") or {}
            loc = location(d)
            if loc is not None:
                if not (x0 <= loc[0] <= x1 and y0 <= loc[1] <= y1):
                    continue
                no_coords = False
            else:
                auth = str(d.get("highway_authority", "")).upper()
                if not any(k in auth for k in GM_AUTHORITIES):
                    continue
                no_coords = True
            row = {"event_type": ev.get("event_type"), "object_type": ev.get("object_type"),
                   "object_reference": ev.get("object_reference"), "version": ev.get("version"),
                   "event_time": ev.get("event_time"), "easting": loc[0] if loc else np.nan,
                   "northing": loc[1] if loc else np.nan, "no_coords": no_coords, "source_file": src}
            row.update({k: d.get(k) for k in FIELDS})
            rows.append(row)
            seen["events_kept"] += 1
            if len(rows) >= 20000:
                flush()
        if seen["files"] % 20000 == 0:
            print(
                f"  {seen['files']:,} files read, {seen['events_kept']:,} kept", flush=True)
    flush()
    print(
        f"read {seen['files']:,} files, {seen['events_total']:,} events, kept {seen['events_kept']:,}")

    parts = sorted(tmp.glob("part_*.parquet"))
    if not parts:
        print("nothing matched; check the bounding box and the coordinate key names")
        return
    final = out / "roadworks_gm.parquet"
    schema = pq.ParquetFile(parts[0]).schema_arrow
    with pq.ParquetWriter(final, schema) as w:
        for p in parts:
            w.write_table(pq.read_table(p).cast(schema))
    shutil.rmtree(tmp, ignore_errors=True)

    df = pd.read_parquet(
        final, columns=["event_type", "event_time", "town", "no_coords"])
    print(f"\n{len(df):,} Greater Manchester events | {df.no_coords.sum():,} without coordinates")
    print("by type:", df.event_type.value_counts().to_dict())
    print("event_time range:", df.event_time.min(), "->", df.event_time.max())
    print("by month:", df.groupby(
        df.event_time.dt.strftime('%Y-%m')).size().to_dict())
    print("towns (top 8):", df.town.value_counts().head(8).to_dict())
    print("unreadable/skipped:",
          {k: v for k, v in seen.items() if k.startswith(("skipped", "unreadable"))})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True,
                    help="folder of .json files and/or .zip files")
    ap.add_argument("--stops", required=True,
                    help="stops.parquet (sets the bounding box)")
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--max-files", type=int, default=0,
                    help="stop after reading this many files (0 = all)")
    ap.add_argument("--every", type=int, default=1,
                    help="read only every Nth file, spread over all dates")
    ap.add_argument("--margin-km", type=float, default=3)
    main(ap.parse_args())
