import json, os, time, uuid
from datetime import datetime, timedelta
from pathlib import Path

from supabase import create_client, Client
from flask import Flask, g, jsonify, redirect, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from dotenv import load_dotenv
    dotenv_path = Path(__file__).parent.parent / ".env.local"
    if not load_dotenv(dotenv_path):
        load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
STATIC = Path(__file__).parent.parent / "static"
ADMIN_USER = "Jaypal"
ADMIN_PASS = "Jaypal"
STATIC_EXTS = {".js", ".css", ".ico", ".png", ".jpg", ".svg", ".woff", ".woff2", ".ttf", ".map"}


def get_supabase_client():
    """Get or create Supabase client."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    return create_client(SUPABASE_URL, SUPABASE_KEY)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)


# ── DB ────────────────────────────────────────────────────────────────────────

def get_db():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY are not configured. Set them in .env file or Vercel environment.")
    if "db" not in g:
        g.db = get_supabase_client()
    return g.db


def get_db_status():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return {"configured": False, "status": "SUPABASE_URL and SUPABASE_KEY not configured.", "url": ""}
    try:
        client = get_supabase_client()
        # Test connection by fetching a simple table
        response = client.table('users').select('id').limit(1).execute()
        return {"configured": True, "status": "connected", "url": SUPABASE_URL}
    except Exception as exc:
        return {"configured": True, "status": f"connection failed: {exc}", "url": SUPABASE_URL}


def print_db_status():
    info = get_db_status()
    print(f"[DB] status={info['status']} url={info['url'] or '<none>'}")


def cursor_of(conn):
    """Return a Supabase client (compatibility wrapper)."""
    return conn

@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    # Supabase client doesn't need explicit close

def now():
    return int(time.time())

def init_db():
    """Initialize database tables in Supabase."""
    client = get_supabase_client()
    if not client:
        return
    try:
        # Check if users table exists by trying to query it
        client.table('users').select('id').limit(1).execute()
    except:
        # Tables will be created via Supabase dashboard or migrations
        print("[INFO] Database tables may need to be created in Supabase dashboard")


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

def query_rows(client, table, filters=None, order_by=None, limit_count=None):
    """Query rows from Supabase table and parse JSON fields."""
    query = client.table(table).select('*')
    if filters:
        for col, val in filters.items():
            query = query.eq(col, val)
    if order_by:
        query = query.order(order_by)
    if limit_count:
        query = query.limit(limit_count)
    try:
        response = query.execute()
        result = []
        for row in response.data:
            data = dict(row) if isinstance(row, dict) else row
            for key in ('items', 'extra_data'):
                if key in data:
                    try:
                        data[key] = json.loads(data[key] or '{}')
                    except (json.JSONDecodeError, TypeError):
                        data[key] = {} if key == 'extra_data' else []
            result.append(data)
        return result
    except Exception as e:
        print(f"[ERROR] query_rows from {table}: {e}")
        return []

def ensure_customer(client, name, phone="", reminder_at=None, extra_data=None):
    """Ensure customer exists, create if not."""
    if not reminder_at:
        reminder_at = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M")
    try:
        # Search for existing customer (case-insensitive)
        existing = client.table('customers').select('*').ilike('name', name).execute()
        if existing.data:
            person = existing.data[0]
            client.table('customers').update({'reminder_at': reminder_at}).eq('id', person['id']).execute()
            return person['id']
        # Insert new customer
        response = client.table('customers').insert({
            'name': name,
            'phone': phone,
            'reminder_at': reminder_at,
            'extra_data': json.dumps(extra_data or {}),
            'created_at': now()
        }).execute()
        return response.data[0]['id']
    except Exception as e:
        print(f"[ERROR] ensure_customer: {e}")
        return None

def account_id_for_method(client, method):
    """Get or create account by method name."""
    try:
        existing = client.table('accounts').select('id').ilike('name', method).execute()
        if existing.data:
            return existing.data[0]['id']
        response = client.table('accounts').insert({
            'name': method.title(),
            'opening_amount': 0,
            'created_at': now()
        }).execute()
        return response.data[0]['id']
    except Exception as e:
        print(f"[ERROR] account_id_for_method: {e}")
        return None

def build_summary(client):
    """Build financial summary."""
    try:
        accounts = query_rows(client, 'accounts', order_by='name')
        tx = query_rows(client, 'transactions', order_by='created_at.desc')
        customers = query_rows(client, 'customers')
        udhari_entries = query_rows(client, 'udhari_entries')
        
        # Calculate customer balances (debit - credit)
        customer_balances = []
        for customer in customers:
            entries = [e for e in udhari_entries if e['customer_id'] == customer['id']]
            balance = sum(e['amount'] if e['kind'] == 'debit' else -e['amount'] for e in entries)
            customer_balances.append({**customer, 'balance': balance})
        customer_balances.sort(key=lambda x: (-x['balance'], x['name']))
        
        income = sum(t['amount'] for t in tx if t['kind'] == 'income')
        expense = sum(t['amount'] for t in tx if t['kind'] == 'expense')
        opening = sum(a.get('opening_amount', 0) for a in accounts)
        
        account_totals = []
        for account in accounts:
            movement = sum(t['amount'] if t['kind'] == 'income' else -t['amount']
                           for t in tx if t.get('account_id') == account['id'])
            account_totals.append({**account, 'current_amount': account.get('opening_amount', 0) + movement})
        
        return {
            'income': income,
            'expense': expense,
            'net_profit': income - expense,
            'opening_total': opening,
            'current_total': opening + income - expense,
            'udhari_total': sum(max(0, cu['balance']) for cu in customer_balances),
            'accounts': account_totals,
            'customers': customer_balances
        }
    except Exception as e:
        print(f"[ERROR] build_summary: {e}")
        return {}

def build_state(client):
    """Build complete app state."""
    return {
        'products': query_rows(client, 'products', order_by='created_at.desc'),
        'sales': query_rows(client, 'sales', order_by='created_at.desc', limit_count=100),
        'stock': query_rows(client, 'stock_purchases', order_by='created_at.desc', limit_count=100),
        'tables': query_rows(client, 'restaurant_tables', order_by='id'),
        'transactions': query_rows(client, 'transactions', order_by='created_at.desc', limit_count=150),
        'custom_fields': query_rows(client, 'custom_fields', order_by='area,created_at'),
        'settings': {r['key']: r['value'] for r in query_rows(client, 'settings')},
        'summary': build_summary(client)
    }


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
    try:
        client = get_db()
        # Check if email exists
        existing = client.table('users').select('id').eq('email', email).execute()
        if existing.data:
            return jsonify({"error": "Email already registered"}), 400
        # Insert new user
        response = client.table('users').insert({
            'email': email,
            'password_hash': generate_password_hash(password),
            'status': 'pending',
            'created_at': now()
        }).execute()
        user_id = response.data[0]['id']
    except Exception as e:
        print(f"[ERROR] signup: {e}")
        return jsonify({"error": str(e)}), 500
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
    try:
        client = get_db()
        # Search for user by email (case-insensitive)
        users = client.table('users').select('*').ilike('email', email).execute()
        if not users.data:
            return jsonify({"error": "Invalid email or password"}), 401
        user = users.data[0]
        if not check_password_hash(user["password_hash"], password):
            return jsonify({"error": "Invalid email or password"}), 401
        if user["status"] == "revoked":
            return jsonify({"error": "Access revoked. Contact admin."}), 403
    except Exception as e:
        print(f"[ERROR] login: {e}")
        return jsonify({"error": str(e)}), 500
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
    try:
        client = get_db()
        response = client.table('users').select('status').eq('id', session["user_id"]).execute()
        if not response.data:
            session.clear()
            return jsonify({"status": "not_found"}), 404
        session["status"] = response.data[0]["status"]
        return jsonify({"status": session["status"], "email": session.get("email")})
    except Exception as e:
        print(f"[ERROR] auth_status: {e}")
        return jsonify({"error": str(e)}), 500

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
    try:
        client = get_db()
        users = query_rows(client, 'users', order_by='created_at.desc')
        return jsonify({"users": users})
    except Exception as e:
        print(f"[ERROR] admin_list_users: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/admin/users/approve", methods=["POST"])
def admin_approve():
    data = request.get_json() or {}
    try:
        client = get_db()
        client.table('users').update({'status': 'approved'}).eq('id', int(data["id"])).execute()
        return jsonify({"ok": True})
    except Exception as e:
        print(f"[ERROR] admin_approve: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/admin/users/revoke", methods=["POST"])
def admin_revoke():
    data = request.get_json() or {}
    try:
        client = get_db()
        client.table('users').update({'status': 'revoked'}).eq('id', int(data["id"])).execute()
        return jsonify({"ok": True})
    except Exception as e:
        print(f"[ERROR] admin_revoke: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/admin/users/delete", methods=["POST"])
def admin_delete():
    data = request.get_json() or {}
    try:
        client = get_db()
        client.table('users').delete().eq('id', int(data["id"])).execute()
        return jsonify({"ok": True})
    except Exception as e:
        print(f"[ERROR] admin_delete: {e}")
        return jsonify({"error": str(e)}), 500


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
    try:
        client = get_db()
        state = build_state(client)
        return jsonify(state)
    except Exception as e:
        print(f"[ERROR] get_state: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/products", methods=["POST"])
def create_product():
    data = request.get_json() or {}
    try:
        client = get_db()
        response = client.table('products').insert({
            'name': data.get("name", "Item").strip(),
            'price': float(data.get("price") or 0),
            'color': data.get("color") or "#2d6cdf",
            'extra_data': json.dumps(data.get("extra_data") or {}),
            'created_at': now()
        }).execute()
        new_id = response.data[0]['id']
        state = build_state(client)
        return jsonify({"id": new_id, "state": state})
    except Exception as e:
        print(f"[ERROR] create_product: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/products/update", methods=["POST"])
def update_product():
    data = request.get_json() or {}
    try:
        client = get_db()
        client.table('products').update({
            'name': data.get("name", "Item").strip(),
            'price': float(data.get("price") or 0),
            'color': data.get("color") or "#176b87",
            'extra_data': json.dumps(data.get("extra_data") or {})
        }).eq('id', int(data["id"])).execute()
        state = build_state(client)
        return jsonify({"state": state})
    except Exception as e:
        print(f"[ERROR] update_product: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/products/delete", methods=["POST"])
def delete_product():
    data = request.get_json() or {}
    try:
        client = get_db()
        client.table('products').delete().eq('id', int(data["id"])).execute()
        state = build_state(client)
        return jsonify({"state": state})
    except Exception as e:
        print(f"[ERROR] delete_product: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/products/reorder", methods=["POST"])
def reorder_products():
    data = request.get_json() or {}
    try:
        client = get_db()
        base_time = now()
        for idx, pid in enumerate(data.get("ids", [])):
            client.table('products').update({'created_at': base_time - idx}).eq('id', int(pid)).execute()
        state = build_state(client)
        return jsonify({"state": state})
    except Exception as e:
        print(f"[ERROR] reorder_products: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/settings", methods=["POST"])
def update_setting():
    data = request.get_json() or {}
    try:
        client = get_db()
        # Upsert: try update first, then insert if not exists
        existing = client.table('settings').select('*').eq('key', data.get("key", "store_name")).execute()
        if existing.data:
            client.table('settings').update({'value': data.get("value", "")}).eq('key', data.get("key", "store_name")).execute()
        else:
            client.table('settings').insert({'key': data.get("key", "store_name"), 'value': data.get("value", "")}).execute()
        state = build_state(client)
        return jsonify({"state": state})
    except Exception as e:
        print(f"[ERROR] update_setting: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/sales", methods=["POST"])
def create_sale():
    data = request.get_json() or {}
    items = data.get("items") or []
    total = float(data.get("total") or sum(float(i.get("price",0)) * float(i.get("qty",1)) for i in items))
    try:
        client = get_db()
        customer_id = data.get("customer_id")
        if data.get("payment_status") == "udhari":
            customer_id = ensure_customer(client, data.get("customer_name") or "Walk-in Customer",
                                          reminder_at=data.get("reminder_at"))
        # Create sale
        sale_response = client.table('sales').insert({
            'source': data.get("source", "calculator"),
            'table_id': data.get("table_id"),
            'customer_id': customer_id,
            'payment_status': data.get("payment_status", "paid"),
            'payment_method': data.get("payment_method", "cash"),
            'subtotal': total,
            'total': total,
            'items': json.dumps(items),
            'extra_data': json.dumps(data.get("extra_data") or {}),
            'created_at': now()
        }).execute()
        sale_id = sale_response.data[0]['id']
        
        if data.get("payment_status") == "udhari":
            client.table('udhari_entries').insert({
                'customer_id': customer_id,
                'kind': 'debit',
                'amount': total,
                'note': 'Bill marked as udhari',
                'source': data.get("source", "calculator"),
                'sale_id': sale_id,
                'created_at': now()
            }).execute()
        else:
            aid = account_id_for_method(client, data.get("payment_method", "cash"))
            client.table('transactions').insert({
                'kind': 'income',
                'account_id': aid,
                'amount': total,
                'title': 'Paid sale',
                'source': data.get("source", "calculator"),
                'ref_id': sale_id,
                'created_at': now()
            }).execute()
        
        if data.get("table_id"):
            client.table('restaurant_tables').update({'status': 'empty'}).eq('id', data["table_id"]).execute()
        
        state = build_state(client)
        return jsonify({"id": sale_id, "state": state})
    except Exception as e:
        print(f"[ERROR] create_sale: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/customers", methods=["POST"])
def create_customer():
    data = request.get_json() or {}
    try:
        client = get_db()
        cid = ensure_customer(client, data.get("name", "Customer").strip(),
                              data.get("phone", ""), data.get("reminder_at"), data.get("extra_data"))
        amount = float(data.get("amount") or 0)
        if amount:
            client.table('udhari_entries').insert({
                'customer_id': cid,
                'kind': 'debit',
                'amount': amount,
                'note': data.get("note", "Opening udhari"),
                'source': 'manual',
                'created_at': now()
            }).execute()
        state = build_state(client)
        return jsonify({"id": cid, "state": state})
    except Exception as e:
        print(f"[ERROR] create_customer: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/udhari/payment", methods=["POST"])
def create_udhari_payment():
    data = request.get_json() or {}
    amount = float(data.get("amount") or 0)
    cid = int(data["customer_id"])
    try:
        client = get_db()
        client.table('udhari_entries').insert({
            'customer_id': cid,
            'kind': 'credit',
            'amount': amount,
            'note': data.get("note", "Payment received"),
            'source': 'payment',
            'created_at': now()
        }).execute()
        aid = account_id_for_method(client, data.get("payment_method", "cash"))
        client.table('transactions').insert({
            'kind': 'income',
            'account_id': aid,
            'amount': amount,
            'title': 'Udhari payment',
            'source': 'udhari',
            'ref_id': cid,
            'created_at': now()
        }).execute()
        state = build_state(client)
        return jsonify({"state": state})
    except Exception as e:
        print(f"[ERROR] create_udhari_payment: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/stock", methods=["POST"])
def create_stock():
    data = request.get_json() or {}
    total = float(data.get("total_cost") or 0)
    try:
        client = get_db()
        stock_response = client.table('stock_purchases').insert({
            'item_name': data.get("item_name", "Stock item").strip(),
            'quantity': float(data.get("quantity") or 0),
            'unit': data.get("unit", ""),
            'total_cost': total,
            'supplier': data.get("supplier", ""),
            'extra_data': json.dumps(data.get("extra_data") or {}),
            'created_at': now()
        }).execute()
        sid = stock_response.data[0]['id']
        aid = account_id_for_method(client, data.get("payment_method", "cash"))
        client.table('transactions').insert({
            'kind': 'expense',
            'account_id': aid,
            'amount': total,
            'title': 'Stock purchase',
            'source': 'stock',
            'ref_id': sid,
            'created_at': now()
        }).execute()
        state = build_state(client)
        return jsonify({"id": sid, "state": state})
    except Exception as e:
        print(f"[ERROR] create_stock: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/accounts", methods=["POST"])
def create_account():
    data = request.get_json() or {}
    try:
        client = get_db()
        response = client.table('accounts').insert({
            'name': data.get("name", "Account").strip(),
            'opening_amount': float(data.get("opening_amount") or 0),
            'extra_data': json.dumps(data.get("extra_data") or {}),
            'created_at': now()
        }).execute()
        new_id = response.data[0]['id']
        state = build_state(client)
        return jsonify({"id": new_id, "state": state})
    except Exception as e:
        print(f"[ERROR] create_account: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/transactions", methods=["POST"])
def create_transaction():
    data = request.get_json() or {}
    try:
        client = get_db()
        response = client.table('transactions').insert({
            'kind': data.get("kind", "income"),
            'account_id': data.get("account_id"),
            'amount': float(data.get("amount") or 0),
            'title': data.get("title", "Manual entry"),
            'source': 'manual',
            'extra_data': json.dumps(data.get("extra_data") or {}),
            'created_at': now()
        }).execute()
        new_id = response.data[0]['id']
        state = build_state(client)
        return jsonify({"id": new_id, "state": state})
    except Exception as e:
        print(f"[ERROR] create_transaction: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/tables", methods=["POST"])
def create_table():
    data = request.get_json() or {}
    try:
        client = get_db()
        response = client.table('restaurant_tables').insert({
            'label': data.get("label") or f"T-{uuid.uuid4().hex[:3].upper()}",
            'x': float(data.get("x") or 80),
            'y': float(data.get("y") or 80),
            'seats': int(data.get("seats") or 4),
            'status': data.get("status", "empty"),
            'extra_data': json.dumps(data.get("extra_data") or {}),
            'created_at': now()
        }).execute()
        new_id = response.data[0]['id']
        state = build_state(client)
        return jsonify({"id": new_id, "state": state})
    except Exception as e:
        print(f"[ERROR] create_table: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/tables/move", methods=["POST"])
def move_table():
    data = request.get_json() or {}
    try:
        client = get_db()
        client.table('restaurant_tables').update({
            'x': data["x"],
            'y': data["y"],
            'status': data.get("status", "empty")
        }).eq('id', data["id"]).execute()
        state = build_state(client)
        return jsonify({"state": state})
    except Exception as e:
        print(f"[ERROR] move_table: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/tables/update", methods=["POST"])
def update_table():
    data = request.get_json() or {}
    try:
        client = get_db()
        client.table('restaurant_tables').update({
            'label': data.get("label", "Table").strip(),
            'seats': int(data.get("seats") or 4),
            'x': float(data.get("x") or 80),
            'y': float(data.get("y") or 80),
            'status': data.get("status", "empty"),
            'extra_data': json.dumps(data.get("extra_data") or {})
        }).eq('id', int(data["id"])).execute()
        state = build_state(client)
        return jsonify({"state": state})
    except Exception as e:
        print(f"[ERROR] update_table: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/custom-fields", methods=["POST"])
def create_custom_field():
    data = request.get_json() or {}
    try:
        client = get_db()
        response = client.table('custom_fields').insert({
            'area': data.get("area", "general"),
            'name': data.get("name", "Field"),
            'field_type': data.get("field_type", "text"),
            'created_at': now()
        }).execute()
        new_id = response.data[0]['id']
        state = build_state(client)
        return jsonify({"id": new_id, "state": state})
    except Exception as e:
        print(f"[ERROR] create_custom_field: {e}")
        return jsonify({"error": str(e)}), 500

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

if SUPABASE_URL and SUPABASE_KEY:
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
