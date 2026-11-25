
import truststore
truststore.inject_into_ssl()

import os
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

from agent.prompts import AGENT_INSTRUCTIONS

from agent.tools import (
    # Account retrieval
    list_accounts,
    search_accounts,
    get_account_details,
    get_account_leads,
    get_account_contacts,
    get_account_opportunities,
    get_account_activities,

    # Account intelligence
    get_account_intelligence,
    calculate_account_health,
    analyze_account_risks,
    summarize_account_engagement,
    identify_expansion_opportunities,
    recommend_next_actions,
    get_health_lifecycle,
    get_health_history,

    # CRM write operations
    create_crm_record,
    update_crm_record,

    # Additional read and retrieve tools
    get_account_documents,
    get_account_document,
    download_account_document,
    get_document_versions,
    get_account_recommendations,
    get_account_risk_alerts,
)


# ---------------------------------------------------------
# ENVIRONMENT CONFIGURATION
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

load_dotenv(PROJECT_ROOT / ".env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise ValueError(
        "GROQ_API_KEY is missing. Please check your project .env file."
    )


# ---------------------------------------------------------
# ACCOUNT INTELLIGENCE AGENT
# ---------------------------------------------------------

ACCOUNT_AGENT_INSTRUCTION = AGENT_INSTRUCTIONS + """

ADDITIONAL ACCOUNT INTELLIGENCE RULES:

1. ACCOUNT IDENTIFICATION
- Always use the exact account ID when retrieving account information.
- Never assume that two accounts with similar names are the same.
- Never invent account IDs or CRM information.

2. ACCOUNT INTELLIGENCE
- Use get_account_intelligence for a complete account intelligence overview.
- Use calculate_account_health for detailed health score explanations.
- Use analyze_account_risks for risk indicators and supporting evidence.
- Use summarize_account_engagement for engagement information.
- Use identify_expansion_opportunities for potential expansion signals.
- Use recommend_next_actions for prioritized recommendations.
- Use get_health_history for calculated health score history.
- Use get_health_lifecycle for manual health-status change history.

3. HEALTH SCORE
- Explain the components contributing to the health score.
- Clearly identify the scoring version as provisional when applicable.
- Do not describe provisional scoring thresholds as officially approved.
- Do not treat missing lead or contact scores as zero.
- Distinguish calculated health status from manually overridden health status.
- Never confuse CRM account status with account health status.

4. RISK ANALYSIS
- Report only risks supported by available CRM evidence.
- Explain the reason and evidence for every identified risk.
- Distinguish overdue activities from completed activities.
- Do not claim declining engagement when there is insufficient historical data.

5. EXPANSION ANALYSIS
- Treat stakeholder coverage, multiple products, and multiple services
  as potential signals rather than confirmed purchase intent.
- Never claim that a customer intends to purchase without supporting evidence.
- Explain the evidence and confidence level behind each signal.

6. ENGAGEMENT
- Report the latest known completed interaction when available.
- Do not invent missing interaction dates.
- Distinguish unavailable engagement scores from zero scores.

7. CRM WRITE OPERATIONS
- Before creating or updating any CRM record, show the user a clear preview.
- Do not execute a write operation until the user explicitly confirms it.
- Never delete records.
- Never silently change account associations.
- Only update fields supported by the available tool allowlists.
- After a write, report the actual result returned by the tool.

8. HONEST REPORTING
- Never invent CRM records, scores, dates, contacts, leads, or opportunities.
- Clearly disclose when information is missing or unavailable.
- Keep recommendations separate from verified CRM facts.
"""


# ---------------------------------------------------------
# ROOT AGENT
# ---------------------------------------------------------

root_agent = Agent(
    name="account_intelligence_agent",

    model=LiteLlm(
        model="groq/openai/gpt-oss-120b",
        api_key=GROQ_API_KEY,
    ),

    description=(
        "An Account Intelligence CRM agent that retrieves account data, "
        "analyses account health, engagement, risks and expansion signals, "
        "recommends next actions, and performs CRM create/update operations "
        "only after explicit user confirmation."
    ),

    instruction=ACCOUNT_AGENT_INSTRUCTION,

    tools=[
        # Account retrieval
        list_accounts,
        search_accounts,
        get_account_details,
        get_account_leads,
        get_account_contacts,
        get_account_opportunities,
        get_account_activities,

        # Account intelligence
        get_account_intelligence,
        calculate_account_health,
        analyze_account_risks,
        summarize_account_engagement,
        identify_expansion_opportunities,
        recommend_next_actions,
        get_health_lifecycle,
        get_health_history,

        # CRM write operations
        create_crm_record,
        update_crm_record,

        # Additional read and retrieve tools
        get_account_documents,
        get_account_document,
        download_account_document,
        get_document_versions,
        get_account_recommendations,
        get_account_risk_alerts,
    ],
)
