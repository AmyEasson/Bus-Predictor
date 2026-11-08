#!/usr/bin/env python3
"""
snapshot_loop.py - every N minutes, copy the live logger database to a shared location.

The copy is made with SQLite's backup API (consistent even while the logger writes),
written to a temp file, then renamed into place, so teammates never see a half-written file.

Usage (run alongside bods_logger.py, on the same machine):
    python3 snapshot_loop.py --dest ~/GoogleDrive/hackathon/snapshot.sqlite
    python3 snapshot_loop.py --dest /srv/share/snapshot.sqlite --every 5

    nohup python3 snapshot_loop.py --dest ... > snapshot.out 2>&1 &
"""
import argparse
import os
import sqlite3
import time
from datetime import datetime

ap = argparse.ArgumentParser()
ap.add_argument("--db", default="bods_gm.sqlite", help="live database written by the logger")
ap.add_argument("--dest", required=True, help="where to put the shared snapshot")
ap.add_argument("--every", type=float, default=10, help="minutes between snapshots")
args = ap.parse_args()

dest = os.path.abspath(os.path.expanduser(args.dest))
os.makedirs(os.path.dirname(dest), exist_ok=True)
tmp = os.path.join(os.path.dirname(dest), "." + os.path.basename(dest) + ".tmp")

while True:
    start = time.monotonic()
    try:
        src = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        if os.path.exists(tmp):
            os.remove(tmp)
        out = sqlite3.connect(tmp)
        src.backup(out)
        n = out.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
        out.close()
        src.close()
        os.replace(tmp, dest)  # atomic swap
        size_mb = os.path.getsize(dest) / 1e6
        print(f"{datetime.now():%H:%M:%S}  snapshot -> {dest}  rows={n:,}  {size_mb:.0f} MB",
              flush=True)
    except Exception as e:
        print(f"{datetime.now():%H:%M:%S}  snapshot failed: {e!r}", flush=True)
    time.sleep(max(0, args.every * 60 - (time.monotonic() - start)))