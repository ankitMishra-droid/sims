# REST API SPECIFICATION & CONTRACTS
## Smart Inventory Management System (SIMS / StockSangati)
**Updated:** 2026-11-27 (Phase 5 Auth, Workspaces, Onboarding & Supplier Portal)  
**Base URL:** `http://127.0.0.1:8000` (Vite dev proxy forwards `/api` and `/dashboard`)

> All workspace endpoints require `Authorization: Bearer <jwt_token>`. Active workspace resolves from `X-Business-Id` or `User.active_business_id`, verified against active `BusinessMember` & `Business` rows.

---

## 1. Public & Authentication (`/api/auth`)
- `GET /` — Public health check.
- `POST /api/auth/register` *(rate-limited)* — Creates `User` (`preferred_language`, optional `create_workspace` flag). Returns `UserResponse` (`201`).
- `POST /api/auth/login` *(rate-limited)* — Verifies credentials; returns `{ access_token, refresh_token, token_type, expires_in, user }`.
- `POST /api/auth/refresh` *(rate-limited)* — Validates & rotates `refresh_token`, revoking prior refresh `jti`.
- `POST /api/auth/logout` — Revokes active `access_token` (`jti`) & optional `refresh_token`; supports `revoke_all: true`.
- `GET /api/auth/me` & `PATCH /api/auth/me` — Fetch/update `name` and `preferred_language`.
- `POST /api/auth/change-password` — Verifies current password, updates hash, increments `token_version`, returns fresh tokens.
- `POST /api/auth/password-reset/request` & `/confirm` *(rate-limited)* — Non-enumerating reset request + SHA-256 single-use token confirmation.

---

## 2. Workspaces, Memberships & Onboarding (`/api/businesses`, `/api/members`, `/api/onboarding`)
- `GET /api/businesses/` — Lists user's authorized workspaces with roles & permissions.
- `POST /api/businesses/` — Creates isolated `retailer` / `wholesaler` / `supplier` workspace, assigns creator `owner` (or `supplier` for supplier business), initializes onboarding.
- `GET /api/businesses/current` & `PUT /api/businesses/current` (`business.update`) — Active workspace profile & settings.
- `POST /api/businesses/switch` — Verifies membership, switches `active_business_id`, returns fresh tokens + workspace.
- `GET /api/members/` (`members.read`), `POST /api/members/invite` (`members.invite`), `GET /api/members/invitations`, `GET /api/members/my-invitations`, `POST /api/members/accept-invitation`, `DELETE /api/members/invitations/{id}`, `PATCH /api/members/{id}/role` (`members.manage_roles`), `DELETE /api/members/{id}`.
- `GET /api/onboarding/progress` & `POST /api/onboarding/step` (`onboarding.manage`) — Persists steps `1..10`, supports `complete | skip | back`, business-type-adaptive steps, duplicate-safe seeding & idempotent `OPENING_STOCK`.

---

## 3. Core ERP & Controlled Supplier Portal
- **Products (`/api/products/`), Inventory (`/api/inventory/`), Sales (`/api/sales/`), Suppliers (`/api/suppliers/`), Purchase Orders (`/api/purchase-orders/`), Dashboard (`/dashboard/`), ML (`/api/forecast`, `/api/decision`, `/api/simulator`, `/api/analytics`)** — All enforced by `BusinessContext` and `role_satisfies_any`.
- `PATCH /api/suppliers/{supplier_id}/link-workspace` (`admin`, `manager`, `owner`) — Links supplier vendor entry to an active `supplier`-type business.
- `POST /api/purchase-orders/{order_id}/share` & `/unshare` (`admin`, `manager`, `owner`) — Explicitly authorizes/revokes visibility of a PO to the linked supplier workspace.
- `GET /api/supplier-portal/purchase-orders`, `GET /api/supplier-portal/purchase-orders/{id}`, `POST /api/supplier-portal/purchase-orders/{id}/status` (`supplier_portal.*` + `business_type == "supplier"`) — Exposes only explicitly shared POs to supplier workspaces; allows recording `ACKNOWLEDGED`, `DISPATCHED`, `ISSUE_REPORTED` while blocking quantity/stock tampering.
