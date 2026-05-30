import json, os, time, uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote, urlunparse

import pg8000.dbapi as pg
from flask import Flask, g, jsonify, redirect, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from dotenv import load_dotenv
    dotenv_path = Path(__file__).parent.parent / ".env.local"
    if not load_dotenv(dotenv_path):
        load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

DATABASE_URL = os.environ.get("DATABASE_URL", "")
STATIC = Path(__file__).parent.parent / "static"
ADMIN_USER = "Jaypal"
ADMIN_PASS = "Jaypal"
STATIC_EXTS = {".js", ".css", ".ico", ".png", ".jpg", ".svg", ".woff", ".woff2", ".ttf", ".map"}


def parse_db_url(url):
    """Parse a postgres:// URL into pg8000.connect() kwargs."""
    p = urlparse(url)
    qs = parse_qs(p.query)
    ssl_mode = qs.get("sslmode", ["require"])[0]
    import ssl
    ssl_ctx = ssl.create_default_context() if ssl_mode != "disable" else None
    if ssl_ctx:
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
    kwargs = {
        "host":     p.hostname,
        "port":     p.port or 5432,
        "database": (p.path or "/postgres").lstrip("/") or "postgres",
        "user":     unquote(p.username or ""),
        "password": unquote(p.password or ""),
    }
    if ssl_ctx:
        kwargs["ssl_context"] = ssl_ctx
    return kwargs


DB_KWARGS = parse_db_url(DATABASE_URL) if DATABASE_URL else {}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)


# ── DB ────────────────────────────────────────────────────────────────────────

def _dict_row(cursor, row):
    """pg8000 row factory: convert tuple rows to dicts using column names."""
    if cursor.description is None or row is None:
        return row
    return {desc[0]: val for desc, val in zip(cursor.description, row)}


def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured. Set it in Vercel → Settings → Environment Variables.")
    if "db" not in g:
        conn = pg.connect(**DB_KWARGS)
        conn.autocommit = False
        g.db = conn
    return g.db


def sanitize_db_url(url):
    if not url:
        return ""
    p = urlparse(url)
    auth = ""
    if p.username:
        auth = p.username
        if p.password:
            auth += ":*****"
        auth += "@"
    netloc = f"{auth}{p.hostname or ''}{f':{p.port}' if p.port else ''}"
    return urlunparse((p.scheme, netloc, p.path or "", p.params or "", p.query or "", p.fragment or ""))


def get_db_status():
    if not DATABASE_URL:
        return {"configured": False, "status": "DATABASE_URL is not configured.", "url": ""}
    try:
        conn = pg.connect(**DB_KWARGS)
        conn.close()
        return {"configured": True, "status": "connected", "url": sanitize_db_url(DATABASE_URL)}
    except Exception as exc:
        return {"configured": True, "status": f"connection failed: {exc}", "url": sanitize_db_url(DATABASE_URL)}


def print_db_status():
    info = get_db_status()
    print(f"[DB] status={info['status']} url={info['url'] or '<none>'}")


def cursor_of(conn):
    """Return a cursor whose fetchone/fetchall return dicts."""
    c = conn.cursor()
    _orig_fetchone = c.fetchone
    _orig_fetchall = c.fetchall

    def fetchone():
        row = _orig_fetchone()
        return _dict_row(c, row) if row is not None else None

    def fetchall():
        return [_dict_row(c, row) for row in _orig_fetchall()]

    c.fetchone = fetchone
    c.fetchall = fetchall
    return c

@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def now():
    return int(time.time())

def init_db():
    conn = pg.connect(**DB_KWARGS)
    conn.autocommit = False
    try:
        with conn.cursor() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','revoked')),
                created_at BIGINT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY, name TEXT NOT NULL, price REAL NOT NULL DEFAULT 0,
                color TEXT NOT NULL DEFAULT '#2d6cdf', extra_data TEXT NOT NULL DEFAULT '{}',
                created_at BIGINT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS customers (
                id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, phone TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '', reminder_at TEXT,
                extra_data TEXT NOT NULL DEFAULT '{}', created_at BIGINT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS udhari_entries (
                id SERIAL PRIMARY KEY,
                customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK(kind IN ('debit','credit')), amount REAL NOT NULL,
                note TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'manual',
                sale_id INTEGER, created_at BIGINT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS sales (
                id SERIAL PRIMARY KEY, source TEXT NOT NULL, table_id INTEGER, customer_id INTEGER,
                payment_status TEXT NOT NULL CHECK(payment_status IN ('paid','udhari')),
                payment_method TEXT NOT NULL DEFAULT 'cash', subtotal REAL NOT NULL, total REAL NOT NULL,
                items TEXT NOT NULL, extra_data TEXT NOT NULL DEFAULT '{}', created_at BIGINT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS stock_purchases (
                id SERIAL PRIMARY KEY, item_name TEXT NOT NULL, quantity REAL NOT NULL DEFAULT 0,
                unit TEXT NOT NULL DEFAULT '', total_cost REAL NOT NULL DEFAULT 0,
                supplier TEXT NOT NULL DEFAULT '', extra_data TEXT NOT NULL DEFAULT '{}',
                created_at BIGINT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS accounts (
                id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                opening_amount REAL NOT NULL DEFAULT 0, extra_data TEXT NOT NULL DEFAULT '{}',
                created_at BIGINT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('income','expense')),
                account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL, amount REAL NOT NULL,
                title TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'manual', ref_id INTEGER,
                extra_data TEXT NOT NULL DEFAULT '{}', created_at BIGINT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS restaurant_tables (
                id SERIAL PRIMARY KEY, label TEXT NOT NULL, x REAL NOT NULL DEFAULT 80,
                y REAL NOT NULL DEFAULT 80, seats INTEGER NOT NULL DEFAULT 4,
                status TEXT NOT NULL DEFAULT 'empty', extra_data TEXT NOT NULL DEFAULT '{}',
                created_at BIGINT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS custom_fields (
                id SERIAL PRIMARY KEY, area TEXT NOT NULL, name TEXT NOT NULL,
                field_type TEXT NOT NULL DEFAULT 'text', created_at BIGINT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
            c.execute("SELECT COUNT(*) AS cnt FROM accounts")
            row = c.fetchone()
            cnt = row[0] if isinstance(row, (list, tuple)) else row["cnt"]
            if cnt == 0:
                ts = now()
                c.execute(
                    "INSERT INTO accounts(name,opening_amount,created_at) VALUES(%s,%s,%s),(%s,%s,%s),(%s,%s,%s)",
                    ("Cash", 0, ts, "Online", 0, ts, "Bank", 0, ts))
        conn.commit()
    finally:
        conn.close()


# ── Auth guard ────────────────────────────────────────────────────────────────

@app.before_request
def require_auth():
    path = request.path
    if os.path.splitext(path)[1].lower() in STATIC_EXTS:
        return None
    if path.startswith("/api/auth/"):
        return None
    if path in ("/login", "/waiting"):
        return None
    if path.startswith("/admin") or path.startswith("/api/admin"):
        if session.get("role") != "admin":
            return (jsonify({"error": "forbidden"}), 403) if path.startswith("/api/") else redirect("/login")
        return None
    if session.get("role") == "admin":
        return None
    if "user_id" not in session:
        return (jsonify({"error": "unauthorized"}), 401) if path.startswith("/api/") else redirect("/login")
    if session.get("status") != "approved":
        return (jsonify({"error": "pending"}), 403) if path.startswith("/api/") else redirect("/waiting")


# ── Query helpers ─────────────────────────────────────────────────────────────

def query_rows(c, sql, args=()):
    c.execute(sql, args)
    result = []
    for row in c.fetchall():
        data = dict(row)
        for key in ("items", "extra_data"):
            if key in data:
                try:
                    data[key] = json.loads(data[key] or "{}")
                except (json.JSONDecodeError, TypeError):
                    data[key] = {} if key == "extra_data" else []
        result.append(data)
    return result

def ensure_customer(c, name, phone="", reminder_at=None, extra_data=None):
    if not reminder_at:
        reminder_at = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M")
    c.execute("SELECT * FROM customers WHERE lower(name)=lower(%s)", (name,))
    person = c.fetchone()
    if person:
        c.execute("UPDATE customers SET reminder_at=%s WHERE id=%s", (reminder_at, person["id"]))
        return person["id"]
    c.execute(
        "INSERT INTO customers(name,phone,reminder_at,extra_data,created_at) VALUES(%s,%s,%s,%s,%s) RETURNING id",
        (name, phone, reminder_at, json.dumps(extra_data or {}), now()))
    return c.fetchone()["id"]

def account_id_for_method(c, method):
    c.execute("SELECT id FROM accounts WHERE lower(name)=lower(%s)", (method,))
    row = c.fetchone()
    if row:
        return row["id"]
    c.execute("INSERT INTO accounts(name,opening_amount,created_at) VALUES(%s,%s,%s) RETURNING id",
              (method.title(), 0, now()))
    return c.fetchone()["id"]

def build_summary(c):
    accounts = query_rows(c, "SELECT * FROM accounts ORDER BY name")
    tx = query_rows(c, "SELECT * FROM transactions ORDER BY created_at DESC")
    customer_balances = query_rows(c, """
        SELECT c.*, COALESCE(SUM(CASE WHEN e.kind='debit' THEN e.amount ELSE -e.amount END),0) AS balance
        FROM customers c LEFT JOIN udhari_entries e ON e.customer_id=c.id
        GROUP BY c.id ORDER BY balance DESC, c.name""")
    income = sum(t["amount"] for t in tx if t["kind"] == "income")
    expense = sum(t["amount"] for t in tx if t["kind"] == "expense")
    opening = sum(a["opening_amount"] for a in accounts)
    account_totals = []
    for account in accounts:
        movement = sum(t["amount"] if t["kind"] == "income" else -t["amount"]
                       for t in tx if t["account_id"] == account["id"])
        account_totals.append({**account, "current_amount": account["opening_amount"] + movement})
    return {"income": income, "expense": expense, "net_profit": income - expense,
            "opening_total": opening, "current_total": opening + income - expense,
            "udhari_total": sum(max(0, cu["balance"]) for cu in customer_balances),
            "accounts": account_totals, "customers": customer_balances}

def build_state(c):
    return {
        "products": query_rows(c, "SELECT * FROM products ORDER BY created_at DESC"),
        "sales": query_rows(c, "SELECT * FROM sales ORDER BY created_at DESC LIMIT 100"),
        "stock": query_rows(c, "SELECT * FROM stock_purchases ORDER BY created_at DESC LIMIT 100"),
        "tables": query_rows(c, "SELECT * FROM restaurant_tables ORDER BY id"),
        "transactions": query_rows(c, "SELECT * FROM transactions ORDER BY created_at DESC LIMIT 150"),
        "custom_fields": query_rows(c, "SELECT * FROM custom_fields ORDER BY area, created_at"),
        "settings": {r["key"]: r["value"] for r in query_rows(c, "SELECT key,value FROM settings")},
        "summary": build_summary(c)}


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route("/login")
def login_page():
    if session.get("role") == "admin":
        return redirect("/admin")
    if session.get("status") == "approved":
        return redirect("/")
    return send_from_directory(str(STATIC), "login.html")

@app.route("/waiting")
def waiting_page():
    return send_from_directory(str(STATIC), "waiting.html")

@app.route("/admin")
def admin_page():
    return send_from_directory(str(STATIC), "admin.html")

@app.route("/api/auth/signup", methods=["POST"])
def signup():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    db = get_db()
    with cursor_of(db) as c:
        c.execute("SELECT id FROM users WHERE email=%s", (email,))
        if c.fetchone():
            return jsonify({"error": "Email already registered"}), 400
        c.execute(
            "INSERT INTO users(email,password_hash,status,created_at) VALUES(%s,%s,%s,%s) RETURNING id",
            (email, generate_password_hash(password), "pending", now()))
        user_id = c.fetchone()["id"]
    db.commit()
    session.permanent = True
    session["user_id"] = user_id
    session["email"] = email
    session["status"] = "pending"
    return jsonify({"status": "pending"})

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    if email == ADMIN_USER and password == ADMIN_PASS:
        session.permanent = True
        session["role"] = "admin"
        session["email"] = ADMIN_USER
        return jsonify({"role": "admin", "redirect": "/admin"})
    db = get_db()
    with cursor_of(db) as c:
        c.execute("SELECT * FROM users WHERE lower(email)=lower(%s)", (email,))
        user = c.fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid email or password"}), 401
    if user["status"] == "revoked":
        return jsonify({"error": "Access revoked. Contact admin."}), 403
    session.permanent = True
    session["user_id"] = user["id"]
    session["email"] = user["email"]
    session["status"] = user["status"]
    redirect_to = "/" if user["status"] == "approved" else "/waiting"
    return jsonify({"status": user["status"], "redirect": redirect_to})

@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/auth/status")
def auth_status():
    if "user_id" not in session:
        return jsonify({"status": "not_logged_in"}), 401
    db = get_db()
    with cursor_of(db) as c:
        c.execute("SELECT status FROM users WHERE id=%s", (session["user_id"],))
        user = c.fetchone()
    if not user:
        session.clear()
        return jsonify({"status": "not_found"}), 404
    session["status"] = user["status"]
    return jsonify({"status": user["status"], "email": session.get("email")})

@app.route("/api/auth/me")
def auth_me():
    if session.get("role") == "admin":
        return jsonify({"role": "admin", "email": session.get("email")})
    return jsonify({"user_id": session.get("user_id"), "email": session.get("email"),
                    "status": session.get("status")})


@app.route("/api/db-status")
def api_db_status():
    return jsonify(get_db_status())


# ── Admin routes ──────────────────────────────────────────────────────────────

@app.route("/api/admin/users")
def admin_list_users():
    db = get_db()
    with cursor_of(db) as c:
        users = query_rows(c, "SELECT id,email,status,created_at FROM users ORDER BY created_at DESC")
    return jsonify({"users": users})

@app.route("/api/admin/users/approve", methods=["POST"])
def admin_approve():
    data = request.get_json() or {}
    db = get_db()
    with cursor_of(db) as c:
        c.execute("UPDATE users SET status='approved' WHERE id=%s", (int(data["id"]),))
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/admin/users/revoke", methods=["POST"])
def admin_revoke():
    data = request.get_json() or {}
    db = get_db()
    with cursor_of(db) as c:
        c.execute("UPDATE users SET status='revoked' WHERE id=%s", (int(data["id"]),))
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/admin/users/delete", methods=["POST"])
def admin_delete():
    data = request.get_json() or {}
    db = get_db()
    with cursor_of(db) as c:
        c.execute("DELETE FROM users WHERE id=%s", (int(data["id"]),))
    db.commit()
    return jsonify({"ok": True})


# ── Static files ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(str(STATIC), "index.html")

@app.route("/<path:filename>")
def static_files(filename):
    file_path = (STATIC / filename).resolve()
    if not str(file_path).startswith(str(STATIC.resolve())) or not file_path.exists():
        return jsonify({"error": "not found"}), 404
    return send_from_directory(str(STATIC), filename)


# ── App routes ────────────────────────────────────────────────────────────────

@app.route("/api/state")
def get_state():
    db = get_db()
    with cursor_of(db) as c:
        state = build_state(c)
    return jsonify(state)

@app.route("/api/products", methods=["POST"])
def create_product():
    data = request.get_json() or {}
    db = get_db()
    with cursor_of(db) as c:
        c.execute("INSERT INTO products(name,price,color,extra_data,created_at) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                  (data.get("name","Item").strip(), float(data.get("price") or 0),
                   data.get("color") or "#2d6cdf", json.dumps(data.get("extra_data") or {}), now()))
        new_id = c.fetchone()["id"]
        state = build_state(c)
    db.commit()
    return jsonify({"id": new_id, "state": state})

@app.route("/api/products/update", methods=["POST"])
def update_product():
    data = request.get_json() or {}
    db = get_db()
    with cursor_of(db) as c:
        c.execute("UPDATE products SET name=%s,price=%s,color=%s,extra_data=%s WHERE id=%s",
                  (data.get("name","Item").strip(), float(data.get("price") or 0),
                   data.get("color") or "#176b87", json.dumps(data.get("extra_data") or {}), int(data["id"])))
        state = build_state(c)
    db.commit()
    return jsonify({"state": state})

@app.route("/api/products/delete", methods=["POST"])
def delete_product():
    data = request.get_json() or {}
    db = get_db()
    with cursor_of(db) as c:
        c.execute("DELETE FROM products WHERE id=%s", (int(data["id"]),))
        state = build_state(c)
    db.commit()
    return jsonify({"state": state})

@app.route("/api/products/reorder", methods=["POST"])
def reorder_products():
    data = request.get_json() or {}
    base_time = now()
    db = get_db()
    with cursor_of(db) as c:
        for idx, pid in enumerate(data.get("ids", [])):
            c.execute("UPDATE products SET created_at=%s WHERE id=%s", (base_time - idx, int(pid)))
        state = build_state(c)
    db.commit()
    return jsonify({"state": state})

@app.route("/api/settings", methods=["POST"])
def update_setting():
    data = request.get_json() or {}
    db = get_db()
    with cursor_of(db) as c:
        c.execute("INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                  (data.get("key","store_name"), data.get("value","")))
        state = build_state(c)
    db.commit()
    return jsonify({"state": state})

@app.route("/api/sales", methods=["POST"])
def create_sale():
    data = request.get_json() or {}
    items = data.get("items") or []
    total = float(data.get("total") or sum(float(i.get("price",0)) * float(i.get("qty",1)) for i in items))
    db = get_db()
    with cursor_of(db) as c:
        customer_id = data.get("customer_id")
        if data.get("payment_status") == "udhari":
            customer_id = ensure_customer(c, data.get("customer_name") or "Walk-in Customer",
                                          reminder_at=data.get("reminder_at"))
        c.execute("""INSERT INTO sales(source,table_id,customer_id,payment_status,payment_method,
                     subtotal,total,items,extra_data,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                  (data.get("source","calculator"), data.get("table_id"), customer_id,
                   data.get("payment_status","paid"), data.get("payment_method","cash"),
                   total, total, json.dumps(items), json.dumps(data.get("extra_data") or {}), now()))
        sale_id = c.fetchone()["id"]
        if data.get("payment_status") == "udhari":
            c.execute("INSERT INTO udhari_entries(customer_id,kind,amount,note,source,sale_id,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                      (customer_id,"debit",total,"Bill marked as udhari",data.get("source","calculator"),sale_id,now()))
        else:
            aid = account_id_for_method(c, data.get("payment_method","cash"))
            c.execute("INSERT INTO transactions(kind,account_id,amount,title,source,ref_id,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                      ("income",aid,total,"Paid sale",data.get("source","calculator"),sale_id,now()))
        if data.get("table_id"):
            c.execute("UPDATE restaurant_tables SET status='empty' WHERE id=%s", (data["table_id"],))
        state = build_state(c)
    db.commit()
    return jsonify({"id": sale_id, "state": state})

@app.route("/api/customers", methods=["POST"])
def create_customer():
    data = request.get_json() or {}
    db = get_db()
    with cursor_of(db) as c:
        cid = ensure_customer(c, data.get("name","Customer").strip(),
                              data.get("phone",""), data.get("reminder_at"), data.get("extra_data"))
        amount = float(data.get("amount") or 0)
        if amount:
            c.execute("INSERT INTO udhari_entries(customer_id,kind,amount,note,source,created_at) VALUES(%s,%s,%s,%s,%s,%s)",
                      (cid,"debit",amount,data.get("note","Opening udhari"),"manual",now()))
        state = build_state(c)
    db.commit()
    return jsonify({"id": cid, "state": state})

@app.route("/api/udhari/payment", methods=["POST"])
def create_udhari_payment():
    data = request.get_json() or {}
    amount = float(data.get("amount") or 0)
    cid = int(data["customer_id"])
    db = get_db()
    with cursor_of(db) as c:
        c.execute("INSERT INTO udhari_entries(customer_id,kind,amount,note,source,created_at) VALUES(%s,%s,%s,%s,%s,%s)",
                  (cid,"credit",amount,data.get("note","Payment received"),"payment",now()))
        aid = account_id_for_method(c, data.get("payment_method","cash"))
        c.execute("INSERT INTO transactions(kind,account_id,amount,title,source,ref_id,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                  ("income",aid,amount,"Udhari payment","udhari",cid,now()))
        state = build_state(c)
    db.commit()
    return jsonify({"state": state})

@app.route("/api/stock", methods=["POST"])
def create_stock():
    data = request.get_json() or {}
    total = float(data.get("total_cost") or 0)
    db = get_db()
    with cursor_of(db) as c:
        c.execute("INSERT INTO stock_purchases(item_name,quantity,unit,total_cost,supplier,extra_data,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                  (data.get("item_name","Stock item").strip(), float(data.get("quantity") or 0),
                   data.get("unit",""), total, data.get("supplier",""),
                   json.dumps(data.get("extra_data") or {}), now()))
        sid = c.fetchone()["id"]
        aid = account_id_for_method(c, data.get("payment_method","cash"))
        c.execute("INSERT INTO transactions(kind,account_id,amount,title,source,ref_id,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                  ("expense",aid,total,"Stock purchase","stock",sid,now()))
        state = build_state(c)
    db.commit()
    return jsonify({"id": sid, "state": state})

@app.route("/api/accounts", methods=["POST"])
def create_account():
    data = request.get_json() or {}
    db = get_db()
    with cursor_of(db) as c:
        c.execute("INSERT INTO accounts(name,opening_amount,extra_data,created_at) VALUES(%s,%s,%s,%s) RETURNING id",
                  (data.get("name","Account").strip(), float(data.get("opening_amount") or 0),
                   json.dumps(data.get("extra_data") or {}), now()))
        new_id = c.fetchone()["id"]
        state = build_state(c)
    db.commit()
    return jsonify({"id": new_id, "state": state})

@app.route("/api/transactions", methods=["POST"])
def create_transaction():
    data = request.get_json() or {}
    db = get_db()
    with cursor_of(db) as c:
        c.execute("INSERT INTO transactions(kind,account_id,amount,title,source,extra_data,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                  (data.get("kind","income"), data.get("account_id"),
                   float(data.get("amount") or 0), data.get("title","Manual entry"),
                   "manual", json.dumps(data.get("extra_data") or {}), now()))
        new_id = c.fetchone()["id"]
        state = build_state(c)
    db.commit()
    return jsonify({"id": new_id, "state": state})

@app.route("/api/tables", methods=["POST"])
def create_table():
    data = request.get_json() or {}
    db = get_db()
    with cursor_of(db) as c:
        c.execute("INSERT INTO restaurant_tables(label,x,y,seats,status,extra_data,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                  (data.get("label") or f"T-{uuid.uuid4().hex[:3].upper()}",
                   float(data.get("x") or 80), float(data.get("y") or 80),
                   int(data.get("seats") or 4), data.get("status","empty"),
                   json.dumps(data.get("extra_data") or {}), now()))
        new_id = c.fetchone()["id"]
        state = build_state(c)
    db.commit()
    return jsonify({"id": new_id, "state": state})

@app.route("/api/tables/move", methods=["POST"])
def move_table():
    data = request.get_json() or {}
    db = get_db()
    with cursor_of(db) as c:
        c.execute("UPDATE restaurant_tables SET x=%s,y=%s,status=%s WHERE id=%s",
                  (data["x"], data["y"], data.get("status","empty"), data["id"]))
        state = build_state(c)
    db.commit()
    return jsonify({"state": state})

@app.route("/api/tables/update", methods=["POST"])
def update_table():
    data = request.get_json() or {}
    db = get_db()
    with cursor_of(db) as c:
        c.execute("UPDATE restaurant_tables SET label=%s,seats=%s,x=%s,y=%s,status=%s,extra_data=%s WHERE id=%s",
                  (data.get("label","Table").strip(), int(data.get("seats") or 4),
                   float(data.get("x") or 80), float(data.get("y") or 80),
                   data.get("status","empty"), json.dumps(data.get("extra_data") or {}), int(data["id"])))
        state = build_state(c)
    db.commit()
    return jsonify({"state": state})

@app.route("/api/custom-fields", methods=["POST"])
def create_custom_field():
    data = request.get_json() or {}
    db = get_db()
    with cursor_of(db) as c:
        c.execute("INSERT INTO custom_fields(area,name,field_type,created_at) VALUES(%s,%s,%s,%s) RETURNING id",
                  (data.get("area","general"), data.get("name","Field"),
                   data.get("field_type","text"), now()))
        new_id = c.fetchone()["id"]
        state = build_state(c)
    db.commit()
    return jsonify({"id": new_id, "state": state})

@app.errorhandler(Exception)
def handle_error(exc):
    import traceback
    # Distinguish client errors (400) from unexpected server errors (500)
    client_errors = (ValueError, KeyError, TypeError)
    status = 400 if isinstance(exc, client_errors) else 500
    print(f"[ERROR {status}] {type(exc).__name__}: {exc}")
    if status == 500:
        traceback.print_exc()
    return jsonify({"error": str(exc), "type": type(exc).__name__}), status

if DATABASE_URL:
    try:
        init_db()
    except Exception as _e:
        print(f"[WARN] init_db() failed (will retry on first request): {_e}")
    finally:
        print_db_status()
else:
    print_db_status()

if __name__ == "__main__":
    app.run(debug=True, port=8000)
