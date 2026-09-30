# Capability 3: Square Platform Integration

- [ ] **Capability complete** (all features below checked)

Bounded context: `src/mbs/integrations/square/` (blueprint §8, §9.4). Owns Square credentials, Catalog/Orders/Payments API access, raw staging, cursor management, and provider sync logs. Accepted Square sales facts, manual sales, COGS, and market assignment belong to Capability 14.

## Feature 3.1 — Square Account & API Access 🧑‍💻 User Input Required
- [ ] Feature complete
- [ ] 🧑‍💻 Confirm you have (or create) a Square seller account with the products/items you sell already in the Square Dashboard: https://squareup.com/dashboard
- [ ] 🧑‍💻 Create a Square Developer account and application: https://developer.squareup.com/apps
- [ ] 🧑‍💻 Decide sandbox vs. production: build and test against the **Sandbox** environment first (Square provides sandbox test data), then switch to production credentials for go-live. Sandbox guide: https://developer.squareup.com/docs/testing/sandbox
- [ ] 🧑‍💻 Generate an **Access Token** for the application (OAuth or Personal Access Token, per your preference) from the app's Credentials page: https://developer.squareup.com/apps → select app → Credentials.
- [ ] 🧑‍💻 Note your **Location ID(s)** (each market/register may be its own Location in Square) via the Locations API or Dashboard → Account & Settings → Locations.
- [ ] 🧑‍💻 Review Square's API rate limits and terms before wiring up scheduled polling: https://developer.squareup.com/docs/build-basics/rate-limiting
- [ ] Store the access token and location ID(s) as secrets; never commit to source control.

## Feature 3.2 — Catalog Sync
- [ ] Feature complete
- [ ] Integrate Square **Catalog API** (`/v2/catalog/list` / `SearchCatalogObjects`) to pull items and variations: https://developer.squareup.com/reference/square/catalog-api
- [ ] Land raw catalog objects into a staging table (`etl/landing/square_catalog.py` equivalent), unvalidated.
- [ ] Normalize into Variation IDs + Item IDs (`etl/staging/catalog_staging.py` equivalent) — Variation ID is the permanent product key everywhere downstream (Governance Rule 1).
- [ ] Scheduled periodic sync via Celery-beat (e.g., every N hours) plus an on-demand "Sync Now" trigger.

## Feature 3.3 — Sales / Orders Sync
- [ ] Feature complete
- [ ] Integrate Square **Orders API** as the source of Square sale line items and amounts (replacing the blueprint's CSV import); Capability 14 decides which staged lines become canonical sales: https://developer.squareup.com/reference/square/orders-api
- [ ] Land raw sales/order data into a staging table (`etl/landing/square_sales.py` equivalent).
- [ ] Stage raw order data and stable Square identity (`Order ID` + `Line Item UID`) for the Capability 14 sales service; retain Variation ID, quantity, sale timestamp, amounts/discounts/taxes, status, and source IDs. Do not use a sync-batch ID as the source identity.
- [ ] Incremental sync using persisted Square cursors/`updated_at`, with replay-safe upserts and reconciliation for updated, cancelled, refunded, or late-arriving orders; record the sync window and cursor in the import log.
- [ ] Persist each fetched page into durable staging before advancing its cursor; restarting a run replays staged pages safely and cannot skip data after a crash.

## Feature 3.4 — Payments Sync
- [ ] Feature complete
- [ ] Fetch Payments only as a supplement to Orders and land raw payment/tender/refund/fee responses in provider staging. Capability 14 owns payment-to-sale attribution and fee reconciliation; a Payment never creates a sale fact.

## Feature 3.5 — Import Log & Governance
- [ ] Feature complete
- [ ] `tblImportLog` equivalent records provider API runs, source/cursor window, pages and records staged, retry counts, duplicates, provider errors, and final status. Sales acceptance and exception resolution are logged by Capability 14.
- [ ] Provide `POST /api/v1/integrations/square/sync` and sync-status/read endpoints with ADMIN/MANAGER authorization per the source API requirements.
