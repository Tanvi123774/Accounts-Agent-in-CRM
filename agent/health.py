
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta


DB_PATH = Path(__file__).resolve().parents[1] / "account_agent.db"

# Provisional model for testing. Not an approved production configuration.
SCORING_VERSION = "provisional-0.1"

WEIGHTS = {
    "customer_engagement": 25,
    "relationship_strength": 20,
    "pipeline_momentum": 25,
    "commercial_relationship": 20,
    "follow_up_effectiveness": 10,
}


def _connect():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    connection = sqlite3.connect(
        DB_PATH.as_uri() + "?mode=ro",
        uri=True,
        timeout=10
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _date(value):
    """Parse an ISO date safely, returning None if unavailable."""
    if not value:
        return None

    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))

        if result.tzinfo is not None:
            result = result.astimezone().replace(tzinfo=None)

        return result

    except (ValueError, TypeError):
        return None


def _recency_score(date_value, now):
    date_value = _date(date_value)

    if date_value is None or date_value > now:
        return None

    days = (now - date_value).days

    if days <= 7:
        return 90
    if days <= 30:
        return 75
    if days <= 60:
        return 55
    if days <= 90:
        return 35

    return 15


def _classify(score):
    if score is None:
        return "Not Assessed"

    if score >= 70:
        return "Healthy"
    if score >= 40:
        return "Needs Attention"

    return "At Risk"


def _customer_engagement(activities, now):
    completed = []

    for activity in activities:
        is_completed = (
            activity["done"] == 1
            or str(activity["status"] or "").lower() == "completed"
        )

        occurred = _date(activity["occurred_at"])

        # Future activities cannot count as historical engagement.
        if is_completed and occurred is not None and occurred <= now:
            completed.append((activity, occurred))

    if not completed:
        return {
            "score": 0,
            "available": True,
            "evidence": [
                "No completed historical activities were found."
            ]
        }

    latest = max(item[1] for item in completed)
    days_since = (now - latest).days

    recency = _recency_score(latest.isoformat(), now)

    recent_count = sum(
        1 for _, date in completed
        if (now - date).days <= 90
    )

    volume_bonus = min(recent_count, 8) * 2

    score = min(100, recency + volume_bonus)

    evidence = [
        f"{len(completed)} completed historical activities found.",
        f"Latest completed activity was {days_since} days ago.",
        f"{recent_count} completed activities occurred in the last 90 days."
    ]

    return {
        "score": round(score, 2),
        "available": True,
        "evidence": evidence
    }


def _relationship_strength(contacts):
    if not contacts:
        return {
            "score": 0,
            "available": True,
            "evidence": ["No linked contacts found."]
        }

    active = [
        contact for contact in contacts
        if str(contact["status"] or "").lower() == "active"
    ]

    decision_makers = [
        contact for contact in active
        if contact["decision_maker"] == 1
    ]

    count = len(active)

    if count == 1:
        coverage_score = 35
    elif count == 2:
        coverage_score = 60
    elif count == 3:
        coverage_score = 75
    else:
        coverage_score = 85

    decision_bonus = min(len(decision_makers), 2) * 10

    score = min(100, coverage_score + decision_bonus)

    return {
        "score": round(score, 2),
        "available": True,
        "evidence": [
            f"{len(contacts)} linked contacts found.",
            f"{count} contacts are Active.",
            f"{len(decision_makers)} active contacts are marked as decision-makers.",
            "This measures recorded contact coverage, not actual relationship quality."
        ]
    }


def _pipeline_momentum(opportunities, now):
    open_opportunities = []

    for opportunity in opportunities:
        outcome = str(opportunity["outcome"] or "").lower()
        stage = str(opportunity["sales_stage"] or "").lower()

        # Do not rely on is_active: it is set to 1 for every
        # opportunity in the inspected database.
        if outcome in ("won", "lost") or stage in ("won", "lost"):
            continue

        open_opportunities.append(opportunity)

    if not open_opportunities:
        return {
            "score": 20 if opportunities else 0,
            "available": True,
            "evidence": [
                f"{len(opportunities)} total opportunities found.",
                "No currently open opportunities were identified.",
                "Won and Lost opportunities were excluded from open pipeline."
            ]
        }

    stage_scores = {
        "upside": 50,
        "probable": 70,
        "commit": 90
    }

    scores = []
    recency_scores = []

    for opportunity in open_opportunities:
        stage = str(opportunity["sales_stage"] or "").lower()

        scores.append(stage_scores.get(stage, 35))

        update_date = (
            opportunity["updated_at"]
            or opportunity["last_customer_interaction_at"]
        )

        recency = _recency_score(update_date, now)

        if recency is not None:
            recency_scores.append(recency)

    stage_average = sum(scores) / len(scores)

    if recency_scores:
        recency_average = sum(recency_scores) / len(recency_scores)
        score = (stage_average * 0.75) + (recency_average * 0.25)
    else:
        score = stage_average

    return {
        "score": round(score, 2),
        "available": True,
        "evidence": [
            f"{len(open_opportunities)} open opportunities identified.",
            f"Average opportunity stage score: {round(stage_average, 2)}.",
            f"{len(opportunities) - len(open_opportunities)} closed opportunities excluded."
        ]
    }


def _commercial_relationship(quotations, sales_orders):
    confirmed_orders = [
        order for order in sales_orders
        if str(order["status"] or "").lower() == "confirmed"
    ]

    accepted_quotes = [
        quote for quote in quotations
        if str(quote["status"] or "").lower() == "accepted"
    ]

    sent_quotes = [
        quote for quote in quotations
        if str(quote["status"] or "").lower() == "sent"
    ]

    draft_quotes = [
        quote for quote in quotations
        if str(quote["status"] or "").lower() == "draft"
    ]

    if len(confirmed_orders) >= 2:
        score = 95
    elif len(confirmed_orders) == 1:
        score = 80
    elif accepted_quotes:
        score = 65
    elif sent_quotes:
        score = 45
    elif draft_quotes:
        score = 25
    else:
        score = 0

    return {
        "score": score,
        "available": True,
        "evidence": [
            f"{len(confirmed_orders)} confirmed sales orders.",
            f"{len(accepted_quotes)} accepted quotations.",
            f"{len(sent_quotes)} sent quotations.",
            f"{len(draft_quotes)} draft quotations."
        ]
    }


def _follow_up_effectiveness(activities, now):
    due_activities = []

    for activity in activities:
        due_date = _date(activity["due_at"])

        if due_date is not None and due_date <= now:
            due_activities.append(activity)

    if not due_activities:
        return {
            "score": None,
            "available": False,
            "evidence": [
                "No activities with a valid due date on or before the calculation time.",
                "Follow-up effectiveness cannot be reliably assessed."
            ]
        }

    completed = sum(
        1 for activity in due_activities
        if (
            activity["done"] == 1
            or str(activity["status"] or "").lower() == "completed"
        )
    )

    score = (completed / len(due_activities)) * 100

    return {
        "score": round(score, 2),
        "available": True,
        "evidence": [
            f"{len(due_activities)} activities have reached their due date.",
            f"{completed} of those activities are completed.",
            f"{len(due_activities) - completed} remain incomplete."
        ]
    }


def calculate_account_health(account_id: str, as_of=None) -> dict:
    """
    Calculate a provisional account health score.

    This function:
    - Reads the existing SQLite database in read-only mode.
    - Does not modify or create database records.
    - Excludes future-dated activity from historical engagement.
    - Separates unavailable components from zero scores.
    - Does not apply manual health overrides.
    """

    if not account_id or not account_id.strip():
        return {
            "status": "error",
            "message": "Please provide an Account ID."
        }

    account_id = account_id.strip()
    now = as_of or datetime.now()

    try:
        with _connect() as connection:

            account = connection.execute(
                "SELECT id, name, industry, status FROM accounts WHERE id = ?",
                (account_id,)
            ).fetchone()

            if not account:
                return {
                    "status": "not_found",
                    "account_id": account_id,
                    "message": "No account found with this exact Account ID."
                }

            contacts = connection.execute("""
                SELECT id, status, decision_maker
                FROM contacts
                WHERE account_id = ?
            """, (account_id,)).fetchall()

            opportunities = connection.execute("""
                SELECT id, sales_stage, outcome, is_active,
                       updated_at, last_customer_interaction_at
                FROM opportunities
                WHERE account_id = ?
            """, (account_id,)).fetchall()

            activities = connection.execute("""
                SELECT id, occurred_at, due_at, done, status
                FROM activities
                WHERE account_id = ?
            """, (account_id,)).fetchall()

            quotations = connection.execute("""
                SELECT id, status, approval, grand_total
                FROM quotations
                WHERE account_id = ?
            """, (account_id,)).fetchall()

            sales_orders = connection.execute("""
                SELECT id, status, approval, grand_total
                FROM sales_orders
                WHERE account_id = ?
            """, (account_id,)).fetchall()

        components = {
            "customer_engagement": _customer_engagement(
                activities, now
            ),
            "relationship_strength": _relationship_strength(
                contacts
            ),
            "pipeline_momentum": _pipeline_momentum(
                opportunities, now
            ),
            "commercial_relationship": _commercial_relationship(
                quotations, sales_orders
            ),
            "follow_up_effectiveness": _follow_up_effectiveness(
                activities, now
            )
        }

        available_weight = sum(
            WEIGHTS[name]
            for name, component in components.items()
            if component["available"]
        )

        if available_weight == 0:
            overall_score = None
        else:
            weighted_total = sum(
                component["score"] * WEIGHTS[name]
                for name, component in components.items()
                if component["available"]
            )

            overall_score = round(
                weighted_total / available_weight, 2
            )

        classification = _classify(overall_score)

        recommendations = []

        for name, component in components.items():
            score = component["score"]

            if not component["available"]:
                recommendations.append(
                    f"Improve CRM data capture for {name.replace('_', ' ')}."
                )
            elif score < 40:
                recommendations.append(
                    f"Priority: improve {name.replace('_', ' ')}."
                )
            elif score < 70:
                recommendations.append(
                    f"Monitor and strengthen {name.replace('_', ' ')}."
                )

        if not recommendations:
            recommendations.append(
                "Continue monitoring account activity and pipeline."
            )

        return {
            "status": "success",
            "scoring_version": SCORING_VERSION,
            "calculated_at": now.isoformat(),
            "account": {
                "id": account["id"],
                "name": account["name"],
                "industry": account["industry"],
                "crm_status": account["status"]
            },
            "health": {
                "score": overall_score,
                "classification": classification,
                "thresholds": {
                    "Healthy": "70-100",
                    "Needs Attention": "40-69.99",
                    "At Risk": "0-39.99"
                },
                "thresholds_are_provisional": True
            },
            "data_coverage": {
                "available_weight_percentage": available_weight,
                "unavailable_weight_percentage": 100 - available_weight,
                "available_components": sum(
                    1 for item in components.values()
                    if item["available"]
                ),
                "total_components": len(components)
            },
            "components": components,
            "recommendations": recommendations,
            "manual_override": {
                "applied": False,
                "message": "No manual health override was applied."
            },
            "persistence": {
                "history_saved": False,
                "message": "This calculation is read-only. No database records were changed."
            }
        }

    except Exception as error:
        return {
            "status": "error",
            "account_id": account_id,
            "message": str(error)
        }
