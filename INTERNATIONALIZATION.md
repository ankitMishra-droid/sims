# INTERNATIONALIZATION & REGIONAL LANGUAGE ARCHITECTURE
## Smart Inventory Management System (SIMS / StockSangati)
**Updated:** 2026-11-27 (Phase 5)

---

## 1. Dictionary & Precedence Design

- **Frontend Dictionary (`src/i18n/translations.js`):** Centralized `DICTIONARIES` + `translate(language, path, fallback)` + `useTranslation()` hook (`src/hooks/useTranslation.js`) with automatic English fallback.
- **Active Fully Translated Languages:**
  - `en` — English (`ltr`)
  - `hi` — Hindi / हिन्दी (`ltr`, using natural business terminology keeping clear codes like `SKU` and `PO` with localized explanations)
- **Registered Upcoming Regional Languages (Persist Preference + English Fallback):**
  - `bho` (Bhojpuri), `ur` (Urdu — `dir: 'rtl'`), `bn` (Bengali), `mr` (Marathi), `gu` (Gujarati), `pa` (Punjabi), `ta` (Tamil), `te` (Telugu), `kn` (Kannada), `ml` (Malayalam).
- **Precedence:** User `User.preferred_language` overrides workspace `Business.default_language` for personal interface rendering and syncs via `PATCH /api/auth/me` and `localStorage` without interrupting the active page or logging out.

---

## 2. RTL Readiness & Honest Limitations

- `src/App.jsx` applies `dir={getLanguageDirection(language)}` (`rtl` for Urdu `ur`, `ltr` otherwise) and `lang={language}` to `<html>`.
- **Limitation:** End-to-end visual verification has been completed for LTR (`en` and `hi`). Complete RTL layout testing across all DataTables, Modals, Sidebar drawers, and Chart tooltips remains pending before claiming full RTL production readiness.
