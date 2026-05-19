from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from datetime import datetime, timedelta
from pathlib import Path
import json
import mimetypes
import sqlite3
import time
import uuid


ROOT = Path(__file__).parent
STATIC = ROOT / "static"
DB = ROOT / "restaurant.sqlite3"


def connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL DEFAULT 0,
                color TEXT NOT NULL DEFAULT '#2d6cdf',
                extra_data TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                phone TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                reminder_at TEXT,
                extra_data TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS udhari_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK(kind IN ('debit', 'credit')),
                amount REAL NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual',
                sale_id INTEGER,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                table_id INTEGER,
                customer_id INTEGER,
                payment_status TEXT NOT NULL CHECK(payment_status IN ('paid', 'udhari')),
                payment_method TEXT NOT NULL DEFAULT 'cash',
                subtotal REAL NOT NULL,
                total REAL NOT NULL,
                items TEXT NOT NULL,
                extra_data TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS stock_purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT NOT NULL,
                quantity REAL NOT NULL DEFAULT 0,
                unit TEXT NOT NULL DEFAULT '',
                total_cost REAL NOT NULL DEFAULT 0,
                supplier TEXT NOT NULL DEFAULT '',
                extra_data TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                opening_amount REAL NOT NULL DEFAULT 0,
                extra_data TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL CHECK(kind IN ('income', 'expense')),
                account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
                amount REAL NOT NULL,
                title TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                ref_id INTEGER,
                extra_data TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS restaurant_tables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                x REAL NOT NULL DEFAULT 80,
                y REAL NOT NULL DEFAULT 80,
                seats INTEGER NOT NULL DEFAULT 4,
                status TEXT NOT NULL DEFAULT 'empty',
                extra_data TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS custom_fields (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                area TEXT NOT NULL,
                name TEXT NOT NULL,
                field_type TEXT NOT NULL DEFAULT 'text',
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        existing = db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        if existing == 0:
            now = int(time.time())
            db.executemany(
                "INSERT INTO accounts(name, opening_amount, created_at) VALUES(?,?,?)",
                [("Cash", 0, now), ("Online", 0, now), ("Bank", 0, now)],
            )
        db.commit()


def now():
    return int(time.time())


def parse_body(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    if length == 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def row_to_dict(row):
    data = dict(row)
    for key in ("items", "extra_data"):
        if key in data:
            try:
                data[key] = json.loads(data[key] or "{}")
            except json.JSONDecodeError:
                data[key] = {} if key == "extra_data" else []
    return data


def rows(db, sql, args=()):
    return [row_to_dict(row) for row in db.execute(sql, args).fetchall()]


def ensure_customer(db, name, phone="", reminder_at=None, extra_data=None):
    if not reminder_at:
        reminder_at = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M")
    person = db.execute("SELECT * FROM customers WHERE lower(name)=lower(?)", (name,)).fetchone()
    if person:
        if reminder_at:
            db.execute("UPDATE customers SET reminder_at=? WHERE id=?", (reminder_at, person["id"]))
        return person["id"]
    cur = db.execute(
        "INSERT INTO customers(name, phone, reminder_at, extra_data, created_at) VALUES(?,?,?,?,?)",
        (name, phone, reminder_at, json.dumps(extra_data or {}), now()),
    )
    return cur.lastrowid


def account_id_for_method(db, method):
    row = db.execute("SELECT id FROM accounts WHERE lower(name)=lower(?)", (method,)).fetchone()
    if row:
        return row["id"]
    cur = db.execute(
        "INSERT INTO accounts(name, opening_amount, created_at) VALUES(?,?,?)",
        (method.title(), 0, now()),
    )
    return cur.lastrowid


def summary(db):
    accounts = rows(db, "SELECT * FROM accounts ORDER BY name")
    tx = rows(db, "SELECT * FROM transactions ORDER BY created_at DESC")
    customer_balances = rows(
        db,
        """
        SELECT c.*, COALESCE(SUM(CASE WHEN e.kind='debit' THEN e.amount ELSE -e.amount END), 0) AS balance
        FROM customers c
        LEFT JOIN udhari_entries e ON e.customer_id = c.id
        GROUP BY c.id
        ORDER BY balance DESC, c.name
        """,
    )
    income = sum(t["amount"] for t in tx if t["kind"] == "income")
    expense = sum(t["amount"] for t in tx if t["kind"] == "expense")
    opening = sum(a["opening_amount"] for a in accounts)
    account_totals = []
    for account in accounts:
        movement = sum(
            t["amount"] if t["kind"] == "income" else -t["amount"]
            for t in tx
            if t["account_id"] == account["id"]
        )
        account_totals.append({**account, "current_amount": account["opening_amount"] + movement})
    return {
        "income": income,
        "expense": expense,
        "net_profit": income - expense,
        "opening_total": opening,
        "current_total": opening + income - expense,
        "udhari_total": sum(max(0, c["balance"]) for c in customer_balances),
        "accounts": account_totals,
        "customers": customer_balances,
    }


class AppHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/state"):
            self.send_json(self.get_state())
            return
        path = self.path.split("?", 1)[0]
        if path == "/":
            path = "/index.html"
        file_path = (STATIC / path.lstrip("/")).resolve()
        if not str(file_path).startswith(str(STATIC.resolve())) or not file_path.exists():
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(file_path)[0] or "application/octet-stream")
        self.end_headers()
        self.wfile.write(file_path.read_bytes())

    def do_POST(self):
        try:
            data = parse_body(self)
            route = self.path.split("?", 1)[0]
            with connect() as db:
                if route == "/api/products":
                    result = self.create_product(db, data)
                elif route == "/api/products/update":
                    result = self.update_product(db, data)
                elif route == "/api/products/delete":
                    result = self.delete_product(db, data)
                elif route == "/api/products/reorder":
                    result = self.reorder_products(db, data)
                elif route == "/api/settings":
                    result = self.update_setting(db, data)
                elif route == "/api/sales":
                    result = self.create_sale(db, data)
                elif route == "/api/customers":
                    result = self.create_customer(db, data)
                elif route == "/api/udhari/payment":
                    result = self.create_udhari_payment(db, data)
                elif route == "/api/stock":
                    result = self.create_stock(db, data)
                elif route == "/api/accounts":
                    result = self.create_account(db, data)
                elif route == "/api/transactions":
                    result = self.create_transaction(db, data)
                elif route == "/api/tables":
                    result = self.create_table(db, data)
                elif route == "/api/tables/move":
                    result = self.move_table(db, data)
                elif route == "/api/tables/update":
                    result = self.update_table(db, data)
                elif route == "/api/custom-fields":
                    result = self.create_custom_field(db, data)
                else:
                    self.send_error(404)
                    return
                db.commit()
            self.send_json(result)
        except Exception as exc:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(exc)}).encode("utf-8"))

    def create_product(self, db, data):
        cur = db.execute(
            "INSERT INTO products(name, price, color, extra_data, created_at) VALUES(?,?,?,?,?)",
            (
                data.get("name", "Item").strip(),
                float(data.get("price") or 0),
                data.get("color") or "#2d6cdf",
                json.dumps(data.get("extra_data") or {}),
                now(),
            ),
        )
        return {"id": cur.lastrowid, "state": self.get_state(db)}

    def update_product(self, db, data):
        db.execute(
            "UPDATE products SET name=?, price=?, color=?, extra_data=? WHERE id=?",
            (
                data.get("name", "Item").strip(),
                float(data.get("price") or 0),
                data.get("color") or "#176b87",
                json.dumps(data.get("extra_data") or {}),
                int(data["id"]),
            ),
        )
        return {"state": self.get_state(db)}

    def delete_product(self, db, data):
        db.execute("DELETE FROM products WHERE id=?", (int(data["id"]),))
        return {"state": self.get_state(db)}

    def reorder_products(self, db, data):
        ids = data.get("ids", [])
        base_time = now()
        for idx, pid in enumerate(ids):
            db.execute("UPDATE products SET created_at=? WHERE id=?", (base_time - idx, int(pid)))
        return {"state": self.get_state(db)}

    def create_customer(self, db, data):
        customer_id = ensure_customer(
            db,
            data.get("name", "Customer").strip(),
            data.get("phone", ""),
            data.get("reminder_at"),
            data.get("extra_data"),
        )
        amount = float(data.get("amount") or 0)
        if amount:
            db.execute(
                "INSERT INTO udhari_entries(customer_id, kind, amount, note, source, created_at) VALUES(?,?,?,?,?,?)",
                (customer_id, "debit", amount, data.get("note", "Opening udhari"), "manual", now()),
            )
        return {"id": customer_id, "state": self.get_state(db)}

    def create_sale(self, db, data):
        items = data.get("items") or []
        total = float(data.get("total") or sum(float(i.get("price", 0)) * float(i.get("qty", 1)) for i in items))
        customer_id = data.get("customer_id")
        if data.get("payment_status") == "udhari":
            customer_name = data.get("customer_name") or "Walk-in Customer"
            customer_id = ensure_customer(db, customer_name, reminder_at=data.get("reminder_at"))
        cur = db.execute(
            """
            INSERT INTO sales(source, table_id, customer_id, payment_status, payment_method, subtotal, total, items, extra_data, created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                data.get("source", "calculator"),
                data.get("table_id"),
                customer_id,
                data.get("payment_status", "paid"),
                data.get("payment_method", "cash"),
                total,
                total,
                json.dumps(items),
                json.dumps(data.get("extra_data") or {}),
                now(),
            ),
        )
        sale_id = cur.lastrowid
        if data.get("payment_status") == "udhari":
            db.execute(
                "INSERT INTO udhari_entries(customer_id, kind, amount, note, source, sale_id, created_at) VALUES(?,?,?,?,?,?,?)",
                (customer_id, "debit", total, "Bill marked as udhari", data.get("source", "calculator"), sale_id, now()),
            )
        else:
            account_id = account_id_for_method(db, data.get("payment_method", "cash"))
            db.execute(
                "INSERT INTO transactions(kind, account_id, amount, title, source, ref_id, created_at) VALUES(?,?,?,?,?,?,?)",
                ("income", account_id, total, "Paid sale", data.get("source", "calculator"), sale_id, now()),
            )
        if data.get("table_id"):
            db.execute("UPDATE restaurant_tables SET status='empty' WHERE id=?", (data.get("table_id"),))
        return {"id": sale_id, "state": self.get_state(db)}

    def create_udhari_payment(self, db, data):
        amount = float(data.get("amount") or 0)
        customer_id = int(data["customer_id"])
        db.execute(
            "INSERT INTO udhari_entries(customer_id, kind, amount, note, source, created_at) VALUES(?,?,?,?,?,?)",
            (customer_id, "credit", amount, data.get("note", "Payment received"), "payment", now()),
        )
        account_id = account_id_for_method(db, data.get("payment_method", "cash"))
        db.execute(
            "INSERT INTO transactions(kind, account_id, amount, title, source, ref_id, created_at) VALUES(?,?,?,?,?,?,?)",
            ("income", account_id, amount, "Udhari payment", "udhari", customer_id, now()),
        )
        return {"state": self.get_state(db)}

    def create_stock(self, db, data):
        total = float(data.get("total_cost") or 0)
        cur = db.execute(
            "INSERT INTO stock_purchases(item_name, quantity, unit, total_cost, supplier, extra_data, created_at) VALUES(?,?,?,?,?,?,?)",
            (
                data.get("item_name", "Stock item").strip(),
                float(data.get("quantity") or 0),
                data.get("unit", ""),
                total,
                data.get("supplier", ""),
                json.dumps(data.get("extra_data") or {}),
                now(),
            ),
        )
        account_id = account_id_for_method(db, data.get("payment_method", "cash"))
        db.execute(
            "INSERT INTO transactions(kind, account_id, amount, title, source, ref_id, created_at) VALUES(?,?,?,?,?,?,?)",
            ("expense", account_id, total, "Stock purchase", "stock", cur.lastrowid, now()),
        )
        return {"id": cur.lastrowid, "state": self.get_state(db)}

    def create_account(self, db, data):
        cur = db.execute(
            "INSERT INTO accounts(name, opening_amount, extra_data, created_at) VALUES(?,?,?,?)",
            (data.get("name", "Account").strip(), float(data.get("opening_amount") or 0), json.dumps(data.get("extra_data") or {}), now()),
        )
        return {"id": cur.lastrowid, "state": self.get_state(db)}

    def create_transaction(self, db, data):
        cur = db.execute(
            "INSERT INTO transactions(kind, account_id, amount, title, source, extra_data, created_at) VALUES(?,?,?,?,?,?,?)",
            (
                data.get("kind", "income"),
                data.get("account_id"),
                float(data.get("amount") or 0),
                data.get("title", "Manual entry"),
                "manual",
                json.dumps(data.get("extra_data") or {}),
                now(),
            ),
        )
        return {"id": cur.lastrowid, "state": self.get_state(db)}

    def create_table(self, db, data):
        cur = db.execute(
            "INSERT INTO restaurant_tables(label, x, y, seats, status, extra_data, created_at) VALUES(?,?,?,?,?,?,?)",
            (
                data.get("label") or f"T-{uuid.uuid4().hex[:3].upper()}",
                float(data.get("x") or 80),
                float(data.get("y") or 80),
                int(data.get("seats") or 4),
                data.get("status", "empty"),
                json.dumps(data.get("extra_data") or {}),
                now(),
            ),
        )
        return {"id": cur.lastrowid, "state": self.get_state(db)}

    def move_table(self, db, data):
        db.execute("UPDATE restaurant_tables SET x=?, y=?, status=? WHERE id=?", (data["x"], data["y"], data.get("status", "empty"), data["id"]))
        return {"state": self.get_state(db)}

    def update_table(self, db, data):
        db.execute(
            "UPDATE restaurant_tables SET label=?, seats=?, x=?, y=?, status=?, extra_data=? WHERE id=?",
            (
                data.get("label", "Table").strip(),
                int(data.get("seats") or 4),
                float(data.get("x") or 80),
                float(data.get("y") or 80),
                data.get("status", "empty"),
                json.dumps(data.get("extra_data") or {}),
                int(data["id"]),
            ),
        )
        return {"state": self.get_state(db)}

    def create_custom_field(self, db, data):
        cur = db.execute(
            "INSERT INTO custom_fields(area, name, field_type, created_at) VALUES(?,?,?,?)",
            (data.get("area", "general"), data.get("name", "Field"), data.get("field_type", "text"), now()),
        )
        return {"id": cur.lastrowid, "state": self.get_state(db)}

    def update_setting(self, db, data):
        db.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (data.get("key", "store_name"), data.get("value", "")),
        )
        return {"state": self.get_state(db)}

    def get_state(self, db=None):
        close = False
        if db is None:
            db = connect()
            close = True
        state = {
            "products": rows(db, "SELECT * FROM products ORDER BY created_at DESC"),
            "sales": rows(db, "SELECT * FROM sales ORDER BY created_at DESC LIMIT 100"),
            "stock": rows(db, "SELECT * FROM stock_purchases ORDER BY created_at DESC LIMIT 100"),
            "tables": rows(db, "SELECT * FROM restaurant_tables ORDER BY id"),
            "transactions": rows(db, "SELECT * FROM transactions ORDER BY created_at DESC LIMIT 150"),
            "custom_fields": rows(db, "SELECT * FROM custom_fields ORDER BY area, created_at"),
            "settings": {row["key"]: row["value"] for row in db.execute("SELECT key, value FROM settings").fetchall()},
            "summary": summary(db),
        }
        if close:
            db.close()
        return state

    def send_json(self, data):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", 8000), AppHandler)
    print("Restaurant app running at http://127.0.0.1:8000")
    server.serve_forever()
