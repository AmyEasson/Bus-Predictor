#!/usr/bin/env python3
"""
bods_logger.py - poll BODS SIRI-VM for Greater Manchester and append to SQLite.

Usage:
    put BODS_KEY=your_key_here in a .env file next to this script, then:
    python3 bods_logger.py --once          # single poll, for testing (do this first)
    python3 bods_logger.py                 # polls every 30 s forever
    python3 bods_logger.py --interval 20   # faster

Run it on a machine that never sleeps (cloud VM), e.g.:
    nohup python3 bods_logger.py > logger.out 2>&1 &
or inside tmux/screen.

Sharing with teammates: don't open the live DB over a network share. Take a snapshot:
    sqlite3 bods_gm.sqlite ".backup snapshot.sqlite"
and copy snapshot.sqlite.

Only needs the standard library + requests (pip install requests).
All timestamps are stored as UTC ISO-8601 strings, exactly as BODS sends them.

Changes from v1:
  - operator_ref is part of the primary key (fleet numbers aren't unique across operators)
  - default interval 30 s (60 s is too coarse to catch buses passing stops)
  - bounding-box coordinate order is auto-detected on start-up
  - refuses to append to a DB created with the old schema
"""

import argparse
import os
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

ENDPOINT = "https://data.bus-data.dft.gov.uk/api/v1/datafeed/"

# Greater Manchester (generous box). Tighten it if responses are slow.
MIN_LAT, MAX_LAT = 53.33, 53.69
MIN_LON, MAX_LON = -2.73, -1.91

# The two plausible orders for the boundingBox parameter; the right one is detected at start-up.
BBOX_ORDERS = {
    "lat-first": f"{MIN_LAT},{MAX_LAT},{MIN_LON},{MAX_LON}",
    "lon-first": f"{MIN_LON},{MIN_LAT},{MAX_LON},{MAX_LAT}",
}

SIRI = "http://www.siri.org.uk/siri"
NS = {"s": SIRI}

COLUMNS = [
    "recorded_at", "polled_at", "operator_ref", "vehicle_ref", "line_ref",
    "published_line_name", "direction_ref", "vehicle_journey_ref",
    "dated_vehicle_journey_ref", "data_frame_ref", "block_ref", "origin_ref",
    "origin_name", "destination_ref", "destination_name",
    "origin_aimed_departure_time", "latitude", "longitude", "bearing",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    recorded_at                 TEXT NOT NULL,   -- when the bus reported (UTC)
    polled_at                   TEXT NOT NULL,   -- when we fetched it (UTC)
    operator_ref                TEXT NOT NULL DEFAULT '',
    vehicle_ref                 TEXT NOT NULL,
    line_ref                    TEXT,
    published_line_name         TEXT,
    direction_ref               TEXT,
    vehicle_journey_ref         TEXT,
    dated_vehicle_journey_ref   TEXT,           -- FramedVehicleJourneyRef
    data_frame_ref              TEXT,           -- service date
    block_ref                   TEXT,
    origin_ref                  TEXT,
    origin_name                 TEXT,
    destination_ref             TEXT,
    destination_name            TEXT,
    origin_aimed_departure_time TEXT,           -- key for timetable matching
    latitude                    REAL,
    longitude                   REAL,
    bearing                     REAL,
    PRIMARY KEY (operator_ref, vehicle_ref, recorded_at)
);
CREATE INDEX IF NOT EXISTS idx_pos_line_time ON positions(published_line_name, recorded_at);
CREATE INDEX IF NOT EXISTS idx_pos_journey ON positions(dated_vehicle_journey_ref, data_frame_ref);

CREATE TABLE IF NOT EXISTS polls (
    polled_at   TEXT PRIMARY KEY,
    n_vehicles  INTEGER,
    n_new       INTEGER,
    status      TEXT
);
"""


def load_dotenv():
    """Read KEY=value lines from .env (current dir, then the script's dir) into os.environ.
    Existing environment variables win. No extra dependency needed."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(os.getcwd(), ".env"), os.path.join(script_dir, ".env")):
        if not os.path.isfile(path):
            continue
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip().removeprefix("export ").strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
        return


def text(el, path):
    """Return stripped text at a namespaced path, or None."""
    node = el.find(path, NS)
    return node.text.strip() if node is not None and node.text else None


def to_float(v):
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def parse_siri(xml_bytes, polled_at):
    root = ET.fromstring(xml_bytes)
    rows = []
    for va in root.iter(f"{{{SIRI}}}VehicleActivity"):
        mvj = va.find("s:MonitoredVehicleJourney", NS)
        if mvj is None:
            continue
        recorded_at = text(va, "s:RecordedAtTime")
        vehicle_ref = text(mvj, "s:VehicleRef")
        if not recorded_at or not vehicle_ref:
            continue
        rows.append((
            recorded_at,
            polled_at,
            text(mvj, "s:OperatorRef") or "",
            vehicle_ref,
            text(mvj, "s:LineRef"),
            text(mvj, "s:PublishedLineName"),
            text(mvj, "s:DirectionRef"),
            text(mvj, "s:VehicleJourneyRef"),
            text(mvj, "s:FramedVehicleJourneyRef/s:DatedVehicleJourneyRef"),
            text(mvj, "s:FramedVehicleJourneyRef/s:DataFrameRef"),
            text(mvj, "s:BlockRef"),
            text(mvj, "s:OriginRef"),
            text(mvj, "s:OriginName"),
            text(mvj, "s:DestinationRef"),
            text(mvj, "s:DestinationName"),
            text(mvj, "s:OriginAimedDepartureTime"),
            to_float(text(mvj, "s:VehicleLocation/s:Latitude")),
            to_float(text(mvj, "s:VehicleLocation/s:Longitude")),
            to_float(text(mvj, "s:Bearing")),
        ))
    return rows


def fetch(api_key, bbox, timeout=60):
    r = requests.get(
        ENDPOINT,
        params={"boundingBox": bbox, "api_key": api_key},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.content


def _inside(r):
    return (r[16] is not None and r[17] is not None
            and MIN_LAT <= r[16] <= MAX_LAT and MIN_LON <= r[17] <= MAX_LON)


def in_box(rows):
    """Count rows whose position really is inside our box (sanity check)."""
    return sum(1 for r in rows if _inside(r))


def detect_bbox(api_key):
    """Try both coordinate orders; keep the one BODS actually applies as a filter.
    A wrong order can make BODS ignore the box and return the whole country, so we pick the
    order with the highest share of returned buses inside the box, not the highest count."""
    best_name, best_share, best_count = None, -1.0, 0
    for name, bbox in BBOX_ORDERS.items():
        try:
            rows = parse_siri(fetch(api_key, bbox), "detect")
            n = in_box(rows)
            share = n / len(rows) if rows else 0.0
            print(f"  bbox {name:9s}: {len(rows)} vehicles returned, {n} inside the box "
                  f"({share:.0%})", flush=True)
        except Exception as e:
            n, share = 0, -1.0
            print(f"  bbox {name:9s}: error {e!r}", flush=True)
        if n > 0 and share > best_share:
            best_name, best_share, best_count = name, share, n
    if best_count <= 0:
        sys.exit("Neither bounding-box order returned buses in the area. "
                 "Check your API key and that BODS is up (try the URL in a browser).")
    print(f"Using bbox order: {best_name}", flush=True)
    return BBOX_ORDERS[best_name]


def check_schema(conn):
    """Stop if the DB was created by the old script (primary key without operator_ref)."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='positions'"
    ).fetchone()
    if row and "PRIMARY KEY (operator_ref" not in row[0]:
        sys.exit("This database was created with the old schema. "
                 "Use a new file (--db bods_gm_v2.sqlite) or rename the old one.")


def poll_once(conn, api_key, bbox):
    polled_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        rows = parse_siri(fetch(api_key, bbox), polled_at)
        # Safety net: only store buses that really are inside the box
        rows = [r for r in rows if _inside(r)]
        before = conn.total_changes
        conn.executemany(
            f"INSERT OR IGNORE INTO positions ({','.join(COLUMNS)}) "
            f"VALUES ({','.join('?' * len(COLUMNS))})",
            rows,
        )
        n_new = conn.total_changes - before
        conn.execute(
            "INSERT OR REPLACE INTO polls VALUES (?,?,?,?)",
            (polled_at, len(rows), n_new, "ok"),
        )
        conn.commit()
        print(f"{polled_at}  vehicles={len(rows):5d}  new={n_new:5d}", flush=True)
        if not rows:
            print("  WARNING: 0 vehicles returned", flush=True)
        return True
    except Exception as e:  # keep running no matter what
        conn.rollback()
        conn.execute(
            "INSERT OR REPLACE INTO polls VALUES (?,?,?,?)",
            (polled_at, 0, 0, f"error: {e!r}"[:500]),
        )
        conn.commit()
        print(f"{polled_at}  ERROR {e!r}", file=sys.stderr, flush=True)
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="bods_gm.sqlite")
    ap.add_argument("--interval", type=int, default=30, help="seconds between polls")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    load_dotenv()
    api_key = os.environ.get("BODS_KEY") or os.environ.get("BODS_API_KEY")
    if not api_key:
        sys.exit("No API key found. Put BODS_KEY=your_key in a .env file next to this "
                 "script (register at data.bus-data.dft.gov.uk)")

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA journal_mode=WAL")  # lets teammates read while it writes
    check_schema(conn)
    conn.executescript(SCHEMA)

    print("Detecting bounding-box order...", flush=True)
    bbox = detect_bbox(api_key)

    if args.once:
        poll_once(conn, api_key, bbox)
        return

    failures = 0
    while True:
        start = time.monotonic()
        ok = poll_once(conn, api_key, bbox)
        failures = 0 if ok else failures + 1
        # back off on repeated errors (max 5 min), otherwise keep the interval
        wait = args.interval if ok else min(300, args.interval * 2 ** min(failures, 3))
        time.sleep(max(0, wait - (time.monotonic() - start)))


if __name__ == "__main__":
    main()