
import json
import sqlite3
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"
DB_PATH = BASE_DIR / "account_agent.db"

HOST = "127.0.0.1"
PORT = 8000


# ---------------- DATABASE ----------------

def connect_db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def fetch_all(query, params=()):
    with connect_db() as db:
        return [dict(row) for row in db.execute(query, params).fetchall()]


def fetch_one(query, params=()):
    with connect_db() as db:
        row = db.execute(query, params).fetchone()
        return dict(row) if row else {}


def get_table_data(table):
    allowed = {
        "contacts": """
            SELECT c.*, a.name AS account_name
            FROM contacts c
            LEFT JOIN accounts a ON a.id = c.account_id
            ORDER BY c.id
        """,
        "leads": """
            SELECT l.*, a.name AS company_name
            FROM leads l
            LEFT JOIN accounts a ON a.id = l.account_id
            ORDER BY l.id
        """,
        "opportunities": """
            SELECT o.*, a.name AS company_name
            FROM opportunities o
            LEFT JOIN accounts a ON a.id = o.account_id
            ORDER BY o.id
        """,
        "activities": """
            SELECT x.*, a.name AS company_name
            FROM activities x
            LEFT JOIN accounts a ON a.id = x.account_id
            ORDER BY x.occurred_at DESC
        """,
        "quotations": """
            SELECT q.*, a.name AS company_name
            FROM quotations q
            LEFT JOIN accounts a ON a.id = q.account_id
            ORDER BY q.quote_date DESC
        """,
        "sales_orders": """
            SELECT s.*, a.name AS company_name
            FROM sales_orders s
            LEFT JOIN accounts a ON a.id = s.account_id
            ORDER BY s.so_date DESC
        """
    }

    if table not in allowed:
        raise ValueError("Invalid table")

    return fetch_all(allowed[table])


def get_accounts():
    return fetch_all("""
        SELECT
            a.*,
            u.name AS owner_name
        FROM accounts a
        LEFT JOIN users u
            ON u.id = a.account_owner_id
        ORDER BY a.name COLLATE NOCASE
    """)


def get_account_details(account_id):
    account = fetch_one(
        "SELECT * FROM accounts WHERE id = ?",
        (account_id,)
    )

    if not account:
        return {}

    result = {"account": account}

    related_tables = {
        "contacts": ("contacts", "account_id"),
        "leads": ("leads", "account_id"),
        "opportunities": ("opportunities", "account_id"),
        "activities": ("activities", "account_id"),
        "quotations": ("quotations", "account_id"),
        "sales_orders": ("sales_orders", "account_id")
    }

    for key, (table, column) in related_tables.items():
        result[key] = fetch_all(
            f"SELECT * FROM {table} WHERE {column} = ?",
            (account_id,)
        )

    return result


# ---------------- API HANDLER ----------------

class CRMHandler(SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def send_json(self, data, status=200):
        response = json.dumps(data, default=str).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(response)

    def read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            params = parse_qs(parsed.query)

            if path == "/api/health":
                self.send_json({
                    "status": "running",
                    "database": DB_PATH.name,
                    "database_exists": DB_PATH.exists()
                })
                return

            if path == "/api/dashboard":
                data = {
                    "total_accounts": fetch_one(
                        "SELECT COUNT(*) AS n FROM accounts"
                    )["n"],
                    "total_contacts": fetch_one(
                        "SELECT COUNT(*) AS n FROM contacts"
                    )["n"],
                    "total_leads": fetch_one(
                        "SELECT COUNT(*) AS n FROM leads"
                    )["n"],
                    "total_opportunities": fetch_one(
                        "SELECT COUNT(*) AS n FROM opportunities"
                    )["n"],
                    "total_activities": fetch_one(
                        "SELECT COUNT(*) AS n FROM activities"
                    )["n"],
                    "total_quotations": fetch_one(
                        "SELECT COUNT(*) AS n FROM quotations"
                    )["n"],
                    "total_orders": fetch_one(
                        "SELECT COUNT(*) AS n FROM sales_orders"
                    )["n"],
                    "pipeline_value": fetch_one("""
                        SELECT COALESCE(SUM(value), 0) AS total
                        FROM opportunities WHERE is_active = 1
                    """)["total"]
                }
                self.send_json(data)
                return

            if path == "/api/accounts":
                self.send_json(get_accounts())
                return

            if path.startswith("/api/accounts/"):
                account_id = path.split("/")[-1]
                details = get_account_details(account_id)

                if not details:
                    self.send_json({"error": "Account not found"}, 404)
                    return

                self.send_json(details)
                return

            if path.startswith("/api/"):
                table = path.split("/")[-1]
                self.send_json(get_table_data(table))
                return

            if path == "/":
                self.path = "/index.html"

            super().do_GET()

        except Exception as error:
            print("GET ERROR:", error)
            self.send_json({"error": str(error)}, 500)

    def do_POST(self):
        try:
            path = urlparse(self.path).path

            if path == "/api/accounts":
                data = self.read_json()

                required = ["id", "name"]
                if any(not data.get(field) for field in required):
                    self.send_json({
                        "error": "Account ID and company name are required"
                    }, 400)
                    return

                with connect_db() as db:
                    db.execute("""
                        INSERT INTO accounts (
                            id, name, industry, company_phone, email,
                            website, address_line1, address_line2,
                            region, location, postal_code, additional_notes,
                            service, product, status, account_type,
                            annual_revenue
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        data.get("id"),
                        data.get("name"),
                        data.get("industry"),
                        data.get("company_phone"),
                        data.get("email"),
                        data.get("website"),
                        data.get("address_line1"),
                        data.get("address_line2"),
                        data.get("region"),
                        data.get("location"),
                        data.get("postal_code"),
                        data.get("additional_notes"),
                        data.get("service"),
                        data.get("product"),
                        data.get("status", "Active"),
                        data.get("account_type"),
                        data.get("annual_revenue")
                    ))

                self.send_json({"success": True}, 201)
                return

            if path.startswith("/api/accounts/"):
                account_id = path.split("/")[-1]
                data = self.read_json()

                editable = [
                    "name", "industry", "company_phone", "email",
                    "website", "address_line1", "address_line2",
                    "region", "location", "postal_code",
                    "additional_notes", "service", "product",
                    "status", "account_type", "annual_revenue"
                ]

                updates = [field for field in editable if field in data]

                if not updates:
                    self.send_json({"error": "No fields to update"}, 400)
                    return

                assignments = ", ".join(f"{field} = ?" for field in updates)
                values = [data[field] for field in updates]
                values.append(account_id)

                with connect_db() as db:
                    cursor = db.execute(
                        f"UPDATE accounts SET {assignments}, last_updated = CURRENT_TIMESTAMP WHERE id = ?",
                        values
                    )

                    if cursor.rowcount == 0:
                        self.send_json({"error": "Account not found"}, 404)
                        return

                self.send_json({"success": True})
                return

            self.send_json({"error": "Endpoint not found"}, 404)

        except sqlite3.IntegrityError as error:
            self.send_json({"error": str(error)}, 409)
        except Exception as error:
            print("POST ERROR:", error)
            self.send_json({"error": str(error)}, 500)

    def do_DELETE(self):
        try:
            path = urlparse(self.path).path

            if path.startswith("/api/accounts/"):
                account_id = path.split("/")[-1]

                with connect_db() as db:
                    cursor = db.execute(
                        "DELETE FROM accounts WHERE id = ?",
                        (account_id,)
                    )

                    if cursor.rowcount == 0:
                        self.send_json({"error": "Account not found"}, 404)
                        return

                self.send_json({"success": True})
                return

            self.send_json({"error": "Endpoint not found"}, 404)

        except Exception as error:
            self.send_json({"error": str(error)}, 500)


if __name__ == "__main__":

    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    if not (FRONTEND_DIR / "index.html").exists():
        raise FileNotFoundError("frontend/index.html not found")

    server = ThreadingHTTPServer((HOST, PORT), CRMHandler)

    print("ACCOUNT INTELLIGENCE CRM")
    print(f"Website: http://{HOST}:{PORT}")
    print(f"Database: {DB_PATH}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.server_close()
