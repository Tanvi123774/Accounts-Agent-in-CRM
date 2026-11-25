
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "account_agent.db"

# Connect to database
connection = sqlite3.connect(DB_PATH)
connection.row_factory = sqlite3.Row
cursor = connection.cursor()

# Retrieve all account records
cursor.execute("SELECT * FROM accounts")

accounts = cursor.fetchall()

print("\n========== ACCOUNT DATABASE ==========")
print(f"Total accounts: {len(accounts)}\n")

# Display selected account fields
for account in accounts:
    print("----------------------------------------")
    print("Account ID:", account["id"])
    print("Company Name:", account["name"])
    print("Industry:", account["industry"])
    print("Phone:", account["company_phone"])
    print("Email:", account["email"])
    print("Website:", account["website"])
    print("Service:", account["service"])
    print("Product:", account["product"])
    print("Status:", account["status"])
    print("Account Owner ID:", account["account_owner_id"])

print("----------------------------------------")

connection.close()
