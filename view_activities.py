
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "account_agent.db"

connection = sqlite3.connect(DB_PATH)
connection.row_factory = sqlite3.Row
cursor = connection.cursor()

query = """
SELECT
    act.id AS activity_id,
    act.account_id,
    a.name AS company_name,
    act.contact_id,
    c.first_name || ' ' || c.last_name AS contact_name,
    act.opportunity_id,
    o.name AS opportunity_name,
    act.kind,
    act.title,
    act.occurred_at,
    act.due_at,
    act.done,
    act.status,
    act.importance,
    act.activity_outcome,
    act.follow_up_required,
    act.customer_response_at,
    act.description
FROM activities act
LEFT JOIN accounts a
    ON act.account_id = a.id
LEFT JOIN contacts c
    ON act.contact_id = c.id
LEFT JOIN opportunities o
    ON act.opportunity_id = o.id
LIMIT 25
"""

cursor.execute(query)
activities = cursor.fetchall()

print("\n========== ACTIVITIES DATABASE ==========")
print("Showing first 25 activities\n")

for activity in activities:
    print("--------------------------------------")
    print("Activity ID:", activity["activity_id"])
    print("Account ID:", activity["account_id"])
    print("Company:", activity["company_name"])
    print("Contact:", activity["contact_name"])
    print("Opportunity:", activity["opportunity_name"])
    print("Type:", activity["kind"])
    print("Title:", activity["title"])
    print("Occurred At:", activity["occurred_at"])
    print("Due At:", activity["due_at"])
    print("Completed:", activity["done"])
    print("Status:", activity["status"])
    print("Importance:", activity["importance"])
    print("Outcome:", activity["activity_outcome"])
    print("Follow-up Required:", activity["follow_up_required"])
    print("Customer Response:", activity["customer_response_at"])
    print("Description:", activity["description"])

connection.close()
