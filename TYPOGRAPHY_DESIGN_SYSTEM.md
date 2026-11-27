# SIMS Typography & Multilingual Font Design System

## 1. Objectives & Design Principles

The StockSangati (SIMS) typography system establishes a unified, accessible, multilingual typographic hierarchy tailored for SaaS inventory, procurement, and forecasting workflows without introducing extra framework dependencies.

Key principles:
1. **Single Primary UI Voice:** Replaced the split `Plus Jakarta Sans` + `Inter` setup with `Inter` across Latin UI surfaces for uniform visual cadence across sidebars, tables, forms, KPIs, and charts.
2. **Script-Aware Multilingual Typography:** Eagerly load `Noto Sans Devanagari` alongside `Inter` and bind CSS `:root[lang="..."]` variables for all 12 supported languages in `src/i18n/translations.js` (`en`, `hi`, `bho`, `mr`, `bn`, `gu`, `pa`, `ta`, `te`, `kn`, `ml`, `ur`).
3. **Disciplined Weight Hierarchy:** Normalized excessive `700`/`800` weights down to `400` (regular), `500` (medium), and `600` (semibold).
4. **Devanagari & Indic Readability:** Disabled negative letter spacing (`-0.02em`/`-0.03em`) and forced `text-transform: uppercase` on non-English locales (`:root:not([lang="en"])`), while increasing line heights (`1.38` headings, `1.65` body) to prevent matra and shirorekha clipping.
5. **Tabular Numerals for ERP Data:** Applied `font-variant-numeric: tabular-nums` on KPI values, `.erp-table td.numeric`, and chart summary metrics instead of forcing monospace on numeric table columns.

---

## 2. Font Stacks & Loading Strategy

### `index.html` Web Font Preconnect & Imports

Loaded via Google Fonts (`display=swap`, WOFF2):
- `Inter` weights `400`, `500`, `600`
- `Noto Sans Devanagari` weights `400`, `500`, `600`
- `JetBrains Mono` weights `400`, `500`, `600`

`Plus Jakarta Sans`, `Inter:300`, and `Inter:700`/`800` were removed to reduce font payload and enforce consistent weights.

### CSS Script Font Variables (`src/index.css`)

| Token | Font Stack |
|---|---|
| `--font-family-latin` | `'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif` |
| `--font-family-devanagari` | `'Inter', 'Noto Sans Devanagari', 'Nirmala UI', 'Kohinoor Devanagari', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif` |
| `--font-family-bengali` | `'Inter', 'Noto Sans Bengali', 'Nirmala UI', 'Kohinoor Bangla', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif` |
| `--font-family-gujarati` | `'Inter', 'Noto Sans Gujarati', 'Nirmala UI', 'Kohinoor Gujarati', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif` |
| `--font-family-gurmukhi` | `'Inter', 'Noto Sans Gurmukhi', 'Nirmala UI', 'Raavi', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif` |
| `--font-family-tamil` | `'Inter', 'Noto Sans Tamil', 'Nirmala UI', 'Latha', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif` |
| `--font-family-telugu` | `'Inter', 'Noto Sans Telugu', 'Nirmala UI', 'Gautami', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif` |
| `--font-family-kannada` | `'Inter', 'Noto Sans Kannada', 'Nirmala UI', 'Tunga', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif` |
| `--font-family-malayalam` | `'Inter', 'Noto Sans Malayalam', 'Nirmala UI', 'Kartika', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif` |
| `--font-family-urdu` | `'Inter', 'Noto Nastaliq Urdu', 'Noto Sans Arabic', 'Tahoma', -apple-system, sans-serif` |
| `--font-sans` | `var(--font-family-devanagari)` (default so mixed Latin/Devanagari content always renders cleanly) |
| `--font-heading` | `var(--font-sans)` |
| `--font-mono` | `'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace` |

Keeping `'Inter'` ahead of `'Noto Sans Devanagari'` ensures Latin SKUs, digits, currency formatting, and English identifiers render in `Inter` while Devanagari codepoints seamlessly render in `Noto Sans Devanagari`.

---

## 3. Type Scale, Weights, Line Heights & Tracking

| Token | Value | Usage |
|---|---|---|
| `--text-xs` | `0.75rem` (`12px`) | Table headers (`th`), KPI labels, badges, sidebar group headers, form hints |
| `--text-sm` | `0.8125rem` (`13px`) | Form labels, nav tabs, compact toast messages, small buttons |
| `--text-base` | `0.875rem` (`14px`) | Body default, table cells, form inputs, sidebar links, page subtitles, buttons |
| `--text-md` | `0.9375rem` (`15px`) | Chart card headers, recommendation card titles, `--btn-lg` |
| `--text-lg` | `1.0625rem` (`17px`) | Section card titles, auth/brand header wordmark, donut center metric |
| `--text-xl` | `1.25rem` (`20px`) | Top navbar wordmark, mobile `page-header-title`, secondary stats |
| `--text-2xl` | `1.5rem` (`24px`) | Desktop `page-header-title`, `auth-title`, primary `.kpi-value` |
| `--text-3xl` | `2rem` (`32px`) | Display / hero headings |
| `--font-weight-regular` | `400` | Body copy, table cells, descriptions |
| `--font-weight-medium` | `500` | Sidebar links, nav tabs, form labels, buttons, badges |
| `--font-weight-semibold` | `600` | Headings (`h1`–`h6`), KPI values, active nav links, table headers |
| `--leading-tight` | `1.25` (`1.38` Indic, `1.55` Urdu) | Headings, KPI numbers |
| `--leading-snug` | `1.375` (`1.5` Indic, `1.7` Urdu) | Form inputs, labels, table rows, badges, buttons |
| `--leading-normal` | `1.5` (`1.65` Indic, `1.85` Urdu) | Body copy, descriptions, subtitles |
| `--leading-relaxed` | `1.625` (`1.75` Devanagari) | Long-form prose |
| `--tracking-tight` | `-0.015em` (`0em` non-EN) | Latin headings and KPI values |
| `--tracking-normal` | `0em` | Body and multilingual UI |
| `--tracking-wide` | `0.04em` (`0em` non-EN) | Uppercase Latin table/KPI/sidebar headers |

---

## 4. Responsive Typography Rules

At `@media (max-width: 960px)`:
- `.page-header-title` scales from `1.5rem` (`24px`) down to `var(--text-xl)` (`1.25rem` / `20px`).
- `.kpi-value` scales from `1.5rem` (`24px`) down to `1.35rem` (`21.6px`).
- `.table-responsive` enables horizontal scroll for dense ERP tables so mobile viewports maintain zero page-level horizontal overflow.
