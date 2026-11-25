
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "account_agent.db"


def identify_expansion_opportunities(account_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    signals = []

    try:
        account = conn.execute(
            "SELECT * FROM accounts WHERE id = ?",
            (account_id,)
        ).fetchone()

        if not account:
            return {"status": "not_found", "account_id": account_id}

        account = dict(account)

        contacts = [
            dict(x) for x in conn.execute(
                "SELECT * FROM contacts WHERE account_id = ?",
                (account_id,)
            ).fetchall()
        ]

        leads = [
            dict(x) for x in conn.execute(
                "SELECT * FROM leads WHERE account_id = ?",
                (account_id,)
            ).fetchall()
        ]

        opportunities = [
            dict(x) for x in conn.execute(
                "SELECT * FROM opportunities WHERE account_id = ?",
                (account_id,)
            ).fetchall()
        ]

        products = set()
        services = set()

        for record in [account] + contacts + leads + opportunities:
            if record.get("product"):
                products.add(str(record["product"]).strip())

            if record.get("service"):
                services.add(str(record["service"]).strip())

        # New stakeholders are a relationship-development signal.
        if len(contacts) >= 2:
            signals.append({
                "type": "Stakeholder coverage",
                "signal": "Multiple stakeholders are recorded for this account.",
                "evidence": {
                    "contact_count": len(contacts),
                    "decision_makers": sum(
                        1 for x in contacts
                        if x.get("decision_maker") in (1, True, "1")
                    )
                },
                "confidence": "Low",
                "interpretation": (
                    "Potential relationship-development opportunity; "
                    "not confirmed purchase intent."
                ),
                "recommended_action": (
                    "Map stakeholder roles and identify any missing decision-makers."
                )
            })

        # Different products/services across linked CRM records may
        # indicate portfolio breadth, but are not automatically a gap.
        if len(products) > 1:
            signals.append({
                "type": "Product portfolio insight",
                "signal": "Multiple products are recorded across account records.",
                "evidence": {"products": sorted(products)},
                "confidence": "Low",
                "interpretation": "Review product adoption and possible adjacent needs.",
                "recommended_action": "Discuss current product usage and customer requirements."
            })

        if len(services) > 1:
            signals.append({
                "type": "Service portfolio insight",
                "signal": "Multiple services are recorded across account records.",
                "evidence": {"services": sorted(services)},
                "confidence": "Low",
                "interpretation": "Review service adoption and possible adjacent needs.",
                "recommended_action": "Ask about service gaps and upcoming projects."
            })

        # Active opportunity and competitor data can support a discussion,
        # but do not infer a cross-sell without evidence.
        active_pipeline = []

        for opp in opportunities:
            stage = str(opp.get("sales_stage") or "").lower()
            outcome = str(opp.get("outcome") or "").lower()

            if not any(x in stage for x in ("won", "lost", "closed")) and \
               not any(x in outcome for x in ("won", "lost", "closed")):
                active_pipeline.append(opp)

        if active_pipeline:
            signals.append({
                "type": "Pipeline development",
                "signal": "Open opportunities exist for this account.",
                "evidence": {
                    "opportunity_ids": [x.get("id") for x in active_pipeline],
                    "products": sorted(set(
                        str(x.get("product")).strip()
                        for x in active_pipeline if x.get("product")
                    ))
                },
                "confidence": "Medium",
                "interpretation": "Existing pipeline may reveal adjacent customer needs.",
                "recommended_action": "Review opportunity discussions for related requirements."
            })

        return {
            "status": "success",
            "account_id": account_id,
            "signals": signals,
            "signal_count": len(signals),
            "disclaimer": (
                "Signals are prompts for sales review, not confirmed customer demand."
            )
        }

    finally:
        conn.close()
