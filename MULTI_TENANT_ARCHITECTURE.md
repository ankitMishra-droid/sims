# MULTI-TENANT WORKSPACE ARCHITECTURE
## Smart Inventory Management System (SIMS / StockSangati)
**Updated:** 2026-11-27 (Phase 5)

---

## 1. Tenant Model & Isolation

- **Entities:** `Business` (`id`, `name`, `business_type` in `retailer | wholesaler | supplier`, `owner_user_id`, preferences), `BusinessMember` (`(business_id, user_id)` unique membership with per-workspace `role`), `BusinessInvitation` (email-matched invite tokens).
- **Business Type vs. Role Separation:** `business_type` controls domain workflows (`retailer` / `wholesaler` ERP vs. `supplier` shared order portal), while `BusinessMember.role` controls user actions within that workspace.
- **Server-Side Workspace Resolution (`get_business_context`):**
  - Resolves `X-Business-Id` header or `User.active_business_id`.
  - Queries `BusinessMember JOIN Business` filtering `user_id == current_user.id`, `BusinessMember.is_active == True`, and `Business.is_active == True`.
  - Requests referencing an unauthorized workspace return `403 Forbidden`. Cross-tenant resource lookups filter strictly by `business_id == ctx.business_id` and return `404 Not Found`.

---

## 2. Workspace Creation, Switching & Invitations (`/api/businesses`, `/api/members`)

- `POST /api/businesses/` creates a new isolated `Business`, assigns the creator as `owner` (or `supplier` for supplier workspaces), updates `active_business_id`, and initializes onboarding progress.
- `POST /api/businesses/switch` verifies active membership, updates `users.active_business_id`, and returns fresh tokens (`TokenResponse` + `workspace`).
- **Frontend Cache Clearing (`src/store/index.js`):** Dispatching `auth/switchWorkspaceReset` or `auth/logout` clears tenant-scoped Redux slices (`products`, `sales`, `suppliers`, `purchaseOrders`, `inventory`, `dashboard`) so previous workspace data cannot remain visible.
- **Invitations:** `POST /api/members/invite` creates an expiring token for an explicit email and role; `POST /api/members/accept-invitation` enforces email ownership match before activating `BusinessMember`.

---

## 3. Controlled Supplier Portal Collaboration (`/api/supplier-portal`)

- Buyers link a `Supplier` vendor record to an active supplier-type `Business` via `PATCH /api/suppliers/{id}/link-workspace`.
- Purchase orders are **never** automatically visible across supplier accounts. A buyer must explicitly authorize visibility via `POST /api/purchase-orders/{id}/share`.
- Supplier workspaces call `GET /api/supplier-portal/purchase-orders` and `POST /api/supplier-portal/purchase-orders/{id}/status` (`ACKNOWLEDGED`, `DISPATCHED`, `ISSUE_REPORTED`), enforced by `require_business_types(["supplier"])`. Buyer inventory, sales, customers, and unshared POs remain strictly inaccessible (`403` / `404`).
