# Market Business System (MBS) v3.3 — Implementation Plan

Source of truth: [Python MBS v3.3 + Receipt OCR Blueprint.docx](Python%20MBS%20v3.3%20+%20Receipt%20OCR%20Blueprint.docx) plus supporting references in [support/](../support/). This is a **planning document only** — no application code is implemented here.

## How to use this plan
- Each capability below has its own file under `plan/capabilities/`. Check the box at the top of a capability file only when **all** its features are checked.
- Each feature has its own checkbox. Check it only when all its implementation steps are checked.
- Steps marked **🧑‍💻 User Input Required** cannot be completed by the coding agent alone — they need an account, credential, purchase decision, or physical machine access from you. Each such step spells out exactly what to do, including links.
- Capability numbers identify functional areas; deploy in the staged order defined by [01-mvp-roadmap.md](01-mvp-roadmap.md), not by capability number alone.

## Key Decisions (confirmed with user)
| Decision | Choice |
|---|---|
| OCR / AI engine | **Google Document AI Expense Parser** is the Receipt MVP provider. The app stores the full response and normalized data so upload is the only normal OCR call; listing, review, search, and export use saved data. Reprocessing is explicit and may incur another page charge. **Tesseract + OpenCV** remains an optional local provider. See [01-receipt-capture-ocr.md](capabilities/01-receipt-capture-ocr.md). |
| Square integration | **Square Orders API is the canonical source for sales and line items**; Payments API supplements it with tender, refund, and actual fee data where available. Catalog API supplies variation identity. No manual CSV export/import step. See [03-square-data-import.md](capabilities/03-square-data-import.md). |
| Business workflow coverage | The application replaces the full workbook workflow, including weekly market attendance, production, sales, ingredient purchases, expenses, inventory, and reporting. Square Orders are canonical for Square sales; manually entered cash and other non-Square sales share the same reporting/tax source layer with distinct provenance. OCR receipts can propose purchase/expense records, but a user reviews and approves them; equivalent manual entry is always available and writes to the same records. |
| Tax reporting scope | Current federal profile is a sole proprietorship; generate a source-linked, Schedule C-aligned preparation document and supporting schedules for use with the owner's Form 1040 workflow, plus applicable Florida business-tax workpapers. Do not generate/sign/file the Form 1040 or calculate final personal tax liability. See [12-tax-filing-support.md](capabilities/12-tax-filing-support.md). |
| UI | Web-based only, **Python-native stack**: FastAPI + Jinja2 templates + HTMX + Alpine.js + Tailwind CSS (CDN). No Node.js build pipeline, no separate frontend service/repo. The original blueprint's React/TypeScript frontend was inherited from a prior Java-based implementation and is dropped in favor of a stack that matches the Python backend — fewer moving parts, one language, one deployable service. Charts (KPI dashboards) render via Chart.js or Plotly, embedded directly in server-rendered pages, no bundler required. No desktop/mobile app. |
| Dev environment | This laptop, via Docker Compose (Postgres, Redis, FastAPI+Jinja2/HTMX web app, Celery). |
| Production environment | Self-hosted **Proxmox VM** running Docker Compose + Caddy (reverse proxy/TLS) + scheduled backups. Kubernetes from the original blueprint is dropped as over-scaled for this workload; can be revisited later if usage grows. See [11-deployment-infrastructure.md](capabilities/11-deployment-infrastructure.md). |

## Python Implementation Baseline
- Minimum Python version: 3.12. Declare runtime and dependency constraints in `pyproject.toml`; commit a reproducible dependency lock file.
- Use FastAPI, Pydantic 2, SQLAlchemy 2 synchronous sessions with Psycopg 3, Alembic, Celery, and pytest. Keep request handlers using the synchronous DB session model and give each request/task its own session and transaction.
- Run Ruff and mypy in CI; share Pydantic/API schemas without importing ORM models into templates. Pin external Square, Google, and Meta SDK/API versions and record supported versions.
- Organize the application as `src/mbs/` with bounded-context services, SQLAlchemy models, Pydantic schemas, FastAPI routers, Celery tasks, and provider adapters kept in separate modules. APIs and workers call the same domain services; templates never access the database directly.

## Capabilities

- [ ] 1. [Receipt Capture & OCR Pipeline](capabilities/01-receipt-capture-ocr.md) — first deployable slice: Google OCR, review, deduplication, and database storage
- [ ] 2. [Receipts Management](capabilities/02-receipts-management.md) — storage, listing, retrieval, soft-delete, audit trail
- [ ] 3. [Square Data Import (Direct API)](capabilities/03-square-data-import.md) — catalog and Square sales ingestion, manual non-Square sales, dedup, market assignment
- [ ] 4. [Product, Recipe & Costing Management](capabilities/04-product-recipe-costing.md) — product master, recipes, ingredient costs, cost engine
- [ ] 5. [Markets & Weekly Entry](capabilities/05-markets-weekly-entry.md) — market master, dated visits, travel, production, expenses, and market shopping/prep lists
- [ ] 6. [Inventory Engine](capabilities/06-inventory-engine.md) — weekly snapshots, spoilage, carry-forward, reorder points
- [ ] 7. [Rankings & Forecasting](capabilities/07-rankings-forecasting.md) — market/product rankings, opportunity engine, rolling forecasts
- [ ] 8. [Dashboards & KPIs](capabilities/08-dashboards-kpis.md) — operations dashboard, executive dashboard, scorecards
- [ ] 9. [Settings & Governance](capabilities/09-settings-governance.md) — configuration store, refresh sequence enforcement, governance rules
- [ ] 10. [Testing & Release Framework](capabilities/10-testing-release.md) — 110 regression tests, release certification gate
- [ ] 11. [Deployment & Infrastructure](capabilities/11-deployment-infrastructure.md) — dev laptop setup now, Proxmox VM production later
- [ ] 12. [Tax Information & Filing Support](capabilities/12-tax-filing-support.md) — tax-year, entity-aware federal and Florida business-tax workpapers and exports
- [ ] 13. [WhatsApp Business Messaging](capabilities/13-whatsapp-messaging.md) — consent-checked outbound Cloud API messages and delivery tracking

## Delivery Sequence
Use [01-mvp-roadmap.md](01-mvp-roadmap.md) for the confirmed sequence: Receipts → Square → Products/Recipes → Shopping/WhatsApp → Markets, followed by Inventory, Reporting, and Tax/Full Release.

## Cross-cutting rules (apply to every capability)
- Auth: server-side browser sessions use `Secure`, `HttpOnly`, `SameSite=Lax` cookies plus CSRF protection on state-changing HTML/HTMX requests. JSON API bearer JWTs are short-lived; login, logout/revocation, password reset, first-admin bootstrap, and role checks share one user/authorization service. Never store auth tokens in browser local storage.
- Product identity: always key by Square **Variation ID**, never by product name alone.
- Test isolation: rows with `Test Record = Yes` must never appear in production aggregations/dashboards/reports.
- MVP 2 sales activation requires Catalog sync plus minimum product/cost and market/location/dated-visit setup; accept passing order lines and keep unresolved lines outside the accepted ledger. Thereafter, business-record and product/market updates feed inventory/COGS and rankings, then dashboards and testing. Receipt upload/OCR/storage remains the independent MVP 1 release. Tax workpapers use approved records and retain source lineage and a year-specific snapshot.
- Domain writes use database transactions and unique source-event/idempotency constraints. A receipt approval posts its linked business record atomically; a production confirmation commits its production event, stock movements, and fractional-waste remainder atomically. External provider calls use persisted workflow states and reconciliation; do not claim an external API side effect is exactly-once.
