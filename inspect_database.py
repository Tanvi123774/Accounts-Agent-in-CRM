
import sqlite3
from pathlib import Path

# Locate the database file
DB_PATH = Path(__file__).parent / "account_agent.db"

# Connect to database
connection = sqlite3.connect(DB_PATH)
cursor = connection.cursor()

print("\nCONNECTED TO DATABASE SUCCESSFULLY!")

# Get all table names
cursor.execute("""
    SELECT name
    FROM sqlite_master
    WHERE type = 'table'
    ORDER BY name;
""")

tables = cursor.fetchall()

print("\nTABLES IN YOUR DATABASE:\n")

for table in tables:
    print(table[0])

connection.close()
