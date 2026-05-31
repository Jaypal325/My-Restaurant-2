# Multi-User System Implementation Guide

## Overview
Your Restaurant app now has a complete multi-user system where each user sees only their own data (products, sales, customers, accounts, transactions, tables, and settings).

## What Changed

### 1. **Database Schema**
Added `user_id` foreign key to all data tables to enable data isolation:
- `products`
- `customers`
- `udhari_entries`
- `sales`
- `stock_purchases`
- `accounts`
- `transactions`
- `restaurant_tables`
- `custom_fields`
- `settings` (now per-user instead of global)

See [migrations.sql](migrations.sql) for the exact SQL commands.

### 2. **Backend Changes (api/index.py)**
- Updated `query_rows()` to filter by `user_id` for all queries
- Updated `build_state()` to pass `user_id` to all queries
- Updated `build_summary()` to calculate per-user financial summaries
- Updated `ensure_customer()` and `account_id_for_method()` to include user context
- **All 15+ API endpoints** now:
  - Extract `user_id` from session: `user_id = session.get("user_id")`
  - Include `user_id` when creating records
  - Filter by `user_id` when updating/deleting records
  - Pass `user_id` to `build_state()` when returning state

## How to Deploy

### Step 1: Run Database Migration
1. Go to your **Supabase dashboard** → **SQL Editor**
2. Create a new query
3. Copy the entire contents of [migrations.sql](migrations.sql)
4. Run the migration

⚠️ **Important**: Run the migration commands carefully. If you encounter errors about columns already existing, that's okay - they likely already exist from a previous migration.

### Step 2: Verify Backend Changes
The API code has been updated. Verify these key functions have `user_id` parameters:
- `query_rows(client, table, filters=None, order_by=None, limit_count=None, user_id=None)`
- `build_state(client, user_id=None)`
- `build_summary(client, user_id=None)`

### Step 3: Test the Multi-User System

1. **Create test accounts**:
   - Sign up with email: `user1@test.com` / password: `test123`
   - Sign up with email: `user2@test.com` / password: `test123`
   - Log in to admin with: `Jaypal` / `Jaypal`
   - Approve both users in the admin panel

2. **Add test data**:
   - Log in as user1
   - Create a few products (e.g., "Coffee", "Tea")
   - Create a test sale
   - Log out

3. **Verify isolation**:
   - Log in as user2
   - Confirm you see **NO** products from user1
   - Create your own products
   - Log out

4. **Verify user1's data persists**:
   - Log in as user1
   - Confirm your original products are still there
   - user2's products are **NOT** visible

## Data Structure After Migration

### Each User Now Has:
- ✅ Personal products list
- ✅ Personal sales records
- ✅ Personal customers and udhari tracking
- ✅ Personal stock purchases
- ✅ Personal accounts and transactions
- ✅ Personal restaurant tables
- ✅ Personal settings (store name, custom fields)
- ✅ Personal financial summary

### Admin Features:
- User list with approval/revocation
- Can see user accounts but not their individual data
- (Optional: could add admin oversight features later)

## Important Notes

### Settings Table Change
The `settings` table is now **per-user**:
- Before: All users shared `store_name`, custom fields, etc.
- After: Each user has their own `store_name`, custom fields, etc.

This means after migration:
- Each user should set their own store name
- Custom fields are per-user

### Backward Compatibility
⚠️ **Existing data without user_id**: Old records won't have `user_id` set. You'll need to:
1. Either clean the database before migration
2. Or manually update existing records to assign them to users
3. Option: Add a script to batch-assign old records to a default user

## Code Examples

### Creating a Record (Now Includes user_id)
```python
user_id = session.get("user_id")
client.table('products').insert({
    'name': product_name,
    'price': price,
    'user_id': user_id,  # ← NEW
    'created_at': now()
}).execute()
```

### Querying Data (Now Filters by user_id)
```python
user_id = session.get("user_id")
products = query_rows(client, 'products', user_id=user_id)  # ← NEW parameter
```

### Updating/Deleting (Now Checks user_id)
```python
user_id = session.get("user_id")
client.table('products').delete()\
    .eq('id', product_id)\
    .eq('user_id', user_id)  # ← NEW safety check
    .execute()
```

## Troubleshooting

### "Column user_id does not exist"
- The migration hasn't been run yet
- Run [migrations.sql](migrations.sql) in Supabase SQL Editor

### Users see each other's data
- Old data might not have `user_id` assigned
- Check that the migration ran successfully
- Verify that `query_rows()` is being called with `user_id` parameter

### Settings not saving per-user / Duplicate key violate settings_pkey
- The settings table originally has `key` as its PRIMARY KEY (`settings_pkey`).
- In multi-user setups, you must drop the single-column primary key constraint and create a composite primary key on `(user_id, key)`.
- Make sure to run the updated [migrations.sql](migrations.sql) which drops the constraint and alters the settings table appropriately.

### Duplicate key violate accounts_name_key
- The accounts table originally has a global `UNIQUE (name)` constraint.
- In multi-user setups, you must drop `accounts_name_key` and create a unique index/constraint per user on `(user_id, name)`.
- The updated migration script handles this automatically.

## Next Steps (Optional Enhancements)

1. **Migrate existing data**: Script to assign old records to users
2. **Admin dashboard**: Show analytics across all users
3. **Multi-tenant features**: Share data between specific users
4. **Data export**: Let users export their data
5. **Soft delete**: Archive old data instead of deleting

## Files Modified
- `api/index.py` - All backend logic updated for user isolation
- `migrations.sql` - Database schema migration (needs to be run in Supabase)

## Questions?
Check the updated `api/index.py` to see how any specific endpoint now handles user isolation. All endpoints follow the same pattern: extract user_id from session and pass it through the data access layer.
