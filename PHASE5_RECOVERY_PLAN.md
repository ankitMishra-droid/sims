# PHASE 5 RECOVERY & INTEGRATION PLAN
**Date:** 2026-11-27  
**Scope:** Root-cause Python/Pyrefly import repair, security hardening, multi-tenant/RBAC verification, onboarding CSV import preview/confirm, centralized API token refresh & auth expiry handling, frontend integration tests, and full-stack documentation deliverables.

---

## Prioritized Findings (Audit of Phases 1–5)

### P0 — Critical (Security, Package Resolution, Cross-Tenant Data Protection)
1. **Pyrefly & Python Package Discovery Failure (`tests/test_phase5_workspaces_auth.py`, `backend/app/*`):**
   - **Root Cause:** The FastAPI `app` package lives under `D:\sims\backend\app`, while tests run from workspace root `D:\sims`. Only `tests/conftest.py` patched `sys.path` dynamically at pytest runtime; 6 subpackages (`app`, `app.core`, `app.dependencies`, `app.routers`, `app.services`, `app.inventory`) lacked `__init__.py`; and no `pyproject.toml`, `.venv` `.pth`, or `.vscode/settings.json` configured `backend` as a source root.
   - **Resolution:** Added missing `__init__.py` files, added `pyproject.toml` (`[tool.pyrefly]` `search-path = ["backend"]` + `[tool.pytest.ini_options]` `pythonpath = ["backend"]`), added `.vscode/settings.json`, and registered `D:\sims\backend` in `.venv` via `sims_backend.pth`.
2. **Hardcoded Production Fallback Secret (`backend/app/core/security.py`):**
   - **Finding:** `SECRET_KEY = os.getenv("JWT_SECRET_KEY", "stocksangati-super-secret-jwt-key-2026-production")` embeds a hardcoded literal fallback.
   - **Action:** Load `.env` early in `security.py`; fail startup (`RuntimeError`) if `APP_ENV=production` lacks a real `JWT_SECRET_KEY`; in dev/test only, fall back to a process-generated `secrets.token_urlsafe(32)` if unset.
3. **Comprehensive Multi-Tenant Negative Test Coverage (`tests/test_phase5_workspaces_auth.py`):**
   - **Finding:** Existing tests verified product isolation and workspace switching, but did not yet assert cross-tenant denial across all endpoints (inventory positions, stock logs, sales read/cancel, purchase orders read/send/receive, dashboard reports, forecasts, unshared supplier PO details).
   - **Action:** Expand `tests/test_phase5_workspaces_auth.py` to test all Part 11.3 & 11.4 scenarios end-to-end.

### P1 — High (Frontend–Backend Coordination, Auth Refresh & Onboarding Import)
4. **Centralized API Client Refresh, Active Workspace Header & Auth Expiry Sync (`src/api.js`, `src/App.jsx`):**
   - **Finding:** Expired `access_token` clears `localStorage` in `api.js` without attempting `refresh_token` rotation or notifying Redux `authSlice`, potentially leaving `isAuthenticated: true` stale until reload.
   - **Action:** Implement single-flight automatic `/api/auth/refresh` retry on `401`, emit a custom `'stocksangati:auth-expired'` event handled in `App.jsx` to dispatch `logout()`, and forward `X-Business-Id` when active user business context is stored.
5. **Onboarding Product Import Preview–Validate–Confirm Workflow (`OnboardingWizardPage.jsx`):**
   - **Finding:** Step 6 currently supports manual entry only, without CSV upload/preview/validation/confirm.
   - **Action:** Add CSV upload, parse, preview table, validation (SKU, prices, duplicate detection against workspace SKUs), explicit confirmation step, and result summary in Step 6 without modifying stock silently.
6. **Frontend Automated Integration Tests (`frontend/.../package.json`):**
   - **Finding:** Frontend `package.json` only runs `lint` and `build`, with zero automated tests covering `api.js` token refresh/401 logout, Redux workspace-switch cache wipe, or `translations.js` EN/HI completeness.
   - **Action:** Add Node native test suite (`npm test`) covering `store`, `translations`, and `api` client behavior.

### P2 — Medium (Migrations Clarity & Type-Checker Hygiene)
7. **Migration Path Clarity (`backend/migrations/` vs `backend/app/db_migrate.py`):**
   - **Finding:** `backend/migrations/versions/` is empty; active upgrades run cleanly via `ensure_schema_and_backfill` in `db_migrate.py`.
   - **Action:** Document backup, safe upgrade, verification, and rollback procedures in `DATABASE_MIGRATION_REPORT.md` and keep `inventory.db` intact.
8. **Type-Check Cleanliness:**
   - Remove unnecessary `str()` conversions flagged in `backend/app/dependencies/authorization.py` and fix annotation default in `tests/test_phase3_core_workflows.py` without adding blanket ignore directives.

### P3 — Low (Workspace Hygiene)
9. **Temp Cleanup & Deliverables Consistency:**
   - Remove stale `.tmp` files (`fe_err.tmp`, `fe_out.tmp` removed) and generate complete Phase 5 documentation deliverables (`PHASE5_IMPLEMENTATION_REPORT.md`, `DATABASE_MIGRATION_REPORT.md`, updated `API_CONTRACTS.md`, `TEST_REPORT.md`).
