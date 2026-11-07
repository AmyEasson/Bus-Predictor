from pathlib import Path
import sqlite3

# database.py is in backend/app/, so go up two levels to reach the root
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "snapshot.sqlite"

print(f"--> Looking for database at: {DB_PATH.resolve()}")
print(f"--> Does file exist? {DB_PATH.exists()}")

def get_db_connection():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con