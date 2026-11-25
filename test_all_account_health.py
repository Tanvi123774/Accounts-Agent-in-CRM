from agent.health import calculate_account_health
from pathlib import Path
import sqlite3

db_path = Path("account_agent.db").resolve()

connection = sqlite3.connect(
    db_path.as_uri() + "?mode=ro",
    uri=True
)

accounts = connection.execute("""
    SELECT id, name
    FROM accounts
    ORDER BY id
""").fetchall()

connection.close()

print("\n========== ALL ACCOUNT HEALTH RESULTS ==========")

results = []

for account_id, account_name in accounts:
    result = calculate_account_health(account_id)

    if result["status"] != "success":
        print(f"\nERROR: {account_id} - {result['message']}")
        continue

    health = result["health"]
    coverage = result["data_coverage"]

    results.append({
        "id": account_id,
        "name": account_name,
        "score": health["score"],
        "classification": health["classification"],
        "coverage": coverage["available_weight_percentage"]
    })

for item in results:
    print(
        f"{item['id']} | "
        f"{item['name'][:32]:32} | "
        f"Score: {str(item['score']):>6} | "
        f"Health: {item['classification']:17} | "
        f"Coverage: {item['coverage']}%"
    )

print("\n========== HEALTH DISTRIBUTION ==========")

for category in ["Healthy", "Needs Attention", "At Risk", "Not Assessed"]:
    count = sum(
        1 for item in results
        if item["classification"] == category
    )
    print(f"{category}: {count}")

print("\n========== COVERAGE SUMMARY ==========")

if results:
    print(
        "Average scoring-weight coverage:",
        round(sum(x["coverage"] for x in results) / len(results), 2),
        "%"
    )

print("\nTotal accounts tested:", len(results))