
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "account_agent.db"

connection = sqlite3.connect(DB_PATH)
connection.row_factory = sqlite3.Row
cursor = connection.cursor()

query = """
SELECT
    o.id AS opportunity_id,
    o.name AS opportunity_name,
    o.account_id,
    a.name AS company_name,
    o.sales_stage,
    o.value,
    o.product,
    o.service,
    o.expected_close_date,
    o.is_active,
    o.outcome,
    o.competitor_present,
    o.competitor_name,
    o.next_followup_date,
    o.last_customer_interaction_at
FROM opportunities o
LEFT JOIN accounts a
    ON o.account_id = a.id
LIMIT 20
"""

cursor.execute(query)
opportunities = cursor.fetchall()

print("\n========== OPPORTUNITIES DATABASE ==========")
print("Showing first 20 opportunities\n")

for opportunity in opportunities:
    print("--------------------------------------")
    print("Opportunity ID:", opportunity["opportunity_id"])
    print("Opportunity Name:", opportunity["opportunity_name"])
    print("Account ID:", opportunity["account_id"])
    print("Company:", opportunity["company_name"])
    print("Sales Stage:", opportunity["sales_stage"])
    print("Value:", opportunity["value"])
    print("Product:", opportunity["product"])
    print("Service:", opportunity["service"])
    print("Expected Close:", opportunity["expected_close_date"])
    print("Active:", opportunity["is_active"])
    print("Outcome:", opportunity["outcome"])
    print("Competitor Present:", opportunity["competitor_present"])
    print("Competitor:", opportunity["competitor_name"])
    print("Next Follow-up:", opportunity["next_followup_date"])
    print("Last Customer Interaction:", opportunity["last_customer_interaction_at"])

connection.close()
