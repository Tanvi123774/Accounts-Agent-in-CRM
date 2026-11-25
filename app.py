import streamlit as st
import sqlite3
import pandas as pd
import csv
import io
import html
import re
from pathlib import Path
from datetime import datetime, date

from services.intelligence_service import (
    initialize_intelligence_tables,
    get_effective_health,
    get_health_lifecycle,
    set_manual_health_status,
    clear_manual_health_override,
    refresh_account_intelligence,
)

from services.document_service import (
    initialize_document_storage,
    upload_account_document,
    list_account_documents,
    get_document_versions,
    get_document_path,
)

# ============================================================
# ACCOUNTIQ CRM — ACCOUNTS MODULE
# Uses the existing account_agent.db
# Does not modify the Google ADK agent.
# ============================================================

st.set_page_config(
    page_title="AccountIQ | Accounts",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded"
)

DB_PATH = Path(__file__).resolve().parent / "account_agent.db"

# Initialise only the additive intelligence/document structures.
# Existing CRM tables and records are preserved.
initialize_intelligence_tables()
initialize_document_storage()

# ============================================================
# DATABASE
# ============================================================

def get_connection():
    if not DB_PATH.exists():
        st.error(f"Database not found: {DB_PATH}")
        st.stop()

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def get_tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {row["name"] for row in rows}


def get_columns(conn, table):
    try:
        rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        return [row["name"] for row in rows]
    except sqlite3.Error:
        return []


def fetch_all(query, params=()):
    conn = get_connection()
    try:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def fetch_one(query, params=()):
    conn = get_connection()
    try:
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def execute_sql(query, params=()):
    conn = get_connection()
    try:
        cursor = conn.execute(query, params)
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_accounts():
    return fetch_all(
        "SELECT * FROM accounts ORDER BY name COLLATE NOCASE"
    )


def get_account(account_id):
    return fetch_one(
        "SELECT * FROM accounts WHERE id = ?",
        (account_id,)
    )


def next_account_id():
    accounts = get_accounts()
    numbers = []

    for account in accounts:
        value = str(account.get("id", ""))
        match = re.search(r"(\d+)$", value)
        if match:
            numbers.append(int(match.group(1)))

    next_number = max(numbers, default=0) + 1
    return f"ACC-{next_number:04d}"


def save_account(payload, account_id=None):
    conn = get_connection()

    try:
        columns = get_columns(conn, "accounts")
        payload = {
            key: value
            for key, value in payload.items()
            if key in columns and key != "id"
        }

        if account_id:
            payload["last_updated"] = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            fields = list(payload.keys())
            assignments = ", ".join(
                f'"{field}" = ?' for field in fields
            )

            values = [payload[field] for field in fields]
            values.append(account_id)

            conn.execute(
                f'UPDATE accounts SET {assignments} WHERE id = ?',
                values
            )

        else:
            payload["id"] = next_account_id()

            if "created_on" in columns:
                payload["created_on"] = datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

            if "last_updated" in columns:
                payload["last_updated"] = datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

            fields = list(payload.keys())
            placeholders = ", ".join(["?"] * len(fields))
            field_names = ", ".join(f'"{field}"' for field in fields)

            conn.execute(
                f'INSERT INTO accounts ({field_names}) '
                f'VALUES ({placeholders})',
                [payload[field] for field in fields]
            )

        conn.commit()

    finally:
        conn.close()


# ============================================================
# RELATED RECORDS
# ============================================================

RELATED_TABLES = {
    "Contacts": "contacts",
    "Leads": "leads",
    "Opportunities": "opportunities",
    "Quotations": "quotations",
    "Sales Orders": "sales_orders",
    "Activities": "activities"
}


def get_related_records(account_id, table):
    conn = get_connection()

    try:
        tables = get_tables(conn)

        if table not in tables:
            return []

        columns = get_columns(conn, table)

        if "account_id" not in columns:
            return []

        rows = conn.execute(
            f'SELECT * FROM "{table}" WHERE account_id = ?',
            (account_id,)
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        conn.close()


def get_account_activities(account_id):
    return get_related_records(account_id, "activities")


def get_health_status(account_id):
    """Return calculated health separately from any manual override."""
    try:
        data = get_effective_health(account_id)
        if data.get("status") != "success":
            return {"status": "Not Assessed", "score": None, "reason": None}

        override = data.get("manual_override")
        return {
            "status": data.get("effective_health_status", "Not Assessed"),
            "score": data.get("calculated_score"),
            "reason": override.get("override_reason") if override else None,
            "calculated_status": data.get("health_status"),
            "status_source": data.get("effective_status_source"),
        }
    except Exception:
        return {"status": "Not Assessed", "score": None, "reason": None}


def get_health_history(account_id):
    """Return manual health lifecycle changes for the selected account."""
    try:
        return get_health_lifecycle(account_id)
    except Exception:
        return []


# ============================================================
# HELPERS
# ============================================================

def safe(value):
    if value is None or str(value).strip() == "":
        return "—"
    return str(value)


def display_date(value):
    if not value:
        return "—"

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", ""))
        return parsed.strftime("%d %b %Y")
    except (ValueError, TypeError):
        return str(value)


def initials(name):
    words = str(name or "AC").strip().split()
    return "".join(word[0] for word in words[:2]).upper()


def health_class(status):
    value = str(status or "").lower()

    if "healthy" in value or value == "green":
        return "healthy"

    if "risk" in value or value == "red":
        return "risk"

    if "attention" in value or value == "yellow":
        return "attention"

    return "not-assessed"


def health_label(status):
    value = str(status or "Not Assessed").lower()

    if value in ("green", "healthy"):
        return "Healthy"

    if value in ("yellow", "needs attention", "attention"):
        return "Needs Attention"

    if value in ("red", "at risk", "risk"):
        return "At Risk"

    return "Not Assessed"


def format_money(value):
    if value is None or value == "":
        return "—"

    try:
        return f"₹{float(value):,.2f}"
    except (ValueError, TypeError):
        return str(value)


def records_to_dataframe(records):
    if not records:
        return pd.DataFrame()

    return pd.DataFrame(records).fillna("")


# ============================================================
# SESSION STATE
# ============================================================

if "page" not in st.session_state:
    st.session_state.page = "accounts"

if "selected_account" not in st.session_state:
    st.session_state.selected_account = None

if "edit_account" not in st.session_state:
    st.session_state.edit_account = None

if "account_search" not in st.session_state:
    st.session_state.account_search = ""

if "account_page_number" not in st.session_state:
    st.session_state.account_page_number = 1

if "show_create_form" not in st.session_state:
    st.session_state.show_create_form = False


def open_account(account_id):
    st.session_state.selected_account = account_id
    st.session_state.page = "details"
    st.session_state.edit_account = None
    st.rerun()


def go_to_accounts():
    st.session_state.page = "accounts"
    st.session_state.selected_account = None
    st.session_state.edit_account = None
    st.session_state.show_create_form = False
    st.rerun()


# ============================================================
# DESIGN SYSTEM
# ============================================================

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=Manrope:wght@400;500;600;700;800&display=swap');

    :root {
        --navy: #101d35;
        --navy-light: #1b2b49;
        --ink: #182338;
        --muted: #7c8799;
        --line: #e8ecf2;
        --surface: #ffffff;
        --canvas: #f5f7fb;
        --blue: #4267e8;
    }

    html, body, [class*="css"] {
        font-family: 'DM Sans', sans-serif;
    }

    .stApp {
        background: var(--canvas);
        color: var(--ink);
    }

    [data-testid="stHeader"] {
        background: transparent;
    }

    [data-testid="stToolbar"] {
        right: 1rem;
    }

    [data-testid="stSidebar"] {
        background: var(--navy);
        border-right: 1px solid rgba(255,255,255,0.06);
    }

    [data-testid="stSidebar"] > div:first-child {
        background: var(--navy);
    }

    [data-testid="stSidebar"] * {
        color: #dbe3f2;
    }

    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
        color: #aab7cc;
    }

    [data-testid="stSidebar"] .stButton button {
        background: rgba(255,255,255,0.08);
        color: white;
        border: 1px solid rgba(255,255,255,0.08);
        text-align: left;
        border-radius: 9px;
        min-height: 42px;
    }

    [data-testid="stSidebar"] .stButton button:hover {
        background: rgba(255,255,255,0.14);
        border-color: rgba(255,255,255,0.16);
    }

    .block-container {
        padding-top: 1.7rem;
        padding-bottom: 3rem;
        max-width: 1600px;
    }

    h1, h2, h3, h4 {
        font-family: 'Manrope', sans-serif;
        color: #17243b;
        letter-spacing: -0.5px;
    }

    .brand-mark {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px 4px 30px 4px;
    }

    .brand-icon {
        height: 42px;
        width: 42px;
        border-radius: 13px;
        background: linear-gradient(145deg, #6586ff, #3d5cda);
        color: white;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 22px;
        font-weight: 800;
        box-shadow: 0 8px 22px rgba(55,90,220,.3);
    }

    .brand-name {
        color: #ffffff;
        font-family: 'Manrope', sans-serif;
        font-size: 20px;
        line-height: 1.1;
        font-weight: 800;
    }

    .brand-subtitle {
        color: #91a2bd;
        font-size: 10px;
        letter-spacing: 1.6px;
        text-transform: uppercase;
        margin-top: 5px;
    }

    .sidebar-caption {
        color: #7588a7;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 1.5px;
        text-transform: uppercase;
        padding: 5px 4px 12px 4px;
    }

    .sidebar-active {
        background: linear-gradient(90deg, rgba(86,119,236,.25), rgba(86,119,236,.08));
        border: 1px solid rgba(117,146,255,.18);
        color: #ffffff;
        border-radius: 9px;
        padding: 12px 13px;
        font-size: 13px;
        font-weight: 700;
        margin-bottom: 8px;
    }

    .sidebar-user {
        border-top: 1px solid rgba(255,255,255,.09);
        padding-top: 18px;
        margin-top: 35px;
        display: flex;
        gap: 10px;
        align-items: center;
    }

    .user-avatar {
        background: #34496d;
        border-radius: 50%;
        height: 36px;
        width: 36px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-size: 12px;
        font-weight: 700;
    }

    .user-name {
        color: white;
        font-size: 12px;
        font-weight: 700;
    }

    .user-role {
        color: #91a2bd;
        font-size: 10px;
        margin-top: 2px;
    }

    .topline {
        display: flex;
        align-items: center;
        justify-content: space-between;
        border-bottom: 1px solid #e9edf3;
        padding-bottom: 17px;
        margin-bottom: 25px;
    }

    .breadcrumb {
        color: #8792a3;
        font-size: 12px;
    }

    .breadcrumb strong {
        color: #273650;
        font-weight: 700;
    }

    .eyebrow {
        font-size: 10px;
        font-weight: 800;
        letter-spacing: 1.5px;
        text-transform: uppercase;
        color: #8290a5;
        margin-bottom: 7px;
    }

    .page-title {
        font-family: 'Manrope', sans-serif;
        font-size: 28px;
        font-weight: 800;
        letter-spacing: -1px;
        color: #17243b;
        margin: 0;
    }

    .page-subtitle {
        color: #8490a2;
        font-size: 13px;
        margin-top: 6px;
    }

    .section-card {
        background: white;
        border: 1px solid #e9edf3;
        border-radius: 13px;
        padding: 19px 21px;
        box-shadow: 0 2px 8px rgba(20,35,60,.025);
        margin-bottom: 16px;
    }

    .section-heading {
        font-family: 'Manrope', sans-serif;
        color: #1d2b43;
        font-size: 15px;
        font-weight: 800;
        margin-bottom: 3px;
    }

    .section-description {
        color: #8a95a5;
        font-size: 11px;
    }

    .table-heading {
        color: #1c2a41;
        font-size: 14px;
        font-weight: 800;
    }

    .table-subheading {
        color: #8a95a5;
        font-size: 11px;
        margin-top: 4px;
    }

    .table-head {
        background: #f7f8fb;
        border-top: 1px solid #edf0f4;
        border-bottom: 1px solid #edf0f4;
        padding: 11px 8px;
        color: #7e8a9d;
        font-size: 10px;
        font-weight: 800;
        letter-spacing: .7px;
        text-transform: uppercase;
    }

    .account-row {
        border-bottom: 1px solid #eff1f5;
        padding: 9px 8px;
        min-height: 58px;
        display: flex;
        align-items: center;
    }

    .company-name {
        color: #243650;
        font-size: 12px;
        font-weight: 700;
    }

    .company-id {
        color: #9aa4b3;
        font-size: 10px;
        margin-top: 3px;
    }

    .cell-text {
        color: #647187;
        font-size: 11px;
    }

    .health-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 5px 9px;
        border-radius: 20px;
        font-size: 10px;
        font-weight: 700;
        white-space: nowrap;
    }

    .health-pill:before {
        content: '';
        width: 6px;
        height: 6px;
        border-radius: 50%;
        display: inline-block;
    }

    .healthy {
        background: #eaf7ef;
        color: #25834a;
    }

    .healthy:before {
        background: #2ea65e;
    }

    .attention {
        background: #fff5df;
        color: #a87413;
    }

    .attention:before {
        background: #e5a52e;
    }

    .risk {
        background: #fff0ef;
        color: #c34d49;
    }

    .risk:before {
        background: #df5a55;
    }

    .not-assessed {
        background: #f0f2f5;
        color: #778295;
    }

    .not-assessed:before {
        background: #aab2be;
    }

    .profile-card {
        background: white;
        border: 1px solid #e9edf3;
        border-radius: 15px;
        padding: 24px;
        margin-bottom: 17px;
        box-shadow: 0 3px 12px rgba(20,35,60,.03);
    }

    .profile-avatar {
        height: 66px;
        width: 66px;
        background: linear-gradient(145deg, #e9edff, #dce4ff);
        color: #4965c9;
        border-radius: 17px;
        display: flex;
        justify-content: center;
        align-items: center;
        font-family: 'Manrope', sans-serif;
        font-size: 22px;
        font-weight: 800;
    }

    .profile-name {
        color: #1b2941;
        font-family: 'Manrope', sans-serif;
        font-size: 22px;
        font-weight: 800;
        letter-spacing: -.6px;
    }

    .profile-meta {
        color: #8994a5;
        font-size: 11px;
        margin-top: 5px;
    }

    .info-label {
        color: #929cad;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: .8px;
        font-weight: 800;
        margin-bottom: 5px;
    }

    .info-value {
        color: #2b3a52;
        font-size: 12px;
        font-weight: 600;
        overflow-wrap: anywhere;
    }

    .info-item {
        padding: 12px 0;
        border-bottom: 1px solid #f0f2f5;
    }

    .timeline-item {
        border-left: 2px solid #dfe6f5;
        padding: 1px 0 17px 16px;
        margin-left: 5px;
    }

    .timeline-title {
        color: #2d3b52;
        font-size: 12px;
        font-weight: 700;
    }

    .timeline-date {
        color: #929cad;
        font-size: 10px;
        margin-top: 4px;
    }

    .empty-state {
        padding: 30px;
        text-align: center;
        color: #929cad;
        font-size: 12px;
    }

    div.stButton > button {
        border-radius: 8px;
        font-size: 11px;
        font-weight: 700;
        min-height: 36px;
        border: 1px solid #e3e8f0;
        color: #40516c;
        background: white;
        transition: all .15s ease;
    }

    div.stButton > button:hover {
        border-color: #a9b9f3;
        color: #3859d2;
        background: #f7f8ff;
    }

    div.stButton > button[kind="primary"] {
        background: #4267e8;
        color: white;
        border: 1px solid #4267e8;
    }

    div.stButton > button[kind="primary"]:hover {
        background: #3155d5;
        border-color: #3155d5;
        color: white;
    }

    div[data-testid="stTextInput"] input,
    div[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
    div[data-testid="stTextArea"] textarea,
    div[data-testid="stNumberInput"] input {
        border-radius: 8px;
        border-color: #e1e6ee;
        font-size: 12px;
    }

    div[data-testid="stTabs"] button {
        font-size: 11px;
        font-weight: 700;
    }

    div[data-testid="stDataFrame"] {
        border: 1px solid #edf0f4;
        border-radius: 9px;
        overflow: hidden;
    }

    .stCaption {
        color: #8a95a5;
    }

    hr {
        border-color: #edf0f4;
    }

    @media (max-width: 900px) {
        .page-title {
            font-size: 23px;
        }
    }
    </style>
    """,
    unsafe_allow_html=True
)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown(
        """
        <div class="brand-mark">
            <div class="brand-icon">◈</div>
            <div>
                <div class="brand-name">AccountIQ</div>
                <div class="brand-subtitle">Intelligence CRM</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="sidebar-caption">WORKSPACE</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="sidebar-active">▦ &nbsp; Accounts</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        """
        <div class="sidebar-user">
            <div class="user-avatar">AD</div>
            <div>
                <div class="user-name">Administrator</div>
                <div class="user-role">CRM Administrator</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


# ============================================================
# TOP BAR
# ============================================================

if st.session_state.page == "details":
    account_for_breadcrumb = get_account(
        st.session_state.selected_account
    ) if st.session_state.selected_account else None

    breadcrumb_name = (
        account_for_breadcrumb.get("name", "Account Details")
        if account_for_breadcrumb else "Account Details"
    )

    st.markdown(
        f"""
        <div class="topline">
            <div class="breadcrumb">
                Accounts &nbsp; / &nbsp;
                <strong>{html.escape(str(breadcrumb_name))}</strong>
            </div>
            <div class="breadcrumb">Administrator &nbsp; ◉</div>
        </div>
        """,
        unsafe_allow_html=True
    )

else:
    st.markdown(
        """
        <div class="topline">
            <div class="breadcrumb">
                Workspace &nbsp; / &nbsp; <strong>Accounts</strong>
            </div>
            <div class="breadcrumb">Administrator &nbsp; ◉</div>
        </div>
        """,
        unsafe_allow_html=True
    )


# ============================================================
# ACCOUNTS PAGE
# ============================================================

def render_accounts_page():

    accounts = get_accounts()

    st.markdown(
        """
        <div class="eyebrow">ACCOUNT MANAGEMENT</div>
        <div class="page-title">Accounts</div>
        <div class="page-subtitle">
            View and manage your customer accounts in one place.
        </div>
        """,
        unsafe_allow_html=True
    )

    st.write("")

    # Toolbar
    toolbar_left, toolbar_right = st.columns([3, 2])

    with toolbar_left:
        st.markdown(
            f"""
            <div style="padding-top:11px;color:#8290a2;font-size:11px;">
                <strong style="color:#25344c;">{len(accounts)}</strong>
                accounts in your CRM
            </div>
            """,
            unsafe_allow_html=True
        )

    with toolbar_right:
        action_cols = st.columns([1, 1, 1.5])

        with action_cols[0]:
            if st.button("＋ Create", use_container_width=True):
                st.session_state.show_create_form = (
                    not st.session_state.show_create_form
                )
                st.session_state.edit_account = None
                st.rerun()

        with action_cols[1]:
            export_data = pd.DataFrame(accounts).to_csv(index=False)
            st.download_button(
                "↓ Export",
                data=export_data,
                file_name="accounts_export.csv",
                mime="text/csv",
                use_container_width=True
            )

        with action_cols[2]:
            uploaded_file = st.file_uploader(
                "Import CSV",
                type=["csv"],
                label_visibility="collapsed",
                key="account_csv_upload"
            )

    # Create account form
    if st.session_state.show_create_form:
        render_account_form()

    # Edit account form
    if st.session_state.edit_account:
        render_account_form(st.session_state.edit_account)

    st.write("")

    # Search and filters
    with st.container(border=True):
        st.markdown(
            '<div class="section-heading">Find an account</div>',
            unsafe_allow_html=True
        )

        search_col, industry_col, status_col, region_col = st.columns(
            [2.2, 1.2, 1, 1.2]
        )

        with search_col:
            search = st.text_input(
                "Search",
                placeholder="Search company, ID, phone or website...",
                key="account_search_input"
            )

        industries = sorted({
            str(a.get("industry"))
            for a in accounts
            if a.get("industry")
        })

        with industry_col:
            selected_industry = st.selectbox(
                "Industry",
                ["All industries"] + industries
            )

        with status_col:
            selected_status = st.selectbox(
                "Status",
                ["All statuses", "Active", "Inactive"]
            )

        regions = sorted({
            str(a.get("region"))
            for a in accounts
            if a.get("region")
        })

        with region_col:
            selected_region = st.selectbox(
                "Region",
                ["All regions"] + regions
            )

    # Filter
    filtered = []

    for account in accounts:
        search_text = " ".join([
            str(account.get("id") or ""),
            str(account.get("name") or ""),
            str(account.get("company_phone") or ""),
            str(account.get("email") or ""),
            str(account.get("website") or ""),
            str(account.get("industry") or ""),
            str(account.get("location") or "")
        ]).lower()

        if search.strip() and search.lower().strip() not in search_text:
            continue

        if (
            selected_industry != "All industries"
            and account.get("industry") != selected_industry
        ):
            continue

        if (
            selected_status != "All statuses"
            and str(account.get("status") or "").lower()
            != selected_status.lower()
        ):
            continue

        if (
            selected_region != "All regions"
            and account.get("region") != selected_region
        ):
            continue

        filtered.append(account)

    st.write("")

    # Table heading and controls
    heading_col, page_size_col = st.columns([3, 1])

    with heading_col:
        st.markdown(
            """
            <div class="table-heading">Account Directory</div>
            <div class="table-subheading">
                Select a company to view its complete account profile.
            </div>
            """,
            unsafe_allow_html=True
        )

    with page_size_col:
        page_size = st.selectbox(
            "Rows per page",
            [10, 20, 50],
            index=0
        )

    st.write("")

    # Sorting
    sort_col, direction_col = st.columns([2, 1])

    with sort_col:
        sort_by = st.selectbox(
            "Sort accounts by",
            ["Company name", "Industry", "Region", "Last updated"]
        )

    with direction_col:
        sort_direction = st.selectbox(
            "Order",
            ["Ascending", "Descending"]
        )

    sort_keys = {
        "Company name": "name",
        "Industry": "industry",
        "Region": "region",
        "Last updated": "last_updated"
    }

    sort_key = sort_keys[sort_by]

    filtered.sort(
        key=lambda item: str(item.get(sort_key) or "").lower(),
        reverse=(sort_direction == "Descending")
    )

    total = len(filtered)
    total_pages = max(1, (total + page_size - 1) // page_size)

    if st.session_state.account_page_number > total_pages:
        st.session_state.account_page_number = total_pages

    current_page = st.session_state.account_page_number
    start = (current_page - 1) * page_size
    page_accounts = filtered[start:start + page_size]

    # Account table
    with st.container(border=True):

        st.markdown(
            f"""
            <div style="display:flex;justify-content:space-between;
            align-items:center;padding:3px 3px 15px 3px;">
                <div class="table-heading">All Accounts</div>
                <div style="color:#8a95a5;font-size:11px;">
                    Showing {len(page_accounts)} of {total} accounts
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

        header = st.columns([0.45, 2.0, 1.15, 1.5, 1.05, 1.05, 1.25, 0.9])

        headers = [
            "S.NO",
            "COMPANY NAME",
            "PHONE",
            "WEBSITE",
            "SERVICE",
            "PRODUCT",
            "HEALTH",
            "ACTION"
        ]

        for col, label in zip(header, headers):
            with col:
                st.markdown(
                    f'<div class="table-head">{label}</div>',
                    unsafe_allow_html=True
                )

        if not page_accounts:
            st.markdown(
                '<div class="empty-state">No accounts match your filters.</div>',
                unsafe_allow_html=True
            )

        for index, account in enumerate(page_accounts, start=start + 1):
            account_id = str(account.get("id") or "")
            name = str(account.get("name") or "Unnamed account")

            health = get_health_status(account_id)
            label = health_label(health["status"])
            css_class = health_class(health["status"])

            row = st.columns(
                [0.45, 2.0, 1.15, 1.5, 1.05, 1.05, 1.25, 0.9],
                vertical_alignment="center"
            )

            with row[0]:
                st.markdown(
                    f'<div class="cell-text">{index}</div>',
                    unsafe_allow_html=True
                )

            with row[1]:
                if st.button(
                    name,
                    key=f"open_company_{account_id}",
                    help="Open account details",
                    use_container_width=True
                ):
                    open_account(account_id)

                st.markdown(
                    f'<div class="company-id">{html.escape(account_id)}</div>',
                    unsafe_allow_html=True
                )

            with row[2]:
                st.markdown(
                    f'<div class="cell-text">{html.escape(safe(account.get("company_phone")))}</div>',
                    unsafe_allow_html=True
                )

            with row[3]:
                website = safe(account.get("website"))
                st.markdown(
                    f'<div class="cell-text">{html.escape(website)}</div>',
                    unsafe_allow_html=True
                )

            with row[4]:
                st.markdown(
                    f'<div class="cell-text">{html.escape(safe(account.get("service")))}</div>',
                    unsafe_allow_html=True
                )

            with row[5]:
                st.markdown(
                    f'<div class="cell-text">{html.escape(safe(account.get("product")))}</div>',
                    unsafe_allow_html=True
                )

            with row[6]:
                st.markdown(
                    f'<span class="health-pill {css_class}">{html.escape(label)}</span>',
                    unsafe_allow_html=True
                )

            with row[7]:
                if st.button(
                    "View →",
                    key=f"view_account_{account_id}",
                    use_container_width=True
                ):
                    open_account(account_id)

                if st.button(
                    "Edit",
                    key=f"edit_account_{account_id}",
                    use_container_width=True
                ):
                    st.session_state.edit_account = account_id
                    st.session_state.show_create_form = False
                    st.rerun()

            st.markdown(
                '<div style="height:1px;background:#eff1f5;margin:3px 0 7px 0;"></div>',
                unsafe_allow_html=True
            )

    # Pagination
    st.write("")

    prev_col, page_col, next_col = st.columns([1, 3, 1])

    with prev_col:
        if st.button(
            "← Previous",
            disabled=current_page <= 1,
            use_container_width=True
        ):
            st.session_state.account_page_number -= 1
            st.rerun()

    with page_col:
        st.markdown(
            f"""
            <div style="text-align:center;color:#8792a3;
            font-size:11px;padding-top:10px;">
                Page <strong style="color:#263650;">{current_page}</strong>
                of <strong style="color:#263650;">{total_pages}</strong>
            </div>
            """,
            unsafe_allow_html=True
        )

    with next_col:
        if st.button(
            "Next →",
            disabled=current_page >= total_pages,
            use_container_width=True
        ):
            st.session_state.account_page_number += 1
            st.rerun()

    # Import CSV
    if uploaded_file is not None:
        try:
            imported_df = pd.read_csv(uploaded_file)
            imported_df.columns = [
                str(column).strip().lower()
                for column in imported_df.columns
            ]

            if "name" not in imported_df.columns:
                st.error("The CSV must contain a 'name' column.")
            else:
                if st.button("Confirm CSV Import", type="primary"):
                    count = 0

                    allowed = set(get_columns_for_accounts())

                    for _, record in imported_df.iterrows():
                        payload = {}

                        for key, value in record.to_dict().items():
                            if key in allowed and key != "id":
                                payload[key] = (
                                    None if pd.isna(value) else str(value)
                                )

                        if payload.get("name"):
                            save_account(payload)
                            count += 1

                    st.success(f"{count} accounts imported.")
                    st.rerun()

        except Exception as error:
            st.error(f"Could not read CSV: {error}")


def get_columns_for_accounts():
    conn = get_connection()
    try:
        return get_columns(conn, "accounts")
    finally:
        conn.close()


# ============================================================
# CREATE / EDIT ACCOUNT FORM
# ============================================================

def render_account_form(account_id=None):

    account = get_account(account_id) if account_id else {}

    editing = bool(account_id)

    st.markdown("---")

    st.markdown(
        f"""
        <div class="section-heading">
            {"Edit Account" if editing else "Create New Account"}
        </div>
        <div class="section-description">
            {"Update the account information below." if editing else "Add a new company to your account directory."}
        </div>
        """,
        unsafe_allow_html=True
    )

    with st.form(
        key=f"account_form_{account_id or 'new'}",
        clear_on_submit=False
    ):

        st.markdown("**Company Information**")

        c1, c2 = st.columns(2)

        with c1:
            name = st.text_input(
                "Company name *",
                value=account.get("name") or ""
            )

            industry = st.text_input(
                "Industry",
                value=account.get("industry") or ""
            )

            phone = st.text_input(
                "Company phone",
                value=account.get("company_phone") or ""
            )

            email = st.text_input(
                "Email",
                value=account.get("email") or ""
            )

        with c2:
            website = st.text_input(
                "Website",
                value=account.get("website") or ""
            )

            status_options = ["Active", "Inactive"]
            current_status = account.get("status") or "Active"

            status_index = (
                status_options.index(current_status)
                if current_status in status_options else 0
            )

            status = st.selectbox(
                "Account status",
                status_options,
                index=status_index
            )

            service = st.text_input(
                "Service",
                value=account.get("service") or ""
            )

            product = st.text_input(
                "Product",
                value=account.get("product") or ""
            )

        st.markdown("**Location Information**")

        l1, l2 = st.columns(2)

        with l1:
            address1 = st.text_input(
                "Address line 1",
                value=account.get("address_line1") or ""
            )

            address2 = st.text_input(
                "Address line 2",
                value=account.get("address_line2") or ""
            )

            region = st.text_input(
                "Region",
                value=account.get("region") or ""
            )

        with l2:
            location = st.text_input(
                "City / Location",
                value=account.get("location") or ""
            )

            postal_code = st.text_input(
                "Postal code",
                value=account.get("postal_code") or ""
            )

            account_type = st.text_input(
                "Account type",
                value=account.get("account_type") or ""
            )

        st.markdown("**Additional Information**")

        annual_revenue = st.text_input(
            "Annual revenue",
            value=str(account.get("annual_revenue") or "")
        )

        notes = st.text_area(
            "Additional notes",
            value=account.get("additional_notes") or "",
            height=90
        )

        save_col, cancel_col = st.columns([1, 1])

        with save_col:
            submitted = st.form_submit_button(
                "Save Account",
                type="primary",
                use_container_width=True
            )

        with cancel_col:
            cancelled = st.form_submit_button(
                "Cancel",
                use_container_width=True
            )

    if cancelled:
        st.session_state.edit_account = None
        st.session_state.show_create_form = False
        st.rerun()

    if submitted:

        if not name.strip():
            st.error("Company name is required.")
            return

        revenue_value = annual_revenue.strip() or None

        payload = {
            "name": name.strip(),
            "industry": industry.strip() or None,
            "company_phone": phone.strip() or None,
            "email": email.strip() or None,
            "website": website.strip() or None,
            "status": status,
            "service": service.strip() or None,
            "product": product.strip() or None,
            "address_line1": address1.strip() or None,
            "address_line2": address2.strip() or None,
            "region": region.strip() or None,
            "location": location.strip() or None,
            "postal_code": postal_code.strip() or None,
            "account_type": account_type.strip() or None,
            "annual_revenue": revenue_value,
            "additional_notes": notes.strip() or None
        }

        try:
            save_account(payload, account_id if editing else None)

            st.success(
                "Account updated successfully."
                if editing else "Account created successfully."
            )

            st.session_state.edit_account = None
            st.session_state.show_create_form = False
            st.rerun()

        except Exception as error:
            st.error(f"Could not save account: {error}")


# ============================================================
# ACCOUNT INTELLIGENCE AND DOCUMENTS
# ============================================================

def render_health_management(account_id):
    """Health controls: refresh, manual override, restore, and audit history."""
    with st.container(border=True):
        st.markdown('<div class="section-heading">Account Intelligence</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="section-description">Calculated health, risk signals and manual status controls</div>',
            unsafe_allow_html=True
        )

        try:
            intelligence = get_effective_health(account_id)
        except Exception as error:
            intelligence = {"status": "error", "message": str(error)}

        if intelligence.get("status") == "success":
            calculated = intelligence.get("health_status", "Not Assessed")
            effective = intelligence.get("effective_health_status", calculated)
            score = intelligence.get("calculated_score")
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Calculated score", f"{score:.1f}" if score is not None else "—")
            with c2:
                st.metric("Calculated status", calculated)
            with c3:
                st.metric("Effective status", effective)

            if intelligence.get("provisional"):
                st.caption("Provisional scoring model — weights and thresholds require business approval.")

            override = intelligence.get("manual_override")
            if override:
                st.info(
                    f"Manual override: {override.get('manual_status')} — "
                    f"{override.get('override_reason')}"
                )
        else:
            st.warning(intelligence.get("message", "Health assessment is not available."))

        with st.expander("Change health status manually"):
            with st.form(key=f"health_override_form_{account_id}"):
                new_status = st.selectbox("New health status", ["Green", "Yellow", "Red"], key=f"health_status_{account_id}")
                reason = st.text_area(
                    "Reason (required)",
                    placeholder="Example: Recent follow-up completed, but purchase confirmation is still pending.",
                    key=f"health_reason_{account_id}"
                )
                changed_by = st.text_input("Changed by", value="CRM User", key=f"health_user_{account_id}")
                submitted = st.form_submit_button("Save health status", type="primary", use_container_width=True)

            if submitted:
                if not reason.strip():
                    st.error("A reason is required for a manual status change.")
                else:
                    result = set_manual_health_status(account_id, new_status, reason, changed_by)
                    if result.get("status") == "success":
                        st.success(f"Health status changed to {new_status}.")
                        st.rerun()
                    else:
                        st.error(result.get("message", "Could not save the status."))

        action1, action2 = st.columns(2)
        with action1:
            if st.button("↻ Refresh intelligence", key=f"refresh_intel_{account_id}", use_container_width=True):
                with st.spinner("Recalculating account intelligence..."):
                    result = refresh_account_intelligence(account_id)
                if result.get("status") == "success":
                    st.success("Account intelligence refreshed and saved.")
                    st.rerun()
                else:
                    st.error(result.get("message", "Refresh failed."))

        with action2:
            if st.button("Restore calculated status", key=f"restore_intel_{account_id}", use_container_width=True):
                result = clear_manual_health_override(account_id, "CRM User")
                if result.get("status") == "success":
                    st.success("Manual override cleared. Calculated status restored.")
                    st.rerun()
                else:
                    st.info(result.get("message", "No active manual override."))

        try:
            from intelligence.risk_analysis import analyze_account_risks
            from intelligence.expansion_analysis import identify_expansion_opportunities
            from intelligence.recommendations import recommend_next_actions

            risks = analyze_account_risks(account_id)
            expansion = identify_expansion_opportunities(account_id)
            recommendations = recommend_next_actions(account_id)

            st.markdown("**Risk alerts**")
            risk_items = risks.get("risks", [])
            if risk_items:
                for item in risk_items:
                    st.warning(f"{item.get('type')}: {item.get('reason')}\n\nNext action: {item.get('recommendation')}")
            else:
                st.caption("No rule-based risk alerts were identified from available records.")

            st.markdown("**Expansion signals**")
            signals = expansion.get("signals", [])
            if signals:
                for item in signals:
                    st.write(f"• **{item.get('type')}** — {item.get('signal')}")
                    st.caption(item.get("interpretation", ""))
            else:
                st.caption("No expansion signals identified from the available CRM data.")

            st.markdown("**Recommended next actions**")
            actions = recommendations.get("actions", [])
            if actions:
                for item in actions:
                    st.write(f"• **{item.get('priority')} priority:** {item.get('action')}")
                    if item.get("reason"):
                        st.caption(item["reason"])
            else:
                st.caption("No recommendations are currently available.")

        except Exception as error:
            st.warning(f"Could not load all intelligence sections: {error}")

        history = get_health_history(account_id)
        if history:
            st.markdown("**Health status change history**")
            st.dataframe(records_to_dataframe(history), use_container_width=True, hide_index=True)


def render_account_documents(account_id):
    with st.container(border=True):
        st.markdown('<div class="section-heading">Account Documents</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="section-description">Upload, download and manage document versions for this account</div>',
            unsafe_allow_html=True
        )

        with st.expander("Upload a document"):
            with st.form(key=f"document_upload_form_{account_id}"):
                uploaded_file = st.file_uploader(
                    "Choose a file",
                    type=["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv", "png", "jpg", "jpeg"],
                    key=f"document_file_{account_id}"
                )
                c1, c2 = st.columns(2)
                with c1:
                    document_type = st.selectbox(
                        "Document type",
                        ["Contract", "Quotation", "Purchase Order", "Invoice", "Agreement", "Technical", "Other"],
                        key=f"document_type_{account_id}"
                    )
                with c2:
                    category = st.selectbox(
                        "Category",
                        ["Commercial", "Legal", "Technical", "Finance", "General"],
                        key=f"document_category_{account_id}"
                    )
                description = st.text_input("Description", key=f"document_description_{account_id}")
                change_notes = st.text_input("Version notes", value="Uploaded through AccountIQ", key=f"document_notes_{account_id}")
                upload_submitted = st.form_submit_button("Upload document", type="primary", use_container_width=True)

            if upload_submitted:
                if uploaded_file is None:
                    st.error("Please choose a file first.")
                else:
                    uploaded_file.seek(0)
                    result = upload_account_document(
                        account_id=account_id,
                        uploaded_file=uploaded_file,
                        document_type=document_type,
                        category=category,
                        description=description,
                        change_notes=change_notes
                    )
                    if result.get("status") == "success":
                        st.success(f"Uploaded {result['document_name']} (version {result['version']}).")
                        st.rerun()
                    else:
                        st.error(result.get("message", "Document upload failed."))

        documents = list_account_documents(account_id)
        if not documents:
            st.caption("No documents have been uploaded for this account.")
            return

        for document in documents:
            title = f"{document.get('document_name', 'Document')} · v{document.get('current_version') or 1}"
            with st.expander(title):
                c1, c2 = st.columns(2)
                with c1:
                    st.write("**Type:**", document.get("document_type") or "—")
                    st.write("**Category:**", document.get("category") or "—")
                with c2:
                    st.write("**Uploaded:**", display_date(document.get("uploaded_at")))
                    st.write("**Description:**", document.get("description") or "—")

                try:
                    file_path = get_document_path(document.get("storage_path") or "")
                    with file_path.open("rb") as file_handle:
                        file_bytes = file_handle.read()
                    st.download_button(
                        "Download document",
                        data=file_bytes,
                        file_name=document.get("document_name") or file_path.name,
                        key=f"download_document_{document.get('document_id')}",
                        use_container_width=True
                    )
                except Exception as error:
                    st.warning(f"Document file could not be opened: {error}")

                versions = get_document_versions(document.get("document_id"))
                if versions:
                    st.markdown("**Version history**")
                    st.dataframe(records_to_dataframe(versions), use_container_width=True, hide_index=True)


# ============================================================
# ACCOUNT DETAILS PAGE
# ============================================================

def render_info_item(label, value):
    st.markdown(
        f"""
        <div class="info-item">
            <div class="info-label">{html.escape(str(label))}</div>
            <div class="info-value">{html.escape(safe(value))}</div>
        </div>
        """,
        unsafe_allow_html=True
    )


def render_account_details():

    account_id = st.session_state.selected_account

    if not account_id:
        st.warning("No account selected.")
        if st.button("Back to Accounts"):
            go_to_accounts()
        return

    account = get_account(account_id)

    if not account:
        st.error("The selected account could not be found.")
        if st.button("Back to Accounts"):
            go_to_accounts()
        return

    # Navigation
    back_col, edit_col = st.columns([4, 1])

    with back_col:
        if st.button("← Back to Accounts"):
            go_to_accounts()

    with edit_col:
        if st.button("Edit Account", type="primary"):
            st.session_state.edit_account = account_id
            st.session_state.page = "details_edit"
            st.rerun()

    if st.session_state.page == "details_edit":
        render_account_form(account_id)
        return

    st.write("")

    # Profile
    health = get_health_status(account_id)
    health_text = health_label(health["status"])
    health_css = health_class(health["status"])

    name = account.get("name") or "Unnamed account"
    location_text = ", ".join(
        str(x) for x in [
            account.get("location"),
            account.get("region")
        ] if x
    )

    st.markdown(
        f"""
        <div class="profile-card">
            <div style="display:flex;align-items:center;gap:18px;
            flex-wrap:wrap;">
                <div class="profile-avatar">
                    {html.escape(initials(name))}
                </div>
                <div style="flex:1;min-width:180px;">
                    <div class="eyebrow">ACCOUNT PROFILE</div>
                    <div class="profile-name">{html.escape(name)}</div>
                    <div class="profile-meta">
                        {html.escape(str(account.get("id") or ""))}
                        &nbsp; · &nbsp;
                        {html.escape(location_text or "Location not available")}
                    </div>
                </div>
                <div style="display:flex;gap:8px;align-items:center;
                flex-wrap:wrap;">
                    <span class="health-pill {health_css}">
                        {html.escape(health_text)}
                    </span>
                    <span style="background:#edf2ff;color:#4964c8;
                    padding:6px 10px;border-radius:20px;
                    font-size:10px;font-weight:700;">
                        {html.escape(safe(account.get("status")))}
                    </span>
                </div>
            </div>
            <div style="height:1px;background:#edf0f4;margin:20px 0;"></div>
            <div style="display:grid;grid-template-columns:
            repeat(auto-fit,minmax(160px,1fr));gap:18px;">
                <div>
                    <div class="info-label">EMAIL</div>
                    <div class="info-value">{html.escape(safe(account.get("email")))}</div>
                </div>
                <div>
                    <div class="info-label">PHONE</div>
                    <div class="info-value">{html.escape(safe(account.get("company_phone")))}</div>
                </div>
                <div>
                    <div class="info-label">WEBSITE</div>
                    <div class="info-value">{html.escape(safe(account.get("website")))}</div>
                </div>
                <div>
                    <div class="info-label">INDUSTRY</div>
                    <div class="info-value">{html.escape(safe(account.get("industry")))}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # Main details and health
    left, right = st.columns([1.65, 1])

    with left:
        with st.container(border=True):
            st.markdown(
                '<div class="section-heading">Account Information</div>'
                '<div class="section-description">Company and business details</div>',
                unsafe_allow_html=True
            )

            a, b = st.columns(2)

            with a:
                render_info_item("Company name", account.get("name"))
                render_info_item("Industry", account.get("industry"))
                render_info_item("Service", account.get("service"))
                render_info_item("Product", account.get("product"))
                render_info_item("Account type", account.get("account_type"))

            with b:
                render_info_item("Address line 1", account.get("address_line1"))
                render_info_item("Address line 2", account.get("address_line2"))
                render_info_item("Location", account.get("location"))
                render_info_item("Region", account.get("region"))
                render_info_item("Postal code", account.get("postal_code"))

            render_info_item("Annual revenue", account.get("annual_revenue"))
            render_info_item("Additional notes", account.get("additional_notes"))

    with right:
        with st.container(border=True):
            st.markdown(
                '<div class="section-heading">Account Health</div>'
                '<div class="section-description">Current available health assessment</div>',
                unsafe_allow_html=True
            )

            st.markdown(
                f"""
                <div style="padding:17px 0 12px 0;">
                    <span class="health-pill {health_css}">
                        {html.escape(health_text)}
                    </span>
                </div>
                """,
                unsafe_allow_html=True
            )

            if health["score"] is not None:
                st.metric("Calculated health score", health["score"])
            else:
                st.caption("No calculated health score is currently available.")

            if health["reason"]:
                st.markdown("**Status reason**")
                st.write(health["reason"])

            st.caption(
                "Account health is separate from the account's Active/Inactive status."
            )

        with st.container(border=True):
            st.markdown(
                '<div class="section-heading">Record Information</div>',
                unsafe_allow_html=True
            )

            render_info_item("Account ID", account.get("id"))
            render_info_item("Created on", display_date(account.get("created_on")))
            render_info_item("Last updated", display_date(account.get("last_updated")))

    # Account intelligence controls and evidence-backed insights
    st.write("")
    render_health_management(account_id)

    # Activities and history
    st.write("")

    activities = get_account_activities(account_id)

    activity_col, history_col = st.columns([1.15, 1])

    with activity_col:
        with st.container(border=True):
            st.markdown(
                '<div class="section-heading">Upcoming Activities</div>'
                '<div class="section-description">Scheduled account interactions</div>',
                unsafe_allow_html=True
            )

            upcoming = []

            for activity in activities:
                done = activity.get("done")
                status = str(activity.get("status") or "").lower()

                if done in (1, True, "1") or status == "completed":
                    continue

                due = activity.get("due_at") or activity.get("occurred_at")

                if due:
                    try:
                        due_date = datetime.fromisoformat(
                            str(due).replace("Z", "")
                        )
                        if due_date.date() >= date.today():
                            upcoming.append(activity)
                    except ValueError:
                        pass

            upcoming.sort(
                key=lambda item: str(item.get("due_at") or "")
            )

            if not upcoming:
                st.markdown(
                    '<div class="empty-state">'
                    'No upcoming activities found for this account.'
                    '</div>',
                    unsafe_allow_html=True
                )
            else:
                for activity in upcoming[:6]:
                    title = (
                        activity.get("title")
                        or activity.get("kind")
                        or "Activity"
                    )

                    st.markdown(
                        f"""
                        <div class="timeline-item">
                            <div class="timeline-title">
                                {html.escape(str(title))}
                            </div>
                            <div class="timeline-date">
                                {html.escape(display_date(activity.get("due_at") or activity.get("occurred_at")))}
                                &nbsp; · &nbsp;
                                {html.escape(safe(activity.get("kind")))}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

    with history_col:
        with st.container(border=True):
            st.markdown(
                '<div class="section-heading">Account History</div>'
                '<div class="section-description">Recent recorded interactions</div>',
                unsafe_allow_html=True
            )

            history = [
                item for item in activities
                if item.get("occurred_at")
            ]

            history.sort(
                key=lambda item: str(item.get("occurred_at") or ""),
                reverse=True
            )

            if not history:
                st.markdown(
                    '<div class="empty-state">No activity history available.</div>',
                    unsafe_allow_html=True
                )
            else:
                for item in history[:6]:
                    title = (
                        item.get("title")
                        or item.get("kind")
                        or "Activity"
                    )

                    st.markdown(
                        f"""
                        <div class="timeline-item">
                            <div class="timeline-title">
                                {html.escape(str(title))}
                            </div>
                            <div class="timeline-date">
                                {html.escape(display_date(item.get("occurred_at")))}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

    # Health lifecycle
    health_history = get_health_history(account_id)

    if health_history:
        with st.container(border=True):
            st.markdown(
                '<div class="section-heading">Health Status History</div>'
                '<div class="section-description">Recorded health status changes</div>',
                unsafe_allow_html=True
            )

            st.dataframe(
                records_to_dataframe(health_history),
                use_container_width=True,
                hide_index=True
            )

    # Account-scoped documents and version history
    st.write("")
    render_account_documents(account_id)

    # Related records
    st.write("")

    with st.container(border=True):
        st.markdown(
            '<div class="section-heading">Related Records</div>'
            '<div class="section-description">'
            'View records associated with this account.'
            '</div>',
            unsafe_allow_html=True
        )

        tab_names = list(RELATED_TABLES.keys())
        tabs = st.tabs(tab_names)

        for tab, label in zip(tabs, tab_names):
            with tab:
                table_name = RELATED_TABLES[label]
                records = get_related_records(account_id, table_name)

                st.markdown(
                    f"""
                    <div style="color:#8792a3;font-size:11px;
                    padding:7px 0 12px 0;">
                        {len(records)} {label.lower()} linked to this account
                    </div>
                    """,
                    unsafe_allow_html=True
                )

                if records:
                    df = records_to_dataframe(records)

                    # Hide internal/empty columns for a cleaner table.
                    useful_columns = [
                        column for column in df.columns
                        if not column.startswith("_")
                    ]

                    df = df[useful_columns]

                    st.dataframe(
                        df,
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.markdown(
                        f'<div class="empty-state">No {label.lower()} linked to this account.</div>',
                        unsafe_allow_html=True
                    )


# ============================================================
# MAIN ROUTER
# ============================================================

try:
    # Verify that the database and required accounts table exist.
    conn = get_connection()
    tables = get_tables(conn)
    conn.close()

    if "accounts" not in tables:
        st.error(
            "The database exists, but the required 'accounts' table "
            "was not found."
        )
        st.stop()

    if st.session_state.page == "accounts":
        render_accounts_page()

    elif st.session_state.page in ("details", "details_edit"):
        render_account_details()

    else:
        st.session_state.page = "accounts"
        st.rerun()

except sqlite3.Error as error:
    st.error(f"Database error: {error}")

except Exception as error:
    st.error(f"Application error: {error}")
    st.exception(error)
