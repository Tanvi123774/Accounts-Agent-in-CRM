import sqlite3

conn = sqlite3.connect("account_agent.db")
conn.row_factory = sqlite3.Row

tables = ["accounts", "leads", "contacts", "opportunities", "activities"]

for table in tables:
    print("\n" + "=" * 60)
    print("TABLE:", table)
    print("=" * 60)

    columns = conn.execute(
        "PRAGMA table_info(" + table + ")"
    ).fetchall()

    for col in columns:
        print(
            col["name"],
            "| TYPE:", col["type"],
            "| REQUIRED:", col["notnull"],
            "| DEFAULT:", col["dflt_value"],
            "| PRIMARY KEY:", col["pk"]
        )

    foreign_keys = conn.execute(
        "PRAGMA foreign_key_list(" + table + ")"
    ).fetchall()

    for fk in foreign_keys:
        print(
            "FOREIGN KEY:",
            fk["from"],
            "->",
            fk["table"] + "." + fk["to"]
        )

conn.close()
