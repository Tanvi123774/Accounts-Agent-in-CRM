
import sqlite3
from pathlib import Path


# Locate the existing database in the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "account_agent.db"


def get_connection():
    """Open the existing CRM database in read-only mode."""
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"CRM database not found: {DB_PATH}"
        )

    connection = sqlite3.connect(
        f"file:{DB_PATH.as_posix()}?mode=ro",
        uri=True
    )
    connection.row_factory = sqlite3.Row
    return connection


def fetch_all(query, params=()):
    """Execute a SELECT query and return dictionaries."""
    with get_connection() as connection:
        cursor = connection.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def get_account_by_id(account_id):
    """Retrieve one account using its unique Account ID."""
    rows = fetch_all(
        "SELECT * FROM accounts WHERE id = ?",
        (account_id,)
    )
    return rows[0] if rows else None


def get_account_records(account_id):
    """
    Retrieve all CRM records explicitly associated
    with the selected Account ID.
    """

    account = get_account_by_id(account_id)

    if not account:
        return {
            "success": False,
            "account_id": account_id,
            "message": "Account not found.",
            "data": None
        }

    related_tables = [
        "leads",
        "contacts",
        "opportunities",
        "activities",
        "quotations",
        "sales_orders"
    ]

    records = {}

    for table in related_tables:
        # Table names come only from this fixed allowlist.
        records[table] = fetch_all(
            f"SELECT * FROM {table} WHERE account_id = ?",
            (account_id,)
        )

    return {
        "success": True,
        "account_id": account_id,
        "data": {
            "account": account,
            **records
        },
        "record_counts": {
            table: len(rows)
            for table, rows in records.items()
        }
    }


def get_database_summary():
    """Return basic counts for the existing CRM tables."""

    tables = [
        "accounts",
        "leads",
        "contacts",
        "opportunities",
        "activities",
        "quotations",
        "sales_orders"
    ]

    summary = {}

    for table in tables:
        rows = fetch_all(f"SELECT COUNT(*) AS total FROM {table}")
        summary[table] = rows[0]["total"]

    return summary


if __name__ == "__main__":
    print("\nDATABASE CONNECTION TEST")
    print("========================")

    print("Database:", DB_PATH)
    print("\nCRM TABLE COUNTS:")

    for table, count in get_database_summary().items():
        print(f"{table}: {count}")

    print("\nACCOUNT RETRIEVAL TEST")
    print("=====================")

    accounts = fetch_all(
        "SELECT id, name FROM accounts ORDER BY id LIMIT 5"
    )

    for account in accounts:
        print(f"{account['id']} - {account['name']}")

    if accounts:
        test_id = accounts[0]["id"]
        result = get_account_records(test_id)

        print(f"\nTesting Account: {test_id}")
        print("Success:", result["success"])
        print("Record counts:", result["record_counts"])
