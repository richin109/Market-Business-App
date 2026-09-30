# Capability 3: Square Data Import (Direct API)

- [ ] **Capability complete** (all features below checked)

Bounded context: `mbs/sales/` (blueprint §3.1 #4, §8, §9.4). **Decision:** integrate directly against the Square API instead of the blueprint's original manual CSV-export workflow. Orders is the canonical sales/line-item source; Payments only supplements linked tender, refund, and fee data. This removes a manual step and keeps data fresher.

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
- [ ] For each order line in the selected history window, require a minimum Product Setup record for its Variation ID and an effective product cost for its sale date before accepting it; do not block unrelated resolvable lines because another line fails. This is an MVP 2 readiness subset, not the full MVP 3 recipe/costing UI.
- [ ] Require each Square Location ID to map to a Market ID or explicit non-market sales channel, and require a dated market visit for each market sale before accepting that line.
- [ ] Stage the selected order history, then provide a preflight report for missing variations, effective costs, location mappings, and dated visits. Accept passing lines and keep failures in the visible exception queue for correction and replay.
- [ ] Scheduled periodic sync via Celery-beat (e.g., every N hours) plus an on-demand "Sync Now" trigger.

## Feature 3.3 — Sales / Orders Sync
- [ ] Feature complete
- [ ] Run the readiness preflight from Feature 3.2 per order line. Accept passing lines while keeping failing lines in a visible `IMPORT_EXCEPTION` staging queue, outside accepted sales; after setup is corrected, replay idempotently.
- [ ] Integrate Square **Orders API** as the sole canonical source of sale line items and sales amounts (replacing the blueprint's CSV import): https://developer.squareup.com/reference/square/orders-api
- [ ] Use the **Payments API only as a supplement** joined to Orders by Square order/payment IDs for tender, refund, and actual processing-fee data; never create a second sales fact from a Payment.
- [ ] Land raw sales/order data into a staging table (`etl/landing/square_sales.py` equivalent).
- [ ] Normalize and idempotently upsert each order line using stable Square identity (`Order ID` + `Line Item UID`); retain Variation ID, quantity, sale timestamp, amounts/discounts/taxes, status, and source IDs. Do not include a sync-batch ID in the business dedup key.
- [ ] Incremental sync using persisted Square cursors/`updated_at`, with replay-safe upserts and reconciliation for updated, cancelled, refunded, or late-arriving orders; record the sync window and cursor in the import log.
- [ ] Square refunds/returns reverse financial sales amounts but never restock inventory automatically. Any returned/resalable quantity requires a separate audited manual stock adjustment linked to the refund/return.

## Feature 3.4 — Market Assignment & Fees
- [ ] Feature complete
- [ ] Assign each accepted sale during ingestion by Square Location ID and order date/time to the configured dated market visit or explicit non-market channel; no accepted sale may have an unresolved market/channel.
- [ ] Calculate and snapshot COGS during ingestion using the approved effective product cost as of sale date; orders missing cost readiness are held in the import exception queue. Later recipe-cost changes do not silently rewrite accepted sale snapshots; historical corrections require an audited adjustment/restate action.
- [ ] Attribute actual Square processing fees and refunds from the related Payment records to the canonical Orders; ensure each Payment/fee is applied once even when an order has multiple tenders or partial refunds.
- [ ] If actual fee data is unavailable, mark the amount as estimated using the effective-dated fee schedule (initial fallback: `(gross × square_fee_rate) + (transaction count × square_fee_fixed_amount)`, defaults 2.6% and $0.10); display estimates separately and never present them as actual fees. Confirm current account pricing: https://squareup.com/us/en/payments/pricing

## Feature 3.5 — Import Log & Governance
- [ ] Feature complete
- [ ] `tblImportLog` equivalent: every sync run records start/end time, source/cursor window, records created/updated/reconciled, duplicates, cancellations/refunds, actual-vs-estimated fees, retry count, errors, and final status.
- [ ] Enforce the MVP 2 preflight sequence: Catalog sync → minimum product/cost readiness + market/location/visit setup → Orders/Payments sync → downstream inventory, rankings, and dashboards.
- [ ] `POST /api/v1/sales/import` (or `/sync`) and related read endpoints per blueprint §9.4, adjusted for API-pull instead of file-upload semantics.
## Feature 3.6 — Manual Non-Square Sales
- [ ] Feature complete
- [ ] Accept a manual sale only when its Variation ID, effective product cost for the sale date, and market visit or explicit non-market channel resolve; otherwise keep it as an unposted correction/draft that does not affect reporting, inventory, or tax totals.
- [ ] Provide MANAGER+ create, review, and audited correction for cash and other non-Square sales, linked to an existing product Variation ID, sale date/time, market visit or explicit non-market channel, quantity, gross amount, discount, tax collected, tender type, and optional external reference.
- [ ] Record refunds/returns and corrections as linked, auditable events; do not overwrite the original sale. Require an idempotency key for imports/retries and prevent double entry against a Square Order.
- [ ] Refunds/returns never restock inventory automatically; record any physically returned/resalable quantity through a separate audited stock adjustment linked to the refund/return event.
- [ ] Use the same effective product-cost lookup and immutable accepted COGS snapshot policy as Square sales. Keep Square and manual source types distinct while exposing both through shared sales, dashboard, inventory, and tax queries.
- [ ] Provide `POST/GET /api/v1/sales/manual` and correction/refund endpoints with role checks, validation, source lineage, and audit history.
