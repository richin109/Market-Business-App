# Capability 9: Settings & Governance

Database support: PostgreSQL only; follow [D-77's shared contract](../00-overview.md#postgresql-contract-all-stages).
- [ ] Test catalog NULL/defaults and audited concurrent changes, session expiry/revocation, safe URL configuration, least-privilege runtime/migration roles, and UTC/timezone boundaries.

- [ ] **Capability complete** (all features below checked)

Bounded context: `mbs/governance/` + `tbl_settings` (blueprint §7, §12). Configuration store and the non-negotiable rules enforced at the application layer.

## Feature 9.1 — Settings Store
- [ ] Feature complete
- [ ] **Settings catalog defaults (authoritative for seed and RT093).** Every listed key must exist exactly once. `NULL` means intentionally unset; no empty strings are allowed.

| Key | Default |
|---|---|
| `business_timezone` | `America/New_York` |
| `cost_review_threshold_days` | `90` |
| `currency` | `USD` |
| `expiry_scan_interval_minutes` | `240` |
| `image_allowed_media_types` | `image/jpeg,image/png,application/pdf` |
| `image_max_bytes` | `10000000` |
| `image_max_dimension_px` | `10000` |
| `item_mapping_suggestion_limit` | `10` |
| `low_stock_alert_min_shelf_life_days` | `30` |
| `low_stock_threshold_pct` | `20` |
| `market_ranking_min_visits` | `5` |
| `mileage_rate` | `0.67` |
| `ocr_engine` | `tesseract-opencv` |
| `phash_duplicate_threshold` | `6` |
| `receipt_image_extraction_enabled` | `No` |
| `receipt_image_min_dimension_px` | `100` |
| `receipt_raw_retention_days` | `NULL` |
| `receipt_source_retention_days` | `NULL` |
| `safety_stock_pct` | `20` |
| `session_idle_timeout_minutes` | `120` |
| `square_fee_fixed_amount` | `0.10` |
| `square_fee_rate` | `0.026` |
| `store_alias_normalization_version` | `casefold-trim-whitespace-punctuation-store-number-v1` |
| `tax_year` | `2026` |
| `testing_mode` | `No` |
| `week_starts_on` | `Monday` |
| `weekly_profit_goal` | `300.00` |
| `backup_destination_reference` | `NULL` |
| `backup_retention_period_days` | `NULL` |
| `backup_encryption_key_owner` | `NULL` |
| `backup_restore_test_owner` | `NULL` |
- [x] `tbl_settings` key-value table seeded with the documented Capability 9.1 catalog. The Blueprint §7 list is reference material only; this written plan controls.
- [ ] Keep `week_starts_on` locked to Monday in MVP 1–8 per D-33 (period starts Monday 00:00, close Monday 03:00 local). Do not accept another day through settings/API until an owner-approved migration and closed-period restatement rule exist.
- [ ] Include `session_idle_timeout_minutes` in the settings catalog with a default of 120 minutes and validated safe bounds. This setting controls idle expiration only; it cannot extend the fixed 12-hour absolute session lifetime (D-14).
- [ ] Store identity and item mapping are master data, not settings. Settings hold only the matching controls: `store_alias_normalization_version` (the casefold/trim/whitespace/punctuation/store-number rule set applied to alias keys) and `item_mapping_suggestion_limit` (maximum ranked suggestions shown). Matching itself is exact on the normalized alias key; no setting may enable automatic fuzzy store grouping or automatic description-based item merging.
- [ ] Shelf Life is item master data, not a setting: store `shelf_life_value` + `shelf_life_unit` (`days`, `weeks`, `months`, `never`) per product, ingredient, and supply, and the output shelf life per recipe. Settings only govern the expiry scan cadence and low-stock alert eligibility; there is no global default shelf life and the system never substitutes one.
- [ ] Keep effective-dated history for `mileage_rate`, `square_fee_rate`, and `square_fee_fixed_amount`; apply the schedule effective on the transaction/market date so a current setting change cannot rewrite historical profit. The reorder engine uses the explicit ingredient-level Safety Stock Quantity in the workbook. Retain `safety_stock_pct` only for source-workbook compatibility; it has no calculation effect until an owner-approved conversion is specified.
- [ ] Settings API (read for VIEWER+, write for ADMIN) — changes apply immediately, no service restart.
- [ ] Provide ADMIN-only backup settings for the destination reference, retention period, encryption-key owner, and restore-test owner. Never store encryption keys or secret credentials in `tbl_settings`; validate the destination before enabling real-data backup.
- [ ] Document the four keys retained under D-65 in this catalog: `currency` (the single operating currency asserted in the overview scope assumptions, while per-record currency identifiers stay on the records), `tax_year`, `receipt_source_retention_days`, and `receipt_raw_retention_days`. Represent unset values as `NULL`, never an empty string, so an unanswered retention period is distinguishable from a configured zero; the retention keys stay `NULL` and no automatic purge runs until U-3 supplies them (D-15). `tax_year` is a screen default that pre-selects a year in tax workpapers and reporting; it never decides which records belong to a tax year, which is always derived from each record's own business date, so a stale value cannot misfile data. Market calendar and holiday exceptions are Capability 5 per-market dated master data, not settings.
- [x] Reconcile the seeded baseline through Alembic revision 0012: rename `week_start`, seed the documented catalog, preserve D-65 keys, represent unset values as `NULL`, and use the DB-backed settings reader at application startup. RT093 derives keys/defaults from this catalog and checks NULL and undocumented-key behavior without a literal count.
- [ ] Imagery settings (D-41–D-44, approved 2026-09-30): `image_allowed_media_types`, `image_max_bytes`, `image_max_dimension_px`, `receipt_image_min_dimension_px`, and `receipt_image_extraction_enabled`. Thumbnail (320 px box) and display (1024 px) sizes are fixed by D-41, not settings. There is no image-generation setting (D-44). Move the near-duplicate threshold (D-08, currently the constant `DEFAULT_PHASH_THRESHOLD = 6`) into this store as `phash_duplicate_threshold`.
- [ ] Changing a non-historical calculation setting (for example, cost review threshold) re-derives affected current outputs; effective-dated rates apply prospectively and do not rewrite historical results.

## Feature 9.2 — Governance Rule Enforcement
- [ ] Feature complete
- [ ] Rule 1 — Product Key Rule: Variation ID only for sellable products, enforced at the model/service layer, not just UI.
- [ ] Rule 1a — Store Identity Rule: every purchase, cost, and expense references a canonical `store_id`. Stores and aliases are created only by the import/store service from source order data, one normalized alias resolves by exact key to exactly one canonical store, and display names and groupings are presentation data that cannot re-key `Receipt_ID` or rewrite raw source text. An audited merge re-points aliases and receipts; a split is forward-only and leaves posted records on the `store_id` resolved at posting time until an audited restatement moves them.
- [ ] Rule 1b — Purchased-Item Identity Rule: a purchased line is keyed by canonical store + store product identifier and resolved to exactly one canonical `item_id`. A store-observed canonical item never loses its last store item; a setup-created item may have none until its first purchase. Square variations identify sellable products: recipe-made outputs link to effective recipes with canonical input items, while direct resale may link to one canonical purchased item (D-52). Descriptions/common names never identify or auto-merge items, and an unmapped purchased store item blocks posting.
- [ ] Rule 1c — Imagery Rule (D-41–D-44): images are display-only and never identity, match, amount, or posting inputs; a missing image never blocks a workflow and shows the default placeholder; all image bytes enter through the one media-asset service; replacing a confirmed primary requires an explicit Yes (default No); MBS never generates images.
- [ ] Rule 2 — Market Master Immutability: enforced via service layer that blocks UPDATE on historical rows, only allows end-date + insert.
- [ ] Rule 3 — Test Record Isolation: isolate fixtures in test-only databases where practical and enforce production query filters excluding `Test Record = Yes` from every aggregation/dashboard/report; add tests proving test rows cannot leak into production results.
- [ ] Rule 4 — Required Refresh Sequence: Catalog sync → per-line product/cost and market/location/dated-visit readiness → accept passing Orders lines and stage exceptions → downstream inventory/COGS/rankings → dashboards → testing. A failing line does not block other passing lines; later approved purchase, expense, market, and production changes trigger downstream recalculation in dependency order.
- [ ] Rule 5 — Deduplication: upsert Square order lines by stable Square Order ID + Line Item UID; deduplicate receipts by the Receipt_ID composite key; make both paths replay-safe and auditable.
- [ ] For receipts under Rule 5, distinguish exact-file duplicates, near-match holds, overlapping same-order copies, and reviewed supplemental files. Enforce one canonical receipt per accepted order plus unique accepted line-occurrence/source decisions; a matching merchant item number alone neither merges nor creates an additional purchase. Audit each accept/hold/reject decision and prevent unreviewed evidence from triggering business postings (RM-022).
- [ ] Apply Rule 5 independently at file-content and order-identity levels on each confirmed directory run: unchanged bytes reuse the existing upload; changed versions of an image may hold old and new orders, so resolve any near-match hold and compare each extracted order under database uniqueness before accepting only new identities. A second concurrent or historical-version run cannot add receipts, approved lines, or postings again; report unresolved identities rather than silently treating the file as all old (RM-025).
- [ ] Rule 7 — Cost Review: flags per Capability 4.4.
- [ ] Rule 8 — Spoilage Logic: enforced per Capability 6.2. Every stocked item has explicit Shelf Life, and remaining unsold lots expire once at `Perishable By`. Only an effective recipe version may elect earlier end-of-plan waste for its unsold produced output; an item with no recipe follows only its own Shelf Life. Never waste sold units or dispose of the same remainder twice (D-54).

## Feature 9.3 — Error Logging
- [ ] Feature complete
- [ ] **Not started:** the error-log table exists, but there is no centralized writer and no OCR, upload, or import failure path currently writes to it. This remains a release gap outside R7.
- [ ] Central error log table capturing ETL/import/governance rule violations with severity, timestamp, and source module — feeds the Release Gate (Capability 10). The table exists from evidence S1 but has no writer; this remains explicitly not started until at least OCR, upload, and import failure paths write to it.

## Feature 9.4 — Authentication & User Lifecycle
- [ ] Feature complete
- [ ] Create persistent users and revocable login sessions; hash passwords with Argon2id and never log or return password material.
- [ ] Browser pages and same-origin HTMX/JSON requests use an opaque server-side session ID in a `Secure`, `HttpOnly`, `SameSite=Lax` cookie; require CSRF tokens on state-changing cookie-authenticated requests.
- [ ] Machine/API bearer JWTs, if enabled, have configured short expiry, issuer/audience checks, key rotation, and revocation through persisted session/token IDs; use the same user/role authorization service as browser sessions.
- [ ] Provide login, logout/revoke-all, current-user, admin user/role management, and password-reset flows. Rate-limit login/reset attempts and audit authentication, role, and destructive actions.
- [ ] First-admin creation and recovery use the one-time local bootstrap/recovery procedure in Capability 11; no default credentials or public self-registration.
- [ ] Test expired/revoked sessions, JWT expiry/claims/revocation, CSRF failures, rate limiting, role authorization on both UI and API routes, and bootstrap/recovery controls.
