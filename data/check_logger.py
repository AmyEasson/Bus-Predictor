#!/usr/bin/env python3
"""
check_logger.py - quick health check for bods_logger.py

Usage:  python3 check_logger.py                    # uses bods_gm.sqlite in the current folder
        python3 check_logger.py --db path/to/bods_gm.sqlite
"""
import argparse
import sqlite3
from datetime import datetime, timezone

ap = argparse.ArgumentParser()
ap.add_argument("--db", default="bods_gm.sqlite")
args = ap.parse_args()

con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)  # read-only, safe while logging
now = datetime.now(timezone.utc)


def ago(ts):
    if not ts:
        return "never"
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return f"{(now - t).total_seconds() / 60:.1f} min ago"


rows, vehicles, lines = con.execute(
    "SELECT COUNT(*), COUNT(DISTINCT operator_ref || vehicle_ref), "
    "COUNT(DISTINCT published_line_name) FROM positions").fetchone()
last_fix = con.execute("SELECT MAX(recorded_at) FROM positions").fetchone()[0]
first_poll, last_poll, n_polls = con.execute(
    "SELECT MIN(polled_at), MAX(polled_at), COUNT(*) FROM polls").fetchone()
n_err = con.execute("SELECT COUNT(*) FROM polls WHERE status != 'ok'").fetchone()[0]
last_err = con.execute(
    "SELECT polled_at, status FROM polls WHERE status != 'ok' ORDER BY polled_at DESC LIMIT 1"
).fetchone()
recent = con.execute(
    "SELECT polled_at, n_vehicles, n_new, status FROM polls ORDER BY polled_at DESC LIMIT 5"
).fetchall()
no_match_key = con.execute(
    "SELECT COUNT(*) FROM positions WHERE origin_aimed_departure_time IS NULL "
    "OR published_line_name IS NULL").fetchone()[0]

print(f"Rows stored:         {rows:,}")
print(f"Distinct buses:      {vehicles:,}   distinct lines: {lines:,}")
print(f"Logging since:       {first_poll}")
print(f"Last poll:           {ago(last_poll)}")
print(f"Newest bus position: {ago(last_fix)}")
print(f"Polls: {n_polls:,} total, {n_err} errors")
if last_err:
    print(f"  last error at {last_err[0]}: {last_err[1][:120]}")
print(f"Rows missing line or origin time (can't be matched to timetable): "
      f"{no_match_key / rows:.0%}" if rows else "")
print("\nLast 5 polls:")
for p in recent:
    print(f"  {p[0]}  vehicles={p[1]:5d}  new={p[2]:5d}  {p[3][:40]}")

# Verdict
problems = []
if last_poll is None or (now - datetime.fromisoformat(last_poll)).total_seconds() > 180:
    problems.append("no poll in the last 3 minutes - is the logger still running?")
if recent and all(p[2] == 0 for p in recent):
    problems.append("last 5 polls added nothing new - feed may be stale")
if recent and recent[0][1] < 300:
    problems.append(f"only {recent[0][1]} vehicles in last poll (expect ~1,000-2,000 daytime)")
print("\n" + ("HEALTHY" if not problems else "CHECK THIS:\n  - " + "\n  - ".join(problems)))