# Capability 3: Square Platform Integration

- [ ] **Capability complete** (all features below checked)

Bounded context: `src/mbs/integrations/square/` (blueprint §8, §9.4). Owns Square credentials, Catalog/Orders/Payments API access, raw staging, cursor management, and provider sync logs. Accepted Square sales facts, COGS, and market assignment belong to Capability 14. The Square app/POS outside MBS captures every actual sale.

Square's separate app/POS captures all payments outside MBS. MVP 2 imports Catalog only; this integration begins Orders/Payments staging in MVP 3 and never initiates checkout or creates a separate sales system. D-16 data attribution is approved. Once sales activation begins, a missing provider identity or ambiguous visit match remains an import exception rather than an invented local sale.

**Blocking Square API gate:** MBS must never create, update, delete, cancel, refund, or otherwise attempt to change any data in Square. This applies to every app path, background job, admin action, retry, and test using a Square connection. All Square access goes through one provider adapter with an explicit allowlist of approved read-only API operations; reject unknown or mutating operations locally before any network request. HTTP `POST` is permitted only for documented read-only search operations on that allowlist (for example, Orders/Catalog search), never as a general write permission. The app's own `POST /api/v1/integrations/square/sync` starts a local read/import job and does not authorize a provider write. Changes to Square data are made only outside MBS in Square's own tools.

## Feature 3.1 — Square Account & API Access 🧑‍💻 User Input Required
- [ ] Feature complete
- [ ] 🧑‍💻 Confirm you have (or create) a Square seller account with the products/items you sell already in the Square Dashboard: https://squareup.com/dashboard
- [ ] 🧑‍💻 Create a Square Developer account and application: https://developer.squareup.com/apps
- [ ] 🧑‍💻 Decide whether to enable optional Sandbox validation before live activation. Local development and recorded-fixture tests do not require a sandbox account (U-4); live Catalog activation requires the read-only credential scope review and Catalog sync evidence in `costing-mvp`, while Orders/Payments activation adds `sales-mvp` evidence. Sandbox guide: https://developer.squareup.com/docs/testing/sandbox
- [ ] 🧑‍💻 Provision Square credentials with only the read permissions needed for Catalog, Orders, Payments, and Locations; prefer scoped OAuth credentials. Do not activate production sync with a broad Personal Access Token or any credential carrying Square write permissions. Record the granted permission set at activation and fail closed if it exceeds the approved read-only set.
- [ ] 🧑‍💻 Note your **Location ID(s)** (each market/register may be its own Location in Square) via the Locations API or Dashboard → Account & Settings → Locations.
- [ ] 🧑‍💻 Review Square's API rate limits and terms before wiring up scheduled polling: https://developer.squareup.com/docs/build-basics/rate-limiting
- [ ] Store the access token and location ID(s) as secrets; never commit to source control.
- [ ] Implement one Square adapter/transport that allowlists only the specific read-only provider operations needed by this capability. Refuse calls to write-capable endpoints and unknown operations before the HTTP client runs, including when invoked by sync retries, admin endpoints, or future features; do not expose a generic Square SDK/client to other services.
- [ ] Add mocked transport tests proving Catalog, Orders, Payments, and Location reads (including approved POST-based searches) succeed, while create/update/delete/cancel/refund requests and unrecognized endpoints fail locally with zero outbound requests. Treat a regression as blocking for `costing-mvp` Catalog activation and every later Square release, including `sales-mvp`.

## Feature 3.2 — Catalog Sync
- [ ] Feature complete
- [ ] Integrate Square **Catalog API** (`/v2/catalog/list` / `SearchCatalogObjects`) to pull items and variations: https://developer.squareup.com/reference/square/catalog-api
- [ ] Land raw catalog objects into a staging table (`etl/landing/square_catalog.py` equivalent), unvalidated.
- [ ] Normalize into Variation IDs + Item IDs (`etl/staging/catalog_staging.py` equivalent) — Variation ID is the permanent product key everywhere downstream (Governance Rule 1).
- [ ] Keep raw catalog staging separate from product creation: product setup requires an explicitly confirmed Shelf Life before persistence. A Variation ID is not a purchase store item; its recipe or direct-resale canonical-item sourcing is completed later under D-52. An incomplete catalog row stays staged with a visible setup exception and no invented default Shelf Life.
- [ ] MVP 2 Catalog sync runs only through an authorized `Sync Catalog Now` trigger; it uses the same read-only adapter, cursor, idempotency, retry, and audit behavior as later scheduled sync. Market-end scheduling, 24-hour retries, Orders/Payments staging, and provider-state settlement visibility begin in Feature 3.3/MVP 3 (D-69).

## Feature 3.3 — Sales / Orders Sync
- [ ] Feature complete
- [ ] In MVP 3, schedule the first Orders/Payments sync 30 minutes after each market ends, then repeat every 24 hours while late or unresolved provider data remains; provide an authorized on-demand `Sync Now` trigger. Scheduled and manual runs share the same read-only adapter, cursor, idempotency, retry, and audit behavior.
- [ ] Integrate Square **Orders API** as the source of Square sale line items and amounts (replacing the blueprint's CSV import); Capability 14 decides which staged lines become canonical sales: https://developer.squareup.com/reference/square/orders-api
- [ ] Land raw sales/order data into a staging table (`etl/landing/square_sales.py` equivalent).
- [ ] Stage raw order data and stable Square identity (`Order ID` + `Line Item UID`) for the Capability 14 sales service; retain Variation ID, quantity, sale timestamp, amounts/discounts/taxes, status, and source IDs. Do not use a sync-batch ID as the source identity.
- [ ] Incremental sync using persisted Square cursors/`updated_at`, with replay-safe upserts and reconciliation for updated, cancelled, refunded, or late-arriving orders; record the sync window and cursor in the import log.
- [ ] Persist each fetched page into durable staging before advancing its cursor; restarting a run replays staged pages safely and cannot skip data after a crash.
- [ ] Retain provider Order ID, Location ID, timestamps, any available device/reference metadata, and the import watermark needed to correlate Orders with market visits/sessions; test delayed Orders, two sessions sharing a Location/date, and orders that cannot be matched without guessing.

## Feature 3.4 — Payments Sync
- [ ] Feature complete
- [ ] Fetch Payments only as a supplement to Orders and land raw payment/tender/refund/fee responses in provider staging. Capability 14 owns payment-to-sale attribution and fee reconciliation; a Payment never creates a sale fact.

## Feature 3.5 — Import Log & Governance
- [ ] Feature complete
- [ ] `tblImportLog` equivalent records provider API runs, source/cursor window, pages and records staged, retry counts, duplicates, provider errors, and final status. Sales acceptance and exception resolution are logged by Capability 14.
- [ ] Provide `POST /api/v1/integrations/square/sync` and sync-status/read endpoints with ADMIN/MANAGER authorization per the source API requirements.
