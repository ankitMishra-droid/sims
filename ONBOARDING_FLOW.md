# GUIDED ONBOARDING FLOW SPECIFICATION
## Smart Inventory Management System (SIMS / StockSangati)
**Updated:** 2026-11-27 (Phase 5)

---

## 1. Architecture & Persistence

- **Model:** `BusinessOnboardingProgress` (`business_id`, `user_id`, `current_step`, `completed_steps_json`, `skipped_steps_json`, `step_data_json`, `is_completed`, `completed_at`).
- **Endpoints:** `GET /api/onboarding/progress` and `POST /api/onboarding/step` (`step`, `action`: `complete | skip | back`, `data`), protected by `onboarding.manage`.
- **Frontend:** [OnboardingWizardPage.jsx](file:///d:/sims/frontend/smart%20inventory%20forecast%20management%20system/src/pages/onboarding/OnboardingWizardPage.jsx) (`/onboarding`).

---

## 2. Step Matrix & Business-Type Adaptation

| Step | Title | Retailer / Wholesaler | Supplier | Optional? | Validation / Safety Rule |
| :---: | :--- | :---: | :---: | :---: | :--- |
| 1 | Welcome | Yes | Yes | No | Initializes wizard state |
| 2 | Business Type | Yes | Yes | No | Must be `retailer`, `wholesaler`, or `supplier` |
| 3 | Preferred Language | Yes | Yes | No | Updates `User.preferred_language` & `Business.default_language` |
| 4 | Business Profile | Yes | Yes | No | Business name >= 2 chars; contact & address saved |
| 5 | Preferences | Yes | Yes | No | Currency, low-stock threshold >= 0, negative-stock toggle |
| 6 | Initial Products | Yes | Skipped | Yes | Manual entry OR CSV Upload -> Preview -> Validate -> Confirm; duplicate-safe by `(business_id, sku)` with `0` stock |
| 7 | Suppliers | Yes | Skipped | Yes | Duplicate-safe by `(business_id, name)` |
| 8 | Opening Stock | Yes | Skipped | Yes | Idempotent per product: checks `InventoryLog.movement_type == 'OPENING_STOCK'` before crediting ledger |
| 9 | Quick Tour | Yes | Yes | Yes | Highlights relevant business modules |
| 10 | Open Dashboard | Yes | Yes | No | Marks `onboarding_completed = True` |
