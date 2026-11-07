from app.database import get_db_connection

con = get_db_connection()

tables = con.execute("""
    SELECT name
    FROM sqlite_master
    WHERE type = 'table'
""").fetchall()

print("DATABASE TABLES:")

for table in tables:
    table_name = table["name"]
    print(f"\n--- {table_name} ---")

    columns = con.execute(
        f"PRAGMA table_info('{table_name}')"
    ).fetchall()

    for col in columns:
        print(f"{col['name']}: {col['type']}")

    # Show a couple of example records
    examples = con.execute(
        f'SELECT * FROM "{table_name}" LIMIT 2'
    ).fetchall()

    for row in examples:
        print(dict(row))

con.close()