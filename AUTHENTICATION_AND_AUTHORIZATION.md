# AUTHENTICATION & AUTHORIZATION ARCHITECTURE
## Smart Inventory Management System (SIMS / StockSangati)
**Updated:** 2026-11-27 (Phase 5)

---

## 1. Authentication Design

- **Password Storage (`backend/app/core/security.py`):** Argon2id hashing via `pwdlib.PasswordHash.recommended()`. Plaintext passwords are never logged, stored, or serialized in API responses.
- **JWT Access & Refresh Tokens:**
  - `POST /api/auth/login` and `POST /api/auth/refresh` issue HS256-signed `access_token` (default 24h via `ACCESS_TOKEN_EXPIRE_MINUTES`) and `refresh_token` (default 7d via `REFRESH_TOKEN_EXPIRE_MINUTES`), each carrying `sub`, `jti`, `type` (`access` / `refresh`), `token_version`, `business_id`, `iat`, and `exp`.
  - `POST /api/auth/refresh` validates the refresh token, revokes the used refresh `jti`, and issues a fresh rotated pair.
- **Logout & Session Revocation (`revoked_tokens` + `users.token_version`):**
  - `POST /api/auth/logout` persists the current `access_token` `jti` (and optional `refresh_token` `jti`) in `revoked_tokens`.
  - Passing `{"revoke_all": true}` or changing/resetting a password increments `users.token_version`, immediately invalidating all prior active JWTs for that user.
- **Password Change & Verified Password Reset:**
  - `POST /api/auth/change-password` verifies `current_password`, hashes `new_password`, increments `token_version`, and returns fresh session tokens.
  - `POST /api/auth/password-reset/request` generates a `secrets.token_urlsafe(32)` token, stores only its SHA-256 hex digest in `password_reset_tokens` (15-minute expiry, single-use `used_at`), invalidates prior pending reset tokens for the account, and always returns a non-enumerating generic response. Without external `SMTP_HOST`, development builds write reset dispatches to `backend/dev_mail_outbox.log`.
  - `POST /api/auth/password-reset/confirm` validates the SHA-256 digest, checks expiry and `used_at`, updates the Argon2id hash, marks the reset token used, and bumps `token_version`.
- **Rate Limiting (`backend/app/core/rate_limiter.py`):** Thread-safe sliding-window HTTP `429` protection on `/api/auth/register`, `/api/auth/login`, `/api/auth/refresh`, `/api/auth/password-reset/request`, and `/api/auth/password-reset/confirm`.

---

## 2. Role-Based Access Control (RBAC)

Defined centrally in `backend/app/core/permissions.py` and enforced in `backend/app/dependencies/authorization.py`:

| Role | Intended Scope | Key Permissions |
| :--- | :--- | :--- |
| **`owner`** | Business workspace creator/owner | Full workspace administration (`business.*`, `members.manage_admins`, operational ERP, reports, onboarding) |
| **`admin`** | Delegated administrator | Operational ERP + member/role management (`manager`/`analyst`/`staff`/`supplier`), blocked from altering `owner` or managing admins |
| **`manager`** | Supply chain / inventory lead | Products, stock adjustments, suppliers, POs, sharing POs with suppliers, sales cancellation, reports |
| **`analyst`** | Forecasting & reporting analyst | Read-only catalog, inventory, sales, suppliers, POs, ML forecasts, reports |
| **`staff`** | Store / warehouse operator | Read catalog/inventory/POs, record sales, post PO goods receipts; blocked from creating products or stock adjustments |
| **`supplier`** | External supplier collaborator | Scoped exclusively to `supplier_portal.*`, `business.read`/`update`, and supplier onboarding; blocked (`403`) from buyer inventory, sales, analytics, and supplier directories |

---

## 3. Known Limitations

- Rate limiting is in-memory per API worker process (Redis-backed distributed counters would be needed for multi-instance horizontal scaling).
- Transactional email SMTP delivery uses a development maildrop (`backend/dev_mail_outbox.log`) when `SMTP_HOST` is not configured.
- Client-side SPA auth tokens are stored in `localStorage` for persistence across Vite/SPA reloads (`httpOnly` cookies would be preferred before public internet exposure).
