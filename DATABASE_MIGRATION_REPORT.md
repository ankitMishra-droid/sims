# DATABASE MIGRATION REPORT (PHASE 5)
## Smart Inventory Management System (SIMS / StockSangati)
**Date:** 2026-11-27  
**Active Database:** `backend/inventory.db` (SQLite with `PRAGMA foreign_keys=ON` and `PRAGMA busy_timeout=5000`)  
**Migration Engine:** `backend/app/db_migrate.py` (`ensure_schema_and_backfill`)

---

## 1. Migration Strategy Assessment

- **Existing Tooling:** `backend/alembic.ini` and `backend/migrations/` are initialized on disk, with `backend/migrations/versions/` empty.
- **Active Schema Management:** `backend/app/main.py` runs `ensure_schema_and_backfill(engine)` at startup (`SQLAlchemy base.metadata.create_all` + idempotent `_add_column_if_missing` checks + safe non-destructive data backfills). Keeping all Phase 5 schema additions inside `db_migrate.py` preserves continuity with Phase 3 without resetting `inventory.db` or invalidating existing single-tenant backfills.

---

## 2. Schema Changes Applied

### 2.1 New Tables
1. `revoked_tokens` (`id`, `jti`, `user_id`, `token_type`, `expires_at`, `revoked_at`)
2. `password_reset_tokens` (`id`, `user_id`, `token_hash`, `expires_at`, `used_at`, `created_at`)
3. `business_invitations` (`id`, `business_id`, `email`, `role`, `token`, `invited_by`, `status`, `expires_at`, `accepted_at`, `created_at`)
4. `business_onboarding_progress` (`id`, `business_id`, `user_id`, `current_step`, `completed_steps_json`, `skipped_steps_json`, `step_data_json`, `is_completed`, `completed_at`, `updated_at`)
5. `purchase_order_supplier_actions` (`id`, `purchase_order_id`, `supplier_business_id`, `user_id`, `action`, `notes`, `created_at`)

### 2.2 Backward-Compatible Additive Columns & Backfills
- **`users`:** `preferred_language VARCHAR(10) DEFAULT 'en'`, `token_version INTEGER DEFAULT 1`
- **`businesses`:** `default_language`, `contact_email`, `contact_phone`, `address`, `gstin_or_tax_id`, `currency DEFAULT 'INR'`, `low_stock_threshold_default DEFAULT 10`, `onboarding_completed BOOLEAN DEFAULT 0`
  - Pre-existing populated workspaces (`EXISTS (SELECT 1 FROM products ...)`) without onboarding rows were safely flagged `onboarding_completed = 1` so existing operator accounts are not blocked.
- **`suppliers`:** `linked_business_id INTEGER` (nullable FK to `businesses.id`)
- **`purchase_orders`:** `shared_with_supplier BOOLEAN DEFAULT 0`, `shared_at DATETIME`, `supplier_status VARCHAR(40)`, `supplier_notes TEXT`, `supplier_acknowledged_at DATETIME`, `supplier_dispatched_at DATETIME` (existing POs stay unshared by default).

---

## 3. Backup, Verification & Rollback / Recovery Procedure

- **Pre-Migration Copy Test:** Verified `ensure_schema_and_backfill` on an isolated copy (`scratch/inventory_mig_test.db`) before running against `backend/inventory.db`:
  - `22` products and `13,604` sales preserved intact; `businesses` `(1, 1), (2, 1)` marked `onboarding_completed = 1`.
- **Backup & Rollback Steps (SQLite):**
  1. Stop uvicorn (`Ctrl+C`) and take an atomic file backup: `Copy-Item d:\sims\backend\inventory.db d:\sims\backend\inventory.db.bak`.
  2. Since Phase 5 schema additions are additive tables and nullable/defaulted columns, Phase 3–4 read/write queries continue to operate without alteration.
  3. To roll back cleanly to pre-Phase-5 binary/schema state: stop uvicorn, restore `Copy-Item inventory.db.bak inventory.db -Force`, and restart on the pre-Phase-5 commit.
