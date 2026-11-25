import sqlite3
from pathlib import Path

db = Path("account_agent.db").resolve()
conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

account_id = "ACC-001"

queries = {
    "ACCOUNT": """
        SELECT * FROM accounts WHERE id = ?
    """,
    "CONTACTS": """
        SELECT id, first_name, last_name, designation, status,
               decision_maker, last_engagement_at,
               last_interaction_type, total_interactions,
               engagement_trend, contact_engagement_score
        FROM contacts WHERE account_id = ?
    """,
    "LEADS": """
        SELECT id, status, priority_level, lead_score,
               engagement_score, last_engagement_at,
               purchase_timeline, estimated_budget
        FROM leads WHERE account_id = ?
    """,
    "OPPORTUNITIES": """
        SELECT id, name, sales_stage, value, is_active,
               outcome, expected_close_date,
               last_customer_interaction_at, updated_at
        FROM opportunities WHERE account_id = ?
    """,
    "ACTIVITIES": """
        SELECT id, kind, title, occurred_at, due_at,
               done, status, customer_response_at,
               activity_outcome, follow_up_required,
               follow_up_completed_at
        FROM activities WHERE account_id = ?
        ORDER BY occurred_at DESC
        LIMIT 15
    """,
    "QUOTATIONS": """
        SELECT id, status, approval, quote_date,
               valid_until, grand_total
        FROM quotations WHERE account_id = ?
    """,
    "SALES ORDERS": """
        SELECT id, status, approval, so_date,
               delivery_date, grand_total
        FROM sales_orders WHERE account_id = ?
    """
}

for section, query in queries.items():
    print(f"\n========== {section} ==========")
    rows = conn.execute(query, (account_id,)).fetchall()

    print(f"RECORD COUNT: {len(rows)}")

    for row in rows:
        print(dict(row))

conn.close()
