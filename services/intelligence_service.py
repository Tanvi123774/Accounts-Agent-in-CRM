
import json
import sqlite3
import uuid

from pathlib import Path
from datetime import datetime

from intelligence.health_analysis import calculate_account_health
from intelligence.engagement_analysis import summarize_account_engagement
from intelligence.risk_analysis import analyze_account_risks
from intelligence.expansion_analysis import identify_expansion_opportunities
from intelligence.recommendations import recommend_next_actions


DB_PATH = Path(__file__).resolve().parents[1] / "account_agent.db"


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def now():
    return datetime.now().isoformat(timespec="seconds")


def initialize_intelligence_tables():
    """Create only the intelligence tables if they do not already exist."""
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS account_health_overrides (
                account_id TEXT PRIMARY KEY,
                manual_status TEXT NOT NULL,
                override_reason TEXT NOT NULL,
                changed_by TEXT,
                changed_at TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS account_health_lifecycle (
                lifecycle_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                old_status TEXT,
                new_status TEXT NOT NULL,
                reason TEXT NOT NULL,
                changed_by TEXT,
                changed_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS account_health_history (
                history_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                health_score REAL NOT NULL,
                health_status TEXT NOT NULL,
                risk_level TEXT,
                health_factors TEXT,
                scoring_config_version TEXT,
                calculated_at TEXT NOT NULL
            )
        """)


def get_manual_override(account_id):
    initialize_intelligence_tables()

    with connect() as conn:
        row = conn.execute("""
            SELECT *
            FROM account_health_overrides
            WHERE account_id = ? AND is_active = 1
        """, (account_id,)).fetchone()

    return dict(row) if row else None


def get_effective_health(account_id):
    """Return calculated health alongside any active manual override."""
    calculated = calculate_account_health(account_id)

    if calculated.get("status") != "success":
        return calculated

    override = get_manual_override(account_id)
    calculated_status = calculated.get("health_status")

    return {
        **calculated,
        "calculated_health_status": calculated_status,
        "health_status": (
            override["manual_status"] if override else calculated_status
        ),
        "health_status_source": (
            "Manual override" if override else "Calculated"
        ),
        "manual_override": override
    }


def set_manual_health_status(
    account_id,
    status,
    reason,
    changed_by="CRM User"
):
    initialize_intelligence_tables()

    if not account_id or not str(account_id).strip():
        return {"status": "error", "message": "A valid account_id is required."}

    if not reason or not str(reason).strip():
        return {"status": "error", "message": "A meaningful reason is required."}

    aliases = {
        "green": "Healthy",
        "healthy": "Healthy",
        "yellow": "Needs Attention",
        "needs attention": "Needs Attention",
        "red": "At Risk",
        "at risk": "At Risk"
    }

    normalized = aliases.get(str(status).strip().lower())

    if not normalized:
        return {
            "status": "error",
            "message": "Status must be Green, Yellow, Red, Healthy, Needs Attention, or At Risk."
        }

    with connect() as conn:
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

        previous = conn.execute("""
            SELECT manual_status
            FROM account_health_overrides
            WHERE account_id = ? AND is_active = 1
        """, (account_id,)).fetchone()

        if previous:
            old_status = previous["manual_status"]
        else:
            calculated = calculate_account_health(account_id)
            old_status = calculated.get("health_status")

        timestamp = now()

        conn.execute("""
            INSERT INTO account_health_overrides (
                account_id, manual_status, override_reason,
                changed_by, changed_at, is_active
            )
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(account_id) DO UPDATE SET
                manual_status = excluded.manual_status,
                override_reason = excluded.override_reason,
                changed_by = excluded.changed_by,
                changed_at = excluded.changed_at,
                is_active = 1
        """, (
            account_id, normalized, reason.strip(),
            changed_by, timestamp
        ))

        conn.execute("""
            INSERT INTO account_health_lifecycle (
                lifecycle_id, account_id, old_status,
                new_status, reason, changed_by, changed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "HLC-" + uuid.uuid4().hex[:12].upper(),
            account_id, old_status, normalized,
            reason.strip(), changed_by, timestamp
        ))

    return {
        "status": "success",
        "account_id": account_id,
        "account_name": account["name"],
        "old_status": old_status,
        "new_status": normalized,
        "reason": reason.strip(),
        "changed_at": timestamp
    }


def clear_manual_health_override(account_id, reason="Restored calculated status",
                                 changed_by="CRM User"):
    initialize_intelligence_tables()

    with connect() as conn:
        account = conn.execute(
            "SELECT id, name FROM accounts WHERE id = ?",
            (account_id,)
        ).fetchone()

        if not account:
            return {"status": "not_found", "account_id": account_id}

        override = conn.execute("""
            SELECT manual_status
            FROM account_health_overrides
            WHERE account_id = ? AND is_active = 1
        """, (account_id,)).fetchone()

        if not override:
            return {
                "status": "success",
                "account_id": account_id,
                "message": "No active manual override exists."
            }

        calculated = calculate_account_health(account_id)
        restored_status = calculated.get("health_status", "Unknown")
        timestamp = now()

        conn.execute("""
            UPDATE account_health_overrides
            SET is_active = 0, changed_at = ?
            WHERE account_id = ?
        """, (timestamp, account_id))

        conn.execute("""
            INSERT INTO account_health_lifecycle (
                lifecycle_id, account_id, old_status,
                new_status, reason, changed_by, changed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "HLC-" + uuid.uuid4().hex[:12].upper(),
            account_id, override["manual_status"],
            restored_status, reason, changed_by, timestamp
        ))

    return {
        "status": "success",
        "account_id": account_id,
        "account_name": account["name"],
        "previous_manual_status": override["manual_status"],
        "restored_calculated_status": restored_status,
        "changed_at": timestamp
    }


def get_health_lifecycle(account_id):
    initialize_intelligence_tables()

    with connect() as conn:
        account = conn.execute(
            "SELECT id, name FROM accounts WHERE id = ?",
            (account_id,)
        ).fetchone()

        if not account:
            return {"status": "not_found", "account_id": account_id}

        rows = conn.execute("""
            SELECT *
            FROM account_health_lifecycle
            WHERE account_id = ?
            ORDER BY changed_at DESC
        """, (account_id,)).fetchall()

    return {
        "status": "success",
        "account_id": account_id,
        "account_name": account["name"],
        "count": len(rows),
        "history": [dict(row) for row in rows]
    }


def get_health_history(account_id, limit=20):
    """Return calculated health snapshots for one exact account ID."""
    initialize_intelligence_tables()

    if not account_id or not str(account_id).strip():
        return {"status": "error", "message": "A valid account_id is required."}

    try:
        limit = max(1, min(int(limit), 100))
    except (ValueError, TypeError):
        limit = 20

    with connect() as conn:
        account = conn.execute(
            "SELECT id, name FROM accounts WHERE id = ?",
            (account_id,)
        ).fetchone()

        if not account:
            return {"status": "not_found", "account_id": account_id}

        rows = conn.execute("""
            SELECT history_id, account_id, health_score,
                   health_status, risk_level, health_factors,
                   scoring_config_version, calculated_at
            FROM account_health_history
            WHERE account_id = ?
            ORDER BY calculated_at DESC
            LIMIT ?
        """, (account_id, limit)).fetchall()

    return {
        "status": "success",
        "account_id": account_id,
        "account_name": account["name"],
        "count": len(rows),
        "history": [dict(row) for row in rows]
    }


def _insert_existing_columns(conn, table, payload):
    """Insert only columns that actually exist in the target table."""
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }

    filtered = {
        key: value for key, value in payload.items()
        if key in columns
    }

    if not filtered:
        return

    names = list(filtered.keys())
    placeholders = ", ".join("?" for _ in names)
    column_sql = ", ".join(f'"{name}"' for name in names)

    conn.execute(
        f'INSERT INTO "{table}" ({column_sql}) VALUES ({placeholders})',
        [filtered[name] for name in names]
    )


def refresh_account_intelligence(account_id):
    """Recalculate account intelligence and persist the latest snapshot."""
    initialize_intelligence_tables()

    health = calculate_account_health(account_id)

    if health.get("status") != "success":
        return health

    engagement = summarize_account_engagement(account_id)
    risks = analyze_account_risks(account_id)
    expansion = identify_expansion_opportunities(account_id)
    recommendations = recommend_next_actions(account_id)

    timestamp = now()
    effective = get_effective_health(account_id)

    score = health.get("health_score")
    calculated_status = health.get("health_status", "Unknown")
    effective_status = effective.get("health_status", calculated_status)

    risk_items = risks.get("risks", []) if risks.get("status") == "success" else []
    risk_level = max(
        (item.get("severity", "Low") for item in risk_items),
        key=lambda value: {"High": 3, "Medium": 2, "Low": 1}.get(value, 0),
        default="Low"
    )

    factors = health.get("component_details", {})
    if not factors:
        factors = health.get("components", {})

    with connect() as conn:
        if score is not None:
            _insert_existing_columns(conn, "account_health_history", {
                "history_id": "HST-" + uuid.uuid4().hex[:12].upper(),
                "account_id": account_id,
                "health_score": score,
                "health_status": calculated_status,
                "risk_level": risk_level,
                "health_factors": json.dumps(factors, default=str),
                "scoring_config_version": health.get("scoring_config_version"),
                "calculated_at": timestamp
            })

        output = {
            "account_id": account_id,
            "health_score": score,
            "health_status": effective_status,
            "lead_health_score": health.get("lead_health_score"),
            "contact_engagement_score": health.get("contact_engagement_score"),
            "opportunity_health_score": health.get("opportunity_health_score"),
            "activity_recency_score": health.get("activity_recency_score"),
            "health_factors": json.dumps(factors, default=str),
            "scoring_weights": json.dumps(health.get("scoring_weights", {}), default=str),
            "scoring_config_version": health.get("scoring_config_version"),
            "engagement_score": engagement.get("average_contact_engagement_score"),
            "engagement_summary": json.dumps(engagement, default=str),
            "last_activity_at": engagement.get("latest_completed_interaction"),
            "last_customer_interaction_at": engagement.get("latest_completed_interaction"),
            "days_since_last_activity": engagement.get("days_since_last_interaction"),
            "risk_flags": json.dumps([r.get("type") for r in risk_items]),
            "risk_reasons": json.dumps(risk_items, default=str),
            "expansion_signals": json.dumps(expansion.get("signals", []), default=str),
            "cross_sell_opportunities": json.dumps(expansion.get("cross_sell_opportunities", []), default=str),
            "upsell_opportunities": json.dumps(expansion.get("upsell_opportunities", []), default=str),
            "recommended_actions": json.dumps(recommendations.get("actions", []), default=str),
            "evidence_record_ids": json.dumps(health.get("evidence_record_ids", []), default=str),
            "confidence": health.get("confidence"),
            "calculated_at": timestamp,
            "updated_at": timestamp
        }

        existing = conn.execute(
            "SELECT account_id FROM account_agent_output WHERE account_id = ?",
            (account_id,)
        ).fetchone()

        if existing:
            columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(account_agent_output)"
                ).fetchall()
            }
            filtered = {
                key: value for key, value in output.items()
                if key in columns and key != "account_id"
            }

            assignments = ", ".join(f'"{key}" = ?' for key in filtered)
            conn.execute(
                f"UPDATE account_agent_output SET {assignments} WHERE account_id = ?",
                [*filtered.values(), account_id]
            )
        else:
            _insert_existing_columns(conn, "account_agent_output", output)

    return {
        "status": "success",
        "account_id": account_id,
        "health": effective,
        "engagement": engagement,
        "risks": risks,
        "expansion": expansion,
        "recommendations": recommendations,
        "saved_at": timestamp
    }


def get_account_intelligence(account_id):
    """Return the latest live intelligence analysis for one account."""
    health = get_effective_health(account_id)

    if health.get("status") != "success":
        return health

    engagement = summarize_account_engagement(account_id)
    risks = analyze_account_risks(account_id)
    expansion = identify_expansion_opportunities(account_id)
    recommendations = recommend_next_actions(account_id)
    lifecycle = get_health_lifecycle(account_id)

    return {
        "status": "success",
        "account_id": account_id,
        "health": health,
        "engagement": engagement,
        "risks": risks,
        "expansion": expansion,
        "recommendations": recommendations,
        "health_lifecycle": lifecycle
    }
