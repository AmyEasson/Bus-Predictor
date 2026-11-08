from pathlib import Path
import sqlite3

# database.py is in backend/app/, so go up two levels to reach the root
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "snapshot.sqlite"


def get_db_connection():
    # sqlite3.connect would silently create an empty DB at a wrong path, so fail loudly instead
    if not DB_PATH.exists():
        raise FileNotFoundError(f"snapshot database not found at {DB_PATH}")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con