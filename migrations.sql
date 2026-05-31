-- Multi-User System Migration
-- Run these in Supabase SQL Editor to enable multi-user data isolation

-- Add user_id to products table
ALTER TABLE products ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
CREATE INDEX idx_products_user_id ON products(user_id);

-- Add user_id to customers table
ALTER TABLE customers ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
CREATE INDEX idx_customers_user_id ON customers(user_id);

-- Add user_id to udhari_entries table
ALTER TABLE udhari_entries ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
CREATE INDEX idx_udhari_entries_user_id ON udhari_entries(user_id);

-- Add user_id to sales table
ALTER TABLE sales ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
CREATE INDEX idx_sales_user_id ON sales(user_id);

-- Add user_id to stock_purchases table
ALTER TABLE stock_purchases ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
CREATE INDEX idx_stock_purchases_user_id ON stock_purchases(user_id);

-- Add user_id to accounts table and fix global unique constraint
ALTER TABLE accounts DROP CONSTRAINT IF EXISTS accounts_name_key;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
UPDATE accounts SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1) WHERE user_id IS NULL AND EXISTS (SELECT 1 FROM users);
DELETE FROM accounts WHERE user_id IS NULL;
DROP INDEX IF EXISTS idx_accounts_user_name;
CREATE UNIQUE INDEX idx_accounts_user_name ON accounts(user_id, name);
CREATE INDEX IF NOT EXISTS idx_accounts_user_id ON accounts(user_id);

-- Add user_id to transactions table
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id);

-- Add user_id to restaurant_tables table (if it exists)
ALTER TABLE restaurant_tables ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_restaurant_tables_user_id ON restaurant_tables(user_id);

-- Settings table: make it per-user instead of global by replacing settings_pkey with composite PK
ALTER TABLE settings DROP CONSTRAINT IF EXISTS settings_pkey;
ALTER TABLE settings ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
UPDATE settings SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1) WHERE user_id IS NULL AND EXISTS (SELECT 1 FROM users);
DELETE FROM settings WHERE user_id IS NULL;
ALTER TABLE settings ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE settings ADD PRIMARY KEY (user_id, key);
DROP INDEX IF EXISTS idx_settings_user_key;
DROP INDEX IF EXISTS idx_settings_key;

-- Add user_id to custom_fields table
ALTER TABLE custom_fields ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_custom_fields_user_id ON custom_fields(user_id);

-- Add user_id to customers table and fix global unique constraint
ALTER TABLE customers DROP CONSTRAINT IF EXISTS customers_name_key;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
UPDATE customers SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1) WHERE user_id IS NULL AND EXISTS (SELECT 1 FROM users);
DELETE FROM customers WHERE user_id IS NULL;
DROP INDEX IF EXISTS idx_customers_user_name;
CREATE UNIQUE INDEX idx_customers_user_name ON customers(user_id, name);
CREATE INDEX IF NOT EXISTS idx_customers_user_id ON customers(user_id);

-- Note: These migrations assume the tables already exist. 
-- Run them one at a time in Supabase and verify each succeeds.
