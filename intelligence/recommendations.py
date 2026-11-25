
from intelligence.risk_analysis import analyze_account_risks
from intelligence.expansion_analysis import identify_expansion_opportunities
from intelligence.engagement_analysis import summarize_account_engagement


def recommend_next_actions(account_id):
    risks = analyze_account_risks(account_id)
    expansion = identify_expansion_opportunities(account_id)
    engagement = summarize_account_engagement(account_id)

    actions = []

    if risks.get("status") == "success":
        for risk in risks.get("risks", []):
            actions.append({
                "priority": (
                    "High" if risk.get("severity") == "High"
                    else "Medium"
                ),
                "action": risk.get("recommendation"),
                "reason": risk.get("reason"),
                "source": risk.get("type")
            })

    if expansion.get("status") == "success":
        for signal in expansion.get("signals", []):
            actions.append({
                "priority": "Low",
                "action": signal.get("recommended_action"),
                "reason": signal.get("interpretation"),
                "source": signal.get("type")
            })

    if not actions:
        actions.append({
            "priority": "Medium",
            "action": "Review the account and confirm the next customer interaction.",
            "reason": "No rule-based urgent action was identified.",
            "source": "Account review"
        })

    priority_order = {"High": 0, "Medium": 1, "Low": 2}
    actions.sort(
        key=lambda x: priority_order.get(x["priority"], 3)
    )

    return {
        "status": "success",
        "account_id": account_id,
        "actions": actions,
        "engagement_summary": engagement
    }
