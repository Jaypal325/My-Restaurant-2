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

-- Add user_id to accounts table
ALTER TABLE accounts ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
CREATE INDEX idx_accounts_user_id ON accounts(user_id);

-- Add user_id to transactions table
ALTER TABLE transactions ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
CREATE INDEX idx_transactions_user_id ON transactions(user_id);

-- Add user_id to restaurant_tables table (if it exists)
ALTER TABLE restaurant_tables ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
CREATE INDEX idx_restaurant_tables_user_id ON restaurant_tables(user_id);

-- Settings table: make it per-user instead of global
ALTER TABLE settings ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
CREATE UNIQUE INDEX idx_settings_user_key ON settings(user_id, key);
-- Drop old unique constraint if it exists
DROP INDEX IF EXISTS idx_settings_key;

-- Add user_id to custom_fields table
ALTER TABLE custom_fields ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
CREATE INDEX idx_custom_fields_user_id ON custom_fields(user_id);

-- Note: These migrations assume the tables already exist. 
-- Run them one at a time in Supabase and verify each succeeds.
