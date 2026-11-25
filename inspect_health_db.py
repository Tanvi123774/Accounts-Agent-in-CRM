import sqlite3
from pathlib import Path

db_path = Path("account_agent.db").resolve()
connection = sqlite3.connect(
    db_path.as_uri() + "?mode=ro",
    uri=True
)
connection.row_factory = sqlite3.Row

print("\n========== HEALTH-RELATED TABLES ==========")

tables = connection.execute("""
    SELECT name
    FROM sqlite_master
    WHERE type = 'table'
      AND (
        name LIKE '%health%'
        OR name LIKE '%scoring%'
        OR name LIKE '%risk%'
        OR name LIKE '%expansion%'
        OR name LIKE '%intelligence%'
      )
    ORDER BY name
""").fetchall()

for item in tables:
    table = item["name"]
    print(f"\n--- TABLE: {table} ---")

    columns = connection.execute(
        f'PRAGMA table_info("{table}")'
    ).fetchall()

    for column in columns:
        print(
            f'{column["name"]} | '
            f'{column["type"]} | '
            f'NOT NULL: {column["notnull"]} | '
            f'PRIMARY KEY: {column["pk"]}'
        )

    count = connection.execute(
        f'SELECT COUNT(*) FROM "{table}"'
    ).fetchone()[0]

    print(f"ROW COUNT: {count}")

    if count > 0:
        rows = connection.execute(
            f'SELECT * FROM "{table}" LIMIT 3'
        ).fetchall()

        for row in rows:
            print(dict(row))

print("\n========== SAMPLE ACCOUNTS ==========")

accounts = connection.execute("""
    SELECT id, name, industry, status
    FROM accounts
    ORDER BY id
    LIMIT 5
""").fetchall()

for account in accounts:
    print(dict(account))

connection.close()
