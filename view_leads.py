
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "account_agent.db"

connection = sqlite3.connect(DB_PATH)
connection.row_factory = sqlite3.Row
cursor = connection.cursor()

query = """
SELECT
    l.id AS lead_id,
    l.account_id,
    a.name AS company_name,
    l.contact_id,
    c.first_name || ' ' || c.last_name AS contact_name,
    l.industry,
    l.status,
    l.priority_level,
    l.lead_score,
    l.ai_lead_classification,
    l.purchase_timeline,
    l.estimated_budget,
    l.product,
    l.service
FROM leads l
LEFT JOIN accounts a
    ON l.account_id = a.id
LEFT JOIN contacts c
    ON l.contact_id = c.id
LIMIT 20
"""

cursor.execute(query)
leads = cursor.fetchall()

print("\n========== LEADS DATABASE ==========")
print("Showing first 20 leads\n")

for lead in leads:
    print("--------------------------------------")
    print("Lead ID:", lead["lead_id"])
    print("Account ID:", lead["account_id"])
    print("Company:", lead["company_name"])
    print("Contact ID:", lead["contact_id"])
    print("Contact Name:", lead["contact_name"])
    print("Industry:", lead["industry"])
    print("Status:", lead["status"])
    print("Priority:", lead["priority_level"])
    print("Lead Score:", lead["lead_score"])
    print("AI Classification:", lead["ai_lead_classification"])
    print("Purchase Timeline:", lead["purchase_timeline"])
    print("Estimated Budget:", lead["estimated_budget"])
    print("Product:", lead["product"])
    print("Service:", lead["service"])

connection.close()
