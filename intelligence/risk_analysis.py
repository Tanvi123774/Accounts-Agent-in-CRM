
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from intelligence.scoring_config import INACTIVITY_THRESHOLD_DAYS

DB_PATH = Path(__file__).resolve().parents[1] / "account_agent.db"


def parse_datetime(value):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            str(value).strip().replace("Z", "+00:00")
        )

        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)

        return parsed
    except (ValueError, TypeError):
        return None


def is_completed(activity):
    return (
        activity.get("done") in (1, True, "1")
        or str(activity.get("status") or "").strip().lower()
        in ("completed", "complete", "done")
    )


def analyze_account_risks(account_id, inactivity_days=None):
    threshold = (
        INACTIVITY_THRESHOLD_DAYS
        if inactivity_days is None
        else max(1, int(inactivity_days))
    )

    now = datetime.now()
    risks = []

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
                "account_id": account_id
            }

        activities = [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM activities
                WHERE account_id = ?
                """,
                (account_id,)
            ).fetchall()
        ]

        # 1. Inactivity risk: use completed activities only.
        completed_dates = []

        for activity in activities:
            if not is_completed(activity):
                continue

            parsed = parse_datetime(activity.get("occurred_at"))

            if parsed and parsed <= now:
                completed_dates.append(
                    (parsed, activity.get("occurred_at"))
                )

        if completed_dates:
            latest_date, latest_raw = max(
                completed_dates,
                key=lambda item: item[0]
            )

            days_inactive = (now - latest_date).days

            if days_inactive >= threshold:
                risks.append({
                    "type": "Inactivity",
                    "severity": (
                        "High"
                        if days_inactive >= threshold * 2
                        else "Medium"
                    ),
                    "reason": (
                        f"No completed activity for "
                        f"{days_inactive} days."
                    ),
                    "evidence": latest_raw,
                    "recommendation": (
                        "Contact the account and record the outcome."
                    )
                })

        elif not activities:
            risks.append({
                "type": "Missing interaction history",
                "severity": "Unknown",
                "reason": (
                    "No activities are linked to this account."
                ),
                "evidence": None,
                "recommendation": (
                    "Verify CRM activity records before assessing engagement."
                )
            })

        # 2. Overdue follow-ups.
        overdue = []

        for activity in activities:
            if is_completed(activity):
                continue

            due_date = parse_datetime(activity.get("due_at"))

            if due_date and due_date < now:
                overdue.append(activity)

        if overdue:
            risks.append({
                "type": "Overdue follow-ups",
                "severity": (
                    "High" if len(overdue) >= 3 else "Medium"
                ),
                "reason": (
                    f"{len(overdue)} unfinished activities are overdue."
                ),
                "evidence": [
                    {
                        "activity_id": item.get("id"),
                        "title": item.get("title"),
                        "due_at": item.get("due_at")
                    }
                    for item in overdue
                ],
                "recommendation": (
                    "Review overdue tasks and complete or reschedule them."
                )
            })

        # 3. Declining engagement.
        # History tables are queried using their actual schema.
        history_checks = [
            {
                "table": "lead_score_history",
                "record_table": "leads",
                "record_id_column": "lead_id",
                "score_column": "lead_score",
                "label": "Lead"
            },
            {
                "table": "contact_engagement_history",
                "record_table": "contacts",
                "record_id_column": "contact_id",
                "score_column": "engagement_score",
                "label": "Contact"
            }
        ]

        for config in history_checks:
            history_table = config["table"]
            record_table = config["record_table"]
            record_id_column = config["record_id_column"]
            score_column = config["score_column"]

            table_exists = conn.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = ?
                """,
                (history_table,)
            ).fetchone()

            if not table_exists:
                continue

            records = conn.execute(
                f"""
                SELECT id
                FROM "{record_table}"
                WHERE account_id = ?
                """,
                (account_id,)
            ).fetchall()

            for record in records:
                record_id = record["id"]

                history = conn.execute(
                    f"""
                    SELECT "{score_column}", calculated_at
                    FROM "{history_table}"
                    WHERE "{record_id_column}" = ?
                      AND account_id = ?
                    ORDER BY calculated_at DESC
                    LIMIT 2
                    """,
                    (record_id, account_id)
                ).fetchall()

                if len(history) < 2:
                    continue

                newest = history[0][score_column]
                previous = history[1][score_column]

                if newest is None or previous is None:
                    continue

                if float(newest) < float(previous):
                    risks.append({
                        "type": "Declining engagement",
                        "severity": "Medium",
                        "reason": (
                            f"{config['label']} {record_id} score declined "
                            f"from {previous} to {newest}."
                        ),
                        "evidence": {
                            "record_id": record_id,
                            "previous_score": previous,
                            "current_score": newest,
                            "previous_calculated_at": history[1]["calculated_at"],
                            "current_calculated_at": history[0]["calculated_at"]
                        },
                        "recommendation": (
                            "Review the relationship and schedule a follow-up."
                        )
                    })

        return {
            "status": "success",
            "account_id": account_id,
            "account_name": account["name"],
            "inactivity_threshold_days": threshold,
            "risk_count": len(risks),
            "risks": risks,
            "analyzed_at": now.isoformat(timespec="seconds")
        }

    finally:
        conn.close()
