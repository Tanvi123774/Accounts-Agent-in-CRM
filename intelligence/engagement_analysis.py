
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).resolve().parents[1] / "account_agent.db"


def _parse_datetime(value):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            str(value).strip().replace("Z", "+00:00")
        )

        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

        return parsed
    except (ValueError, TypeError):
        return None


def _safe_number(value):
    if value is None:
        return None

    try:
        number = float(value)
        return number if number == number else None
    except (ValueError, TypeError):
        return None


def summarize_account_engagement(account_id):
    if not account_id or not str(account_id).strip():
        return {
            "status": "error",
            "message": "A valid account_id is required."
        }

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        account = conn.execute(
            "SELECT id, name FROM accounts WHERE id = ?",
            (account_id,)
        ).fetchone()

        if not account:
            return {
                "status": "not_found",
                "account_id": account_id,
                "message": "Account not found."
            }

        contacts = [
            dict(row) for row in conn.execute(
                "SELECT * FROM contacts WHERE account_id = ?",
                (account_id,)
            ).fetchall()
        ]

        leads = [
            dict(row) for row in conn.execute(
                "SELECT * FROM leads WHERE account_id = ?",
                (account_id,)
            ).fetchall()
        ]

        activities = [
            dict(row) for row in conn.execute(
                """
                SELECT *
                FROM activities
                WHERE account_id = ?
                ORDER BY occurred_at DESC
                """,
                (account_id,)
            ).fetchall()
        ]

        def is_completed(activity):
            done = activity.get("done")
            status = str(activity.get("status") or "").strip().lower()

            return (
                done in (1, True, "1", "true", "TRUE")
                or status == "completed"
            )

        completed_interactions = [
            activity for activity in activities
            if is_completed(activity)
        ]

        now = datetime.utcnow()

        dated_interactions = []

        for activity in completed_interactions:
            parsed = _parse_datetime(activity.get("occurred_at"))

            if parsed and parsed <= now:
                dated_interactions.append(
                    (parsed, activity.get("occurred_at"))
                )

        latest = None
        days_since = None

        if dated_interactions:
            latest_parsed, latest_original = max(
                dated_interactions,
                key=lambda item: item[0]
            )
            latest = latest_original
            days_since = max(0, (now - latest_parsed).days)

        lead_scores = [
            score for row in leads
            if (score := _safe_number(row.get("lead_score"))) is not None
        ]

        contact_scores = [
            score for row in contacts
            if (
                score := _safe_number(
                    row.get("contact_engagement_score")
                )
            ) is not None
        ]

        average_lead = (
            round(sum(lead_scores) / len(lead_scores), 2)
            if lead_scores else None
        )

        average_contact = (
            round(sum(contact_scores) / len(contact_scores), 2)
            if contact_scores else None
        )

        if latest is None:
            interpretation = (
                "No completed interactions with a valid past date "
                "were found for this account."
            )
        elif days_since >= 30:
            interpretation = (
                f"The last completed interaction was {days_since} days ago. "
                "Engagement may need attention."
            )
        else:
            interpretation = (
                f"The last completed interaction was {days_since} days ago."
            )

        return {
            "status": "success",
            "account_id": account_id,
            "account_name": account["name"],
            "total_contacts": len(contacts),
            "total_leads": len(leads),
            "total_activities": len(activities),
            "completed_interactions": len(completed_interactions),
            "latest_completed_interaction": latest,
            "days_since_last_interaction": days_since,
            "average_lead_score": average_lead,
            "average_contact_engagement_score": average_contact,
            "known_lead_scores": len(lead_scores),
            "known_contact_scores": len(contact_scores),
            "interpretation": interpretation
        }

    except sqlite3.Error as exc:
        return {
            "status": "error",
            "account_id": account_id,
            "message": f"Database error while analysing engagement: {exc}"
        }

    finally:
        conn.close()
