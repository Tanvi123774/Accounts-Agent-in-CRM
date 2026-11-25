
import sqlite3
import uuid

from pathlib import Path

from intelligence.health_analysis import calculate_account_health as _calculate_account_health
from intelligence.risk_analysis import analyze_account_risks as _analyze_account_risks
from intelligence.engagement_analysis import summarize_account_engagement as _summarize_account_engagement
from intelligence.expansion_analysis import identify_expansion_opportunities as _identify_expansion_opportunities
from intelligence.recommendations import recommend_next_actions as _recommend_next_actions

from services.intelligence_service import (
    get_account_intelligence as _get_account_intelligence,
    get_health_lifecycle as _get_health_lifecycle,
    get_health_history as _get_health_history,
)


DB_PATH = Path(__file__).resolve().parents[1] / "account_agent.db"


TABLES = {
    "account": "accounts",
    "accounts": "accounts",
    "lead": "leads",
    "leads": "leads",
    "contact": "contacts",
    "contacts": "contacts",
    "opportunity": "opportunities",
    "opportunities": "opportunities",
    "activity": "activities",
    "activities": "activities",
}

ID_PREFIXES = {
    "accounts": "ACC",
    "leads": "LEAD",
    "contacts": "CONT",
    "opportunities": "OPP",
    "activities": "ACT",
}

ALLOWED_FIELDS = {
    "accounts": {
        "name", "industry", "company_phone", "email",
        "address_line1", "address_line2", "region", "location",
        "postal_code", "website", "additional_notes", "service",
        "product", "status", "inside_sales_id", "sales_user_id",
        "account_type", "annual_revenue", "account_owner_id"
    },
    "leads": {
        "account_name", "account_id", "contact_id", "industry",
        "designation", "email", "mobile", "company_phone",
        "website", "lead_origin", "priority_level", "status",
        "reason", "purchase_timeline", "company_size",
        "estimated_budget", "region", "location", "service",
        "product", "notes", "owner_id", "lead_score",
        "ai_lead_classification", "engagement_score",
        "last_engagement_at", "score_calculated_at"
    },
    "contacts": {
        "account_id", "title", "first_name", "last_name",
        "designation", "email", "phone", "mobile", "status",
        "decision_maker", "region", "location", "notes",
        "product", "service", "contact_engagement_score",
        "last_engagement_at", "last_interaction_type",
        "total_interactions", "engagement_trend",
        "score_calculated_at"
    },
    "opportunities": {
        "name", "account_id", "owner_id", "region",
        "sales_stage", "value", "start_date", "is_active",
        "competitor_present", "outcome", "closed_at",
        "account_name", "product", "service", "expected_close_date",
        "competitor_name", "updated_at", "inside_sales_id",
        "lead_id", "location", "description", "lost_reason",
        "next_followup_date", "last_customer_interaction_at"
    },
    "activities": {
        "opportunity_id", "owner_id", "kind", "occurred_at",
        "due_at", "done", "customer_response_at", "lead_id",
        "title", "importance", "status", "end_at", "description",
        "account_id", "account_id_source", "contact_id",
        "activity_outcome", "interaction_summary",
        "follow_up_required", "follow_up_completed_at"
    }
}


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _now():
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def _new_id(record_type):
    return (
        ID_PREFIXES[record_type]
        + "-"
        + uuid.uuid4().hex[:12].upper()
    )


def _normalise_type(record_type):
    if not record_type:
        return None
    return TABLES.get(str(record_type).strip().lower())


def _account_exists(conn, account_id):
    if not account_id:
        return False
    return conn.execute(
        "SELECT 1 FROM accounts WHERE id = ?",
        (account_id,)
    ).fetchone() is not None


def _linked_record_belongs_to_account(
    conn, table, record_id, account_id
):
    if not record_id:
        return True

    row = conn.execute(
        f"SELECT account_id FROM {table} WHERE id = ?",
        (record_id,)
    ).fetchone()

    return bool(row and row["account_id"] == account_id)


def _validate_related_links(conn, table, fields, account_id):
    """Validate linked CRM records against the selected account."""

    if table == "leads":
        contact_id = fields.get("contact_id")
        if contact_id and not _linked_record_belongs_to_account(
            conn, "contacts", contact_id, account_id
        ):
            return "The selected contact does not belong to this account."

    if table == "opportunities":
        lead_id = fields.get("lead_id")
        if lead_id and not _linked_record_belongs_to_account(
            conn, "leads", lead_id, account_id
        ):
            return "The selected lead does not belong to this account."

    if table == "activities":
        for field, linked_table in (
            ("lead_id", "leads"),
            ("contact_id", "contacts"),
            ("opportunity_id", "opportunities")
        ):
            linked_id = fields.get(field)
            if linked_id and not _linked_record_belongs_to_account(
                conn, linked_table, linked_id, account_id
            ):
                return (
                    f"The selected {field.replace('_id', '')} "
                    "does not belong to this account."
                )

    return None


# ---------------------------------------------------------
# ACCOUNT RETRIEVAL
# ---------------------------------------------------------

def list_accounts(limit: int = 50, offset: int = 0) -> dict:
    """List CRM accounts with pagination."""
    try:
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        return {"status": "error", "message": "Invalid pagination values."}

    with _connect() as conn:
        rows = conn.execute("""
            SELECT id, name, industry, company_phone, email,
                   website, service, product, status, region,
                   location, account_type, annual_revenue
            FROM accounts
            ORDER BY name COLLATE NOCASE
            LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()

        total = conn.execute(
            "SELECT COUNT(*) FROM accounts"
        ).fetchone()[0]

    return {
        "status": "success",
        "count": len(rows),
        "total_accounts": total,
        "limit": limit,
        "offset": offset,
        "accounts": [dict(row) for row in rows]
    }


def search_accounts(search_term: str) -> dict:
    """Search accounts by name, ID, industry, phone, or website."""
    if not search_term or not str(search_term).strip():
        return {"status": "error", "message": "Enter a search term."}

    term = f"%{str(search_term).strip()}%"

    with _connect() as conn:
        rows = conn.execute("""
            SELECT id, name, industry, company_phone, email,
                   website, service, product, status, region, location
            FROM accounts
            WHERE id LIKE ?
               OR name LIKE ?
               OR industry LIKE ?
               OR company_phone LIKE ?
               OR website LIKE ?
            ORDER BY name COLLATE NOCASE
            LIMIT 100
        """, (term, term, term, term, term)).fetchall()

    return {
        "status": "success",
        "search_term": search_term,
        "count": len(rows),
        "accounts": [dict(row) for row in rows]
    }


def get_account_details(account_id: str) -> dict:
    """Retrieve one account and all CRM records linked by its exact ID."""
    if not account_id:
        return {"status": "error", "message": "account_id is required."}

    with _connect() as conn:
        account = conn.execute(
            "SELECT * FROM accounts WHERE id = ?",
            (account_id,)
        ).fetchone()

        if not account:
            return {
                "status": "not_found",
                "account_id": account_id,
                "message": "Account not found."
            }

        records = {}
        for table in (
            "leads", "contacts", "opportunities",
            "activities", "quotations", "sales_orders"
        ):
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE account_id = ?",
                (account_id,)
            ).fetchall()
            records[table] = [dict(row) for row in rows]

    return {
        "status": "success",
        "account_id": account_id,
        "account": dict(account),
        **records,
        "record_counts": {
            table: len(rows) for table, rows in records.items()
        }
    }


def _get_account_records(account_id, table):
    if not account_id:
        return {"status": "error", "message": "account_id is required."}

    with _connect() as conn:
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

        rows = conn.execute(
            f"SELECT * FROM {table} WHERE account_id = ?",
            (account_id,)
        ).fetchall()

    return {
        "status": "success",
        "account_id": account_id,
        "account_name": account["name"],
        "count": len(rows),
        "records": [dict(row) for row in rows]
    }


def get_account_leads(account_id: str) -> dict:
    """Retrieve leads explicitly linked to one account ID."""
    return _get_account_records(account_id, "leads")


def get_account_contacts(account_id: str) -> dict:
    """Retrieve contacts explicitly linked to one account ID."""
    return _get_account_records(account_id, "contacts")


def get_account_opportunities(account_id: str) -> dict:
    """Retrieve opportunities explicitly linked to one account ID."""
    return _get_account_records(account_id, "opportunities")


def get_account_activities(account_id: str) -> dict:
    """Retrieve activities explicitly linked to one account ID."""
    return _get_account_records(account_id, "activities")


# ---------------------------------------------------------
# CRM CREATE / UPDATE
# ---------------------------------------------------------

def create_crm_record(
    record_type: str,
    fields: dict,
    account_id: str = ""
) -> dict:
    """
    Create one CRM record.
    The caller must obtain explicit user confirmation before calling.
    """
    table = _normalise_type(record_type)

    if not table:
        return {
            "status": "error",
            "message": "Unsupported record type."
        }

    if not isinstance(fields, dict) or not fields:
        return {
            "status": "error",
            "message": "Provide a non-empty fields dictionary."
        }

    invalid = set(fields) - ALLOWED_FIELDS[table]
    if invalid:
        return {
            "status": "error",
            "message": "Unsupported fields: " + ", ".join(sorted(invalid))
        }

    data = dict(fields)

    if table == "accounts":
        if not data.get("name"):
            return {
                "status": "error",
                "message": "An account name is required."
            }
    else:
        if not account_id:
            account_id = data.get("account_id", "")

        if not account_id:
            return {
                "status": "error",
                "message": "A valid account_id is required for this record."
            }

        if data.get("account_id") and data["account_id"] != account_id:
            return {
                "status": "error",
                "message": "The supplied account IDs do not match."
            }

        data["account_id"] = account_id

    timestamp = _now()
    if table == "accounts":
        data.setdefault("created_on", timestamp)
        data.setdefault("last_updated", timestamp)
    else:
        if table in ("leads", "contacts"):
            data.setdefault("created_on", timestamp)
            data.setdefault("last_updated", timestamp)
        elif table == "opportunities":
            data.setdefault("updated_at", timestamp)

    record_id = _new_id(table)

    with _connect() as conn:
        if table != "accounts":
            if not _account_exists(conn, account_id):
                return {
                    "status": "not_found",
                    "message": "The specified account does not exist."
                }

            link_error = _validate_related_links(
                conn, table, data, account_id
            )
            if link_error:
                return {"status": "error", "message": link_error}

        columns = ["id"] + list(data.keys())
        values = [record_id] + list(data.values())
        column_sql = ", ".join(f'"{column}"' for column in columns)
        placeholders = ", ".join("?" for _ in columns)

        conn.execute(
            f'INSERT INTO "{table}" ({column_sql}) VALUES ({placeholders})',
            values
        )

        saved = conn.execute(
            f'SELECT * FROM "{table}" WHERE id = ?',
            (record_id,)
        ).fetchone()

    return {
        "status": "success",
        "record_type": table,
        "record_id": record_id,
        "account_id": account_id or None,
        "record": dict(saved)
    }


def update_crm_record(
    record_type: str,
    record_id: str,
    field: str,
    value,
    account_id: str = ""
) -> dict:
    """
    Update one allowlisted CRM field on one record.
    Account associations cannot be changed through this tool.
    """
    table = _normalise_type(record_type)

    if not table:
        return {"status": "error", "message": "Unsupported record type."}

    if field not in ALLOWED_FIELDS[table]:
        return {
            "status": "error",
            "message": f"Field '{field}' cannot be updated."
        }

    if field == "account_id":
        return {
            "status": "error",
            "message": "Changing account associations is not permitted."
        }

    if not record_id:
        return {"status": "error", "message": "record_id is required."}

    with _connect() as conn:
        record = conn.execute(
            f'SELECT * FROM "{table}" WHERE id = ?',
            (record_id,)
        ).fetchone()

        if not record:
            return {
                "status": "not_found",
                "record_id": record_id,
                "message": "CRM record not found."
            }

        if table != "accounts":
            actual_account_id = record["account_id"]

            if account_id and actual_account_id != account_id:
                return {
                    "status": "error",
                    "message": "Record does not belong to the specified account."
                }

            if not account_id:
                account_id = actual_account_id

        timestamp_field = (
            "last_updated" if table in ("accounts", "leads", "contacts")
            else "updated_at" if table == "opportunities"
            else None
        )

        if timestamp_field:
            conn.execute(
                f'UPDATE "{table}" SET "{field}" = ?, "{timestamp_field}" = ? WHERE id = ?',
                (value, _now(), record_id)
            )
        else:
            conn.execute(
                f'UPDATE "{table}" SET "{field}" = ? WHERE id = ?',
                (value, record_id)
            )

        updated = conn.execute(
            f'SELECT * FROM "{table}" WHERE id = ?',
            (record_id,)
        ).fetchone()

    return {
        "status": "success",
        "record_type": table,
        "record_id": record_id,
        "account_id": account_id or None,
        "updated_field": field,
        "record": dict(updated)
    }


# ---------------------------------------------------------
# ACCOUNT INTELLIGENCE TOOLS
# ---------------------------------------------------------

def get_account_intelligence(account_id: str) -> dict:
    """Retrieve health, engagement, risks, expansion, and recommendations."""
    return _get_account_intelligence(account_id)


def calculate_account_health(account_id: str) -> dict:
    """Calculate the provisional rule-based account health score."""
    return _calculate_account_health(account_id)


def analyze_account_risks(account_id: str) -> dict:
    """Identify evidence-based account risks."""
    return _analyze_account_risks(account_id)


def summarize_account_engagement(account_id: str) -> dict:
    """Summarize account contacts, leads, and completed interactions."""
    return _summarize_account_engagement(account_id)


def identify_expansion_opportunities(account_id: str) -> dict:
    """Identify potential cross-sell, upsell, and stakeholder signals."""
    return _identify_expansion_opportunities(account_id)


def recommend_next_actions(account_id: str) -> dict:
    """Return prioritized, evidence-based recommended actions."""
    return _recommend_next_actions(account_id)


def get_health_lifecycle(account_id: str) -> dict:
    """Retrieve manual health-status change history."""
    return _get_health_lifecycle(account_id)


def get_health_history(account_id: str, limit: int = 20) -> dict:
    """Retrieve calculated health-score snapshots."""
    return _get_health_history(account_id, limit)


# =========================================================
# ADDITIONAL READ & RETRIEVE TOOLS
# =========================================================

def get_account_documents(account_id: str) -> dict:
    """Retrieve all documents belonging to an exact account."""

    conn = _connect()

    try:
        if not _account_exists(conn, account_id):
            return {
                "success": False,
                "message": f"Account {account_id} was not found."
            }

        rows = conn.execute(
            """
            SELECT
                document_id,
                account_id,
                document_name,
                document_type,
                category,
                uploaded_by,
                uploaded_at,
                current_version,
                status,
                description
            FROM account_documents
            WHERE account_id = ?
            ORDER BY uploaded_at DESC
            """,
            (account_id,)
        ).fetchall()

        return {
            "success": True,
            "account_id": account_id,
            "document_count": len(rows),
            "documents": [dict(row) for row in rows]
        }

    except Exception as exc:
        return {"success": False, "message": str(exc)}

    finally:
        conn.close()


def get_account_document(account_id: str, document_id: str) -> dict:
    """Retrieve one document, verifying its account association."""

    conn = _connect()

    try:
        row = conn.execute(
            """
            SELECT
                document_id,
                account_id,
                document_name,
                document_type,
                category,
                file_url,
                uploaded_by,
                uploaded_at,
                current_version,
                status,
                description
            FROM account_documents
            WHERE account_id = ?
              AND document_id = ?
            """,
            (account_id, document_id)
        ).fetchone()

        if not row:
            return {
                "success": False,
                "message": "Document not found for this account."
            }

        return {
            "success": True,
            "document": dict(row)
        }

    except Exception as exc:
        return {"success": False, "message": str(exc)}

    finally:
        conn.close()


def get_document_versions(account_id: str, document_id: str) -> dict:
    """Retrieve version history for a document belonging to an account."""

    conn = _connect()

    try:
        document = conn.execute(
            """
            SELECT document_id, document_name
            FROM account_documents
            WHERE account_id = ?
              AND document_id = ?
            """,
            (account_id, document_id)
        ).fetchone()

        if not document:
            return {
                "success": False,
                "message": "Document not found for this account."
            }

        rows = conn.execute(
            """
            SELECT
                document_version_id,
                document_id,
                version_number,
                uploaded_by,
                uploaded_at,
                change_notes,
                is_current
            FROM account_document_versions
            WHERE document_id = ?
            ORDER BY version_number DESC
            """,
            (document_id,)
        ).fetchall()

        return {
            "success": True,
            "account_id": account_id,
            "document_id": document_id,
            "document_name": document["document_name"],
            "version_count": len(rows),
            "versions": [dict(row) for row in rows]
        }

    except Exception as exc:
        return {"success": False, "message": str(exc)}

    finally:
        conn.close()


def download_account_document(
    account_id: str,
    document_id: str,
    version_number: int = None
) -> dict:
    """
    Resolve a validated document path.
    If version_number is omitted, resolve the current document version.
    """

    conn = _connect()

    try:
        if version_number is None:
            row = conn.execute(
                """
                SELECT
                    d.document_id,
                    d.account_id,
                    d.document_name,
                    d.current_version,
                    d.storage_path
                FROM account_documents d
                WHERE d.account_id = ?
                  AND d.document_id = ?
                """,
                (account_id, document_id)
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT
                    d.document_id,
                    d.account_id,
                    d.document_name,
                    v.version_number,
                    v.storage_path
                FROM account_documents d
                JOIN account_document_versions v
                  ON v.document_id = d.document_id
                WHERE d.account_id = ?
                  AND d.document_id = ?
                  AND v.version_number = ?
                """,
                (account_id, document_id, version_number)
            ).fetchone()

        if not row:
            return {
                "success": False,
                "message": "Document or requested version was not found."
            }

        storage_path = row["storage_path"]

        if not storage_path:
            return {
                "success": False,
                "message": "No stored file path is available."
            }

        from services.document_service import get_document_path

        file_path = get_document_path(storage_path)

        if not file_path or not file_path.is_file():
            return {
                "success": False,
                "message": "The document file is missing from storage."
            }

        return {
            "success": True,
            "account_id": account_id,
            "document_id": document_id,
            "document_name": row["document_name"],
            "version_number": (
                row["version_number"]
                if version_number is not None
                else row["current_version"]
            ),
            "file_path": str(file_path),
            "message": "Document path validated successfully."
        }

    except Exception as exc:
        return {"success": False, "message": str(exc)}

    finally:
        conn.close()


def get_account_recommendations(account_id: str) -> dict:
    """Retrieve account-level recommendations."""

    try:
        return recommend_next_actions(account_id)

    except Exception as exc:
        return {
            "success": False,
            "account_id": account_id,
            "message": str(exc)
        }


def get_account_risk_alerts(account_id: str) -> dict:
    """Retrieve risk alerts and supporting evidence for an account."""

    try:
        result = analyze_account_risks(account_id)

        if not result or result.get("status") != "success":
            return result

        return {
            "status": "success",
            "account_id": account_id,
            "risk_count": result.get("risk_count", 0),
            "risks": result.get("risks", []),
            "inactivity_threshold_days": result.get(
                "inactivity_threshold_days"
            ),
            "analyzed_at": result.get("analyzed_at")
        }

    except Exception as exc:
        return {
            "status": "error",
            "account_id": account_id,
            "message": str(exc)
        }

