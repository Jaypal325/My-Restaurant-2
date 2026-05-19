-- ============================================================
-- Gopi Store App — PostgreSQL Schema for Supabase
-- Run this ONCE in Supabase → SQL Editor → New query
-- ============================================================

-- Auth: User accounts (pending → approved → revoked)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'revoked')),
    created_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    price REAL NOT NULL DEFAULT 0,
    color TEXT NOT NULL DEFAULT '#2d6cdf',
    extra_data TEXT NOT NULL DEFAULT '{}',
    created_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    phone TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    reminder_at TEXT,
    extra_data TEXT NOT NULL DEFAULT '{}',
    created_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS udhari_entries (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('debit', 'credit')),
    amount REAL NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    sale_id INTEGER,
    created_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS sales (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    table_id INTEGER,
    customer_id INTEGER,
    payment_status TEXT NOT NULL CHECK(payment_status IN ('paid', 'udhari')),
    payment_method TEXT NOT NULL DEFAULT 'cash',
    subtotal REAL NOT NULL,
    total REAL NOT NULL,
    items TEXT NOT NULL,
    extra_data TEXT NOT NULL DEFAULT '{}',
    created_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS stock_purchases (
    id SERIAL PRIMARY KEY,
    item_name TEXT NOT NULL,
    quantity REAL NOT NULL DEFAULT 0,
    unit TEXT NOT NULL DEFAULT '',
    total_cost REAL NOT NULL DEFAULT 0,
    supplier TEXT NOT NULL DEFAULT '',
    extra_data TEXT NOT NULL DEFAULT '{}',
    created_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    opening_amount REAL NOT NULL DEFAULT 0,
    extra_data TEXT NOT NULL DEFAULT '{}',
    created_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('income', 'expense')),
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    amount REAL NOT NULL,
    title TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    ref_id INTEGER,
    extra_data TEXT NOT NULL DEFAULT '{}',
    created_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS restaurant_tables (
    id SERIAL PRIMARY KEY,
    label TEXT NOT NULL,
    x REAL NOT NULL DEFAULT 80,
    y REAL NOT NULL DEFAULT 80,
    seats INTEGER NOT NULL DEFAULT 4,
    status TEXT NOT NULL DEFAULT 'empty',
    extra_data TEXT NOT NULL DEFAULT '{}',
    created_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS custom_fields (
    id SERIAL PRIMARY KEY,
    area TEXT NOT NULL,
    name TEXT NOT NULL,
    field_type TEXT NOT NULL DEFAULT 'text',
    created_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Seed default accounts (only if table is empty)
INSERT INTO accounts(name, opening_amount, created_at)
SELECT name, 0, EXTRACT(EPOCH FROM NOW())::BIGINT
FROM (VALUES ('Cash'), ('Online'), ('Bank')) AS v(name)
WHERE NOT EXISTS (SELECT 1 FROM accounts LIMIT 1);
