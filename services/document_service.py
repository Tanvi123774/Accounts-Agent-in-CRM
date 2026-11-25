
import sqlite3
import shutil
import uuid

from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).resolve().parents[1] / "account_agent.db"
DOCUMENT_ROOT = Path(__file__).resolve().parents[1] / "account_documents"

ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".ppt", ".pptx", ".txt", ".csv", ".png",
    ".jpg", ".jpeg"
}


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_document_storage():
    DOCUMENT_ROOT.mkdir(parents=True, exist_ok=True)


def upload_account_document(
    account_id,
    uploaded_file,
    document_type="Other",
    category="General",
    description="",
    uploaded_by="CRM User",
    change_notes="Initial upload"
):
    initialize_document_storage()

    filename = Path(uploaded_file.name).name
    extension = Path(filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        return {
            "status": "error",
            "message": f"File type {extension} is not allowed."
        }

    with connect() as conn:
        account = conn.execute(
            "SELECT id FROM accounts WHERE id = ?",
            (account_id,)
        ).fetchone()

        if not account:
            return {"status": "not_found", "account_id": account_id}

        existing = conn.execute("""
            SELECT * FROM account_documents
            WHERE account_id = ? AND document_name = ?
            ORDER BY uploaded_at DESC
            LIMIT 1
        """, (account_id, filename)).fetchone()

        now = datetime.now().isoformat(timespec="seconds")

        if existing:
            document_id = existing["document_id"]
            version = int(existing["current_version"] or 1) + 1
        else:
            document_id = "DOC-" + uuid.uuid4().hex[:12].upper()
            version = 1

        account_folder = DOCUMENT_ROOT / account_id
        account_folder.mkdir(parents=True, exist_ok=True)

        stored_name = f"{document_id}_v{version}{extension}"
        destination = account_folder / stored_name

        with destination.open("wb") as output:
            shutil.copyfileobj(uploaded_file, output)

        relative_path = str(destination.relative_to(
            Path(__file__).resolve().parents[1]
        ))

        if existing:
            conn.execute("""
                UPDATE account_documents
                SET current_version = ?,
                    file_url = ?,
                    storage_path = ?,
                    uploaded_by = ?,
                    uploaded_at = ?,
                    status = 'Active',
                    description = ?
                WHERE document_id = ?
            """, (
                version, relative_path, relative_path,
                uploaded_by, now, description, document_id
            ))
        else:
            conn.execute("""
                INSERT INTO account_documents (
                    document_id, account_id, document_name,
                    document_type, category, file_url, storage_path,
                    uploaded_by, uploaded_at, current_version,
                    status, description
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                document_id, account_id, filename,
                document_type, category, relative_path,
                relative_path, uploaded_by, now, version,
                "Active", description
            ))

        conn.execute("""
            UPDATE account_document_versions
            SET is_current = 0
            WHERE document_id = ?
        """, (document_id,))

        conn.execute("""
            INSERT INTO account_document_versions (
                document_version_id, document_id, version_number,
                file_url, storage_path, uploaded_by, uploaded_at,
                change_notes, is_current
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            "VER-" + uuid.uuid4().hex[:12].upper(),
            document_id,
            version,
            relative_path,
            relative_path,
            uploaded_by,
            now,
            change_notes
        ))

    return {
        "status": "success",
        "document_id": document_id,
        "document_name": filename,
        "version": version,
        "storage_path": relative_path
    }


def list_account_documents(account_id):
    with connect() as conn:
        records = conn.execute("""
            SELECT *
            FROM account_documents
            WHERE account_id = ?
            ORDER BY uploaded_at DESC
        """, (account_id,)).fetchall()

    return [dict(x) for x in records]


def get_document_versions(document_id):
    with connect() as conn:
        records = conn.execute("""
            SELECT *
            FROM account_document_versions
            WHERE document_id = ?
            ORDER BY version_number DESC
        """, (document_id,)).fetchall()

    return [dict(x) for x in records]


def get_document_path(storage_path):
    project_root = Path(__file__).resolve().parents[1]
    path = (project_root / storage_path).resolve()

    if not path.is_relative_to(DOCUMENT_ROOT.resolve()):
        raise ValueError("Invalid document storage path.")

    if not path.exists() or not path.is_file():
        raise FileNotFoundError("Document file not found.")

    return path
