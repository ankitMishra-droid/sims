# SIMS DATABASE DESIGN & SCHEMA SPECIFICATION
## Smart Inventory Management System (SIMS / StockSangati)
**Updated:** 2026-11-27 (Post-Phase 5 Auth, Workspaces & Onboarding)  
**Active Engine:** SQLite (`backend/inventory.db`) via SQLAlchemy 2.1.3 with `PRAGMA foreign_keys=ON` and `PRAGMA busy_timeout=5000` (PostgreSQL dialect normalization configured in `backend/app/database.py`).  
**Safe Upgrade Module:** `backend/app/db_migrate.py` (`ensure_schema_and_backfill`) creates new tables, runs idempotent `ALTER TABLE ADD COLUMN` upgrades, creates indexes, and backfills tenant ownership without dropping or overwriting existing records.

---

## 1. Entity-Relationship Diagram

```mermaid
erDiagram
    USERS {
        int id PK
        varchar name
        varchar email UK
        varchar password_hash
        varchar role
        int active_business_id FK
        varchar preferred_language
        int token_version
        boolean is_active
    }

    REVOKED_TOKENS {
        int id PK
        varchar jti UK
        int user_id FK
        varchar token_type
        datetime expires_at
    }

    PASSWORD_RESET_TOKENS {
        int id PK
        int user_id FK
        varchar token_hash UK
        datetime expires_at
        datetime used_at
    }

    BUSINESSES {
        int id PK
        varchar name
        varchar business_type
        int owner_user_id FK
        varchar default_language
        varchar contact_email
        varchar currency
        int low_stock_threshold_default
        boolean allow_negative_stock
        boolean onboarding_completed
        boolean is_active
    }

    BUSINESS_INVITATIONS {
        int id PK
        int business_id FK
        varchar email
        varchar role
        varchar token UK
        varchar status
        datetime expires_at
    }

    BUSINESS_ONBOARDING_PROGRESS {
        int id PK
        int business_id UK
        int user_id FK
        int current_step
        text completed_steps_json
        text skipped_steps_json
        text step_data_json
        boolean is_completed
    }

    BUSINESS_MEMBERS {
        int id PK
        int business_id FK
        int user_id FK
        varchar role
        boolean is_active
    }

    SUPPLIERS {
        int id PK
        int business_id FK
        int linked_business_id FK
        varchar name
        varchar email
        int lead_time_days
        boolean is_active
    }

    PRODUCTS {
        int id PK
        int business_id FK
        varchar sku
        varchar name
        varchar category
        int current_stock
        int reorder_level
        int supplier_id FK
        boolean is_active
    }

    SALES {
        int id PK
        int business_id FK
        int product_id FK
        datetime sales_date
        int quantity_sold
        float selling_price
        float revenue
        varchar status
        int created_by FK
        varchar idempotency_key
    }

    INVENTORY_LOGS {
        int id PK
        int business_id FK
        int product_id FK
        datetime timestamp
        varchar movement_type
        int stock_in
        int stock_out
        int previous_stock
        int closing_stock
        varchar reference_type
        int reference_id
        int user_id FK
        varchar reason
    }

    PURCHASE_ORDERS {
        int id PK
        int business_id FK
        varchar order_number
        int supplier_id FK
        varchar status
        numeric total_amount
        boolean shared_with_supplier
        varchar supplier_status
        datetime order_date
        int created_by FK
    }

    PURCHASE_ORDER_SUPPLIER_ACTIONS {
        int id PK
        int purchase_order_id FK
        int supplier_business_id FK
        int user_id FK
        varchar action
        text notes
    }

    PURCHASE_ORDER_ITEMS {
        int id PK
        int purchase_order_id FK
        int product_id FK
        int ordered_quantity
        int received_quantity
        numeric unit_cost
    }

    GOODS_RECEIPTS {
        int id PK
        varchar receipt_number
        int business_id FK
        int purchase_order_id FK
        int received_by FK
        varchar idempotency_key
        datetime received_at
    }

    GOODS_RECEIPT_ITEMS {
        int id PK
        int goods_receipt_id FK
        int purchase_order_item_id FK
        int product_id FK
        int quantity_received
    }

    BUSINESSES ||--o{ BUSINESS_MEMBERS : "has"
    USERS ||--o{ BUSINESS_MEMBERS : "belongs_to"
    BUSINESSES ||--o{ SUPPLIERS : "owns"
    BUSINESSES ||--o{ PRODUCTS : "owns"
    BUSINESSES ||--o{ SALES : "records"
    BUSINESSES ||--o{ INVENTORY_LOGS : "audits"
    BUSINESSES ||--o{ PURCHASE_ORDERS : "issues"
    BUSINESSES ||--o{ GOODS_RECEIPTS : "receives"
    SUPPLIERS ||--o{ PRODUCTS : "supplies"
    SUPPLIERS ||--o{ PURCHASE_ORDERS : "fulfills"
    PURCHASE_ORDERS ||--o{ PURCHASE_ORDER_ITEMS : "contains"
    PURCHASE_ORDERS ||--o{ GOODS_RECEIPTS : "fulfilled_by"
    GOODS_RECEIPTS ||--o{ GOODS_RECEIPT_ITEMS : "details"
    PRODUCTS ||--o{ SALES : "sold_in"
    PRODUCTS ||--o{ INVENTORY_LOGS : "tracked_by"
    PRODUCTS ||--o{ PURCHASE_ORDER_ITEMS : "ordered_in"
```

---

## 2. Key Schema & Integrity Enforcements

1. **Tenant Isolation Columns & Unique Scopes:**
   - `businesses` and `business_members` (`UNIQUE(business_id, user_id)`).
   - `business_id` FK and index on `suppliers`, `products`, `sales`, `inventory_logs`, `purchase_orders`, `goods_receipts`.
   - `UNIQUE(business_id, sku)` on `products`; `UNIQUE(business_id, name)` on `suppliers`; `UNIQUE(business_id, order_number)` on `purchase_orders`.
2. **Idempotency Constraints:**
   - `UNIQUE(business_id, idempotency_key)` on `sales` and `goods_receipts`.
3. **Check Constraints (enforced on newly created tables & validated in services):**
   - `products`: `current_stock >= 0`, `cost_price >= 0`, `selling_price >= 0`, `reorder_level >= 0`.
   - `sales`: `quantity_sold > 0`, `selling_price >= 0`, `revenue >= 0`.
   - `purchase_order_items`: `ordered_quantity > 0`, `0 <= received_quantity <= ordered_quantity`, `unit_cost >= 0`.
   - `goods_receipt_items`: `quantity_received > 0`.
4. **Traceable Ledger (`inventory_logs`):**
   - Stores `business_id`, `product_id`, `movement_type` (`OPENING_STOCK`, `PURCHASE_RECEIPT`, `SALE`, `STOCK_ADJUSTMENT`, `RETURN`, `REVERSAL`), `stock_in`, `stock_out`, `previous_stock`, `closing_stock`, `reference_type`, `reference_id`, `user_id`, `reason`, `timestamp`.
5. **Performance Indexes:**
   - Composite indexes `(business_id, product_id, sales_date)` on `sales`, `(business_id, product_id, timestamp)` on `inventory_logs`, `(business_id, status)` on `purchase_orders`, and `(purchase_order_id, product_id)` on `purchase_order_items`.
6. **Known Remaining Limitation:**
   - Stock reservations are not yet implemented (`reserved_stock` is explicitly `0` in inventory position responses).
