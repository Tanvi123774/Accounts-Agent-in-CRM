import sqlite3
from pathlib import Path

db = Path("account_agent.db").resolve()
conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)

checks = {
    "LEAD STATUS": "SELECT status, COUNT(*) FROM leads GROUP BY status",
    "LEAD PRIORITY": "SELECT priority_level, COUNT(*) FROM leads GROUP BY priority_level",
    "OPPORTUNITY STAGES": "SELECT sales_stage, COUNT(*) FROM opportunities GROUP BY sales_stage",
    "OPPORTUNITY OUTCOMES": "SELECT outcome, COUNT(*) FROM opportunities GROUP BY outcome",
    "OPPORTUNITY ACTIVE FLAGS": "SELECT is_active, COUNT(*) FROM opportunities GROUP BY is_active",
    "ACTIVITY STATUS": "SELECT status, COUNT(*) FROM activities GROUP BY status",
    "ACTIVITY KIND": "SELECT kind, COUNT(*) FROM activities GROUP BY kind",
    "ACTIVITY COMPLETION": "SELECT done, COUNT(*) FROM activities GROUP BY done",
    "CONTACT STATUS": "SELECT status, COUNT(*) FROM contacts GROUP BY status",
    "CONTACT DECISION MAKERS": "SELECT decision_maker, COUNT(*) FROM contacts GROUP BY decision_maker",
    "QUOTATION STATUS": "SELECT status, COUNT(*) FROM quotations GROUP BY status",
    "SALES ORDER STATUS": "SELECT status, COUNT(*) FROM sales_orders GROUP BY status"
}

for title, query in checks.items():
    print(f"\n========== {title} ==========")
    for row in conn.execute(query):
        print(row)

print("\n========== ACTIVITY DATE RANGE ==========")
print(conn.execute("""
    SELECT MIN(occurred_at), MAX(occurred_at),
           SUM(CASE WHEN occurred_at > datetime('now') THEN 1 ELSE 0 END)
    FROM activities
""").fetchone())

print("\n========== CONTACT ENGAGEMENT DATA ==========")
print(conn.execute("""
    SELECT
        COUNT(*),
        SUM(CASE WHEN last_engagement_at IS NOT NULL THEN 1 ELSE 0 END),
        SUM(CASE WHEN contact_engagement_score IS NOT NULL THEN 1 ELSE 0 END),
        SUM(CASE WHEN total_interactions IS NOT NULL THEN 1 ELSE 0 END)
    FROM contacts
""").fetchone())

conn.close()
