
import sqlite3
import json
import uuid

from pathlib import Path
from datetime import datetime, date

from intelligence.scoring_config import (
    WEIGHTS,
    SCORING_VERSION,
    INACTIVITY_THRESHOLD_DAYS,
    RECENCY_WINDOWS,
    RECENCY_SCORES,
    classify_health,
)

DB_PATH = Path(__file__).resolve().parents[1] / "account_agent.db"


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def rows(conn, query, params=()):
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def parse_date(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "").replace("T", " ")
        )
    except (ValueError, TypeError):
        try:
            return datetime.combine(
                date.fromisoformat(str(value)[:10]),
                datetime.min.time()
            )
        except (ValueError, TypeError):
            return None


def days_old(value, now):
    parsed = parse_date(value)
    if not parsed:
        return None

    return max(0, (now - parsed).days)


def recency_score(value, now):
    days = days_old(value, now)

    if days is None:
        return None
    if days <= RECENCY_WINDOWS["very_recent_days"]:
        return RECENCY_SCORES["very_recent"]
    if days <= RECENCY_WINDOWS["recent_days"]:
        return RECENCY_SCORES["recent"]
    if days <= RECENCY_WINDOWS["moderate_days"]:
        return RECENCY_SCORES["moderate"]
    if days <= RECENCY_WINDOWS["old_days"]:
        return RECENCY_SCORES["old"]

    return RECENCY_SCORES["stale"]


def average(values):
    valid = [float(v) for v in values if v is not None]
    return round(sum(valid) / len(valid), 2) if valid else None


def safe_float(value):
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def calculate_account_health(account_id, as_of=None):
    """
    Calculates provisional account health using only records linked
    to the exact selected Account ID.

    This function does not write to the database.
    """

    now = parse_date(as_of) if as_of else datetime.now()
    if now is None:
        now = datetime.now()

    evidence = []
    factors = {}
    component_scores = {}
    component_details = {}

    with connect() as conn:
        account = conn.execute(
            "SELECT * FROM accounts WHERE id = ?",
            (account_id,)
        ).fetchone()

        if not account:
            return {
                "status": "not_found",
                "account_id": account_id,
                "message": "No account exists with this exact Account ID."
            }

        account = dict(account)

        contacts = rows(
            conn,
            "SELECT * FROM contacts WHERE account_id = ?",
            (account_id,)
        )

        leads = rows(
            conn,
            "SELECT * FROM leads WHERE account_id = ?",
            (account_id,)
        )

        opportunities = rows(
            conn,
            "SELECT * FROM opportunities WHERE account_id = ?",
            (account_id,)
        )

        activities = rows(
            conn,
            "SELECT * FROM activities WHERE account_id = ?",
            (account_id,)
        )

        quotations = rows(
            conn,
            "SELECT * FROM quotations WHERE account_id = ?",
            (account_id,)
        )

        orders = rows(
            conn,
            "SELECT * FROM sales_orders WHERE account_id = ?",
            (account_id,)
        )

    # --------------------------------------------------------
    # 1. CUSTOMER ENGAGEMENT — 25%
    # --------------------------------------------------------

    interaction_dates = []

    for activity in activities:
        completed = (
            activity.get("done") in (1, True, "1")
            or str(activity.get("status") or "").lower() == "completed"
        )

        if completed:
            interaction_dates.append(activity.get("occurred_at"))

    for lead in leads:
        interaction_dates.append(lead.get("last_engagement_at"))

    for contact in contacts:
        interaction_dates.append(contact.get("last_engagement_at"))

    interaction_dates = [x for x in interaction_dates if x]
    latest_interaction = None

    if interaction_dates:
        latest_interaction = max(
            interaction_dates,
            key=lambda x: parse_date(x) or datetime.min
        )

    activity_recency = recency_score(latest_interaction, now)

    lead_engagement_scores = [
        safe_float(x.get("engagement_score"))
        for x in leads
    ]

    contact_engagement_scores = [
        safe_float(x.get("contact_engagement_score"))
        for x in contacts
    ]

    lead_engagement = average(lead_engagement_scores)
    contact_engagement = average(contact_engagement_scores)

    engagement_parts = [
        x for x in [
            activity_recency,
            lead_engagement,
            contact_engagement
        ] if x is not None
    ]

    engagement_score = average(engagement_parts)

    if engagement_score is not None:
        component_scores["customer_engagement"] = engagement_score
        component_details["customer_engagement"] = {
            "score": engagement_score,
            "latest_interaction": latest_interaction,
            "completed_activities": len(interaction_dates),
            "lead_engagement_average": lead_engagement,
            "contact_engagement_average": contact_engagement,
        }

        evidence.append({
            "component": "Customer Engagement",
            "summary": (
                f"Latest recorded interaction: {latest_interaction or 'unknown'}."
            ),
            "source": "activities, leads and contacts"
        })

    # --------------------------------------------------------
    # 2. RELATIONSHIP STRENGTH — 20%
    # --------------------------------------------------------

    active_contacts = [
        c for c in contacts
        if str(c.get("status") or "").lower() == "active"
    ]

    decision_makers = [
        c for c in active_contacts
        if c.get("decision_maker") in (1, True, "1")
    ]

    contact_scores = [
        safe_float(c.get("contact_engagement_score"))
        for c in active_contacts
    ]

    known_contact_scores = [x for x in contact_scores if x is not None]

    if contacts:
        count = len(active_contacts)

        coverage_score = (
            35 if count == 1 else
            60 if count == 2 else
            75 if count == 3 else
            85 if count >= 4 else 0
        )

        stakeholder_score = min(len(decision_makers), 2) * 7.5
        engagement_quality = (
            average(known_contact_scores)
            if known_contact_scores else None
        )

        parts = [coverage_score + stakeholder_score]

        if engagement_quality is not None:
            parts.append(engagement_quality)

        relationship_score = average(parts)

        component_scores["relationship_strength"] = relationship_score
        component_details["relationship_strength"] = {
            "score": relationship_score,
            "active_contacts": count,
            "decision_makers": len(decision_makers),
            "known_contact_engagement_scores": len(known_contact_scores),
        }

        evidence.append({
            "component": "Relationship Strength",
            "summary": (
                f"{count} active contacts and "
                f"{len(decision_makers)} identified decision-makers."
            ),
            "source": "contacts"
        })

    # --------------------------------------------------------
    # 3. OPPORTUNITY AND PIPELINE MOMENTUM — 25%
    # --------------------------------------------------------

    open_opportunities = []

    closed_words = ("won", "lost", "closed", "cancelled", "canceled")

    for opportunity in opportunities:
        stage = str(opportunity.get("sales_stage") or "").lower()
        outcome = str(opportunity.get("outcome") or "").lower()

        if any(word in stage for word in closed_words):
            continue

        if any(word in outcome for word in closed_words):
            continue

        open_opportunities.append(opportunity)

    stage_scores = {
        "upside": 50,
        "qualified": 55,
        "probable": 70,
        "commit": 90,
        "negotiation": 80,
        "proposal": 65,
        "discovery": 45,
    }

    opportunity_scores = []

    for opportunity in open_opportunities:
        stage = str(opportunity.get("sales_stage") or "").lower()

        stage_score = next(
            (
                score for key, score in stage_scores.items()
                if key in stage
            ),
            40
        )

        date_value = (
            opportunity.get("last_customer_interaction_at")
            or opportunity.get("updated_at")
        )

        recent_score = recency_score(date_value, now)

        if recent_score is not None:
            opportunity_scores.append(
                (stage_score * 0.75) + (recent_score * 0.25)
            )
        else:
            opportunity_scores.append(stage_score)

    lead_scores = [
        safe_float(x.get("lead_score"))
        for x in leads
    ]

    known_lead_scores = [x for x in lead_scores if x is not None]

    pipeline_parts = []

    if opportunity_scores:
        pipeline_parts.append(average(opportunity_scores))

    if known_lead_scores:
        pipeline_parts.append(average(known_lead_scores))

    if pipeline_parts:
        pipeline_score = average(pipeline_parts)
        component_scores["pipeline_momentum"] = pipeline_score

        component_details["pipeline_momentum"] = {
            "score": pipeline_score,
            "open_opportunities": len(open_opportunities),
            "total_opportunities": len(opportunities),
            "known_lead_scores": len(known_lead_scores),
            "average_lead_score": average(known_lead_scores),
        }

        evidence.append({
            "component": "Pipeline Momentum",
            "summary": (
                f"{len(open_opportunities)} open opportunities and "
                f"{len(leads)} linked leads."
            ),
            "source": "opportunities and leads"
        })

    # --------------------------------------------------------
    # 4. COMMERCIAL RELATIONSHIP — 20%
    # --------------------------------------------------------

    commercial_score = None

    if orders:
        commercial_score = 80 if len(orders) == 1 else 95

    elif quotations:
        quote_statuses = [
            str(q.get("status") or "").lower()
            for q in quotations
        ]

        if any("accept" in x or "approv" in x for x in quote_statuses):
            commercial_score = 65
        elif any("sent" in x or "submit" in x for x in quote_statuses):
            commercial_score = 45
        else:
            commercial_score = 25

    if commercial_score is not None:
        component_scores["commercial_relationship"] = commercial_score

        component_details["commercial_relationship"] = {
            "score": commercial_score,
            "sales_orders": len(orders),
            "quotations": len(quotations),
        }

        evidence.append({
            "component": "Commercial Relationship",
            "summary": (
                f"{len(orders)} sales orders and "
                f"{len(quotations)} quotations recorded."
            ),
            "source": "sales_orders and quotations"
        })

    # --------------------------------------------------------
    # 5. FOLLOW-UP EFFECTIVENESS — 10%
    # --------------------------------------------------------

    due_activities = []

    for activity in activities:
        completed = (
            activity.get("done") in (1, True, "1")
            or str(activity.get("status") or "").lower() == "completed"
        )

        due = parse_date(activity.get("due_at"))

        if due and due <= now:
            due_activities.append({
                "completed": completed,
                "overdue": due < now and not completed,
                "title": activity.get("title"),
                "due_at": activity.get("due_at"),
            })

    if due_activities:
        completed_count = sum(
            1 for x in due_activities if x["completed"]
        )

        follow_up_score = (
            completed_count / len(due_activities)
        ) * 100

        component_scores["follow_up_effectiveness"] = round(
            follow_up_score, 2
        )

        component_details["follow_up_effectiveness"] = {
            "score": round(follow_up_score, 2),
            "due_activities": len(due_activities),
            "completed_activities": completed_count,
            "overdue_activities": sum(
                1 for x in due_activities if x["overdue"]
            ),
        }

        evidence.append({
            "component": "Follow-up Effectiveness",
            "summary": (
                f"{completed_count} of {len(due_activities)} due activities "
                "are completed."
            ),
            "source": "activities"
        })

    # --------------------------------------------------------
    # FINAL WEIGHTED SCORE
    # --------------------------------------------------------

    available_weight = sum(
        WEIGHTS[name] for name in component_scores
    )

    if available_weight:
        score = sum(
            component_scores[name] * WEIGHTS[name]
            for name in component_scores
        ) / available_weight

        score = round(score, 2)
        health_status = classify_health(score)
    else:
        score = None
        health_status = "Not Assessed"

    days_since_interaction = days_old(latest_interaction, now)

    return {
        "status": "success",
        "account_id": account_id,
        "account_name": account.get("name"),
        "calculated_score": score,
        "health_status": health_status,
        "scoring_version": SCORING_VERSION,
        "provisional": True,
        "weights": WEIGHTS,
        "component_scores": component_scores,
        "component_details": component_details,
        "available_weight_percentage": available_weight,
        "latest_interaction": latest_interaction,
        "days_since_last_interaction": days_since_interaction,
        "inactivity_threshold_days": INACTIVITY_THRESHOLD_DAYS,
        "evidence": evidence,
        "record_counts": {
            "contacts": len(contacts),
            "leads": len(leads),
            "opportunities": len(opportunities),
            "open_opportunities": len(open_opportunities),
            "activities": len(activities),
            "quotations": len(quotations),
            "sales_orders": len(orders),
        },
        "calculated_at": now.isoformat(timespec="seconds"),
        "history_saved": False,
    }
