
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "account_agent.db"

connection = sqlite3.connect(DB_PATH)
connection.row_factory = sqlite3.Row
cursor = connection.cursor()

cursor.execute("""
    SELECT
        c.id,
        c.account_id,
        c.first_name,
        c.last_name,
        c.designation,
        c.email,
        c.phone,
        c.decision_maker,
        a.name AS company_name
    FROM contacts c
    LEFT JOIN accounts a
        ON c.account_id = a.id
    LIMIT 15
""")

contacts = cursor.fetchall()

print("\n========== CONTACTS DATABASE ==========")
print("Showing first 15 contacts\n")

for contact in contacts:
    print("--------------------------------------")
    print("Contact ID:", contact["id"])
    print("Account ID:", contact["account_id"])
    print("Company:", contact["company_name"])
    print("Name:", contact["first_name"], contact["last_name"])
    print("Designation:", contact["designation"])
    print("Email:", contact["email"])
    print("Phone:", contact["phone"])
    print("Decision Maker:", contact["decision_maker"])

connection.close()
