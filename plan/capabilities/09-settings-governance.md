# Capability 9: Settings & Governance

Database: PostgreSQL only; see [D-77](../00-overview.md#postgresql-contract-all-stages).
- [ ] Test catalog NULL/defaults, audited concurrent updates, session expiry/revocation, URL config, role least privilege, UTC/timezones.

- [ ] **Capability complete** (all features below checked)

Bounded context: `mbs/governance/`, `tbl_settings` (blueprint §7/12). Owns configuration and application-layer governance rules.

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
- [ ] Store/item identities are master data. Settings only configure alias normalization version and suggestion limit; alias matching stays exact. No setting enables fuzzy auto-grouping or description-based merging.
- [ ] Shelf Life belongs to each product/ingredient/supply and recipe output, not settings. Settings govern scan cadence/alert eligibility only; no global default or substitution.
- [ ] Keep effective-dated history for `mileage_rate`, `square_fee_rate`, and `square_fee_fixed_amount`; apply the schedule effective on the transaction/market date so a current setting change cannot rewrite historical profit. The reorder engine uses the explicit ingredient-level Safety Stock Quantity in the workbook. Retain `safety_stock_pct` only for source-workbook compatibility; it has no calculation effect until an owner-approved conversion is specified.
- [ ] Settings API (read for VIEWER+, write for ADMIN) — changes apply immediately, no service restart.
- [ ] Provide ADMIN-only backup settings for the destination reference, retention period, encryption-key owner, and restore-test owner. Never store encryption keys or secret credentials in `tbl_settings`; validate the destination before enabling real-data backup.
- [ ] Keep D-65 catalog keys: `currency`, `tax_year`, `receipt_source_retention_days`, `receipt_raw_retention_days`. Unset=`NULL`, never empty; retention stays NULL/no auto-purge until U-3 (D-15). Currency is USD default; records retain currency IDs. `tax_year` is a screen default only; derive tax year from each record's business date. Market calendars/holidays are Capability 5 dated data, not settings.
- [x] Reconcile the seeded baseline through Alembic revision 0012: rename `week_start`, seed the documented catalog, preserve D-65 keys, represent unset values as `NULL`, and use the DB-backed settings reader at application startup. RT093 derives keys/defaults from this catalog and checks NULL and undocumented-key behavior without a literal count.
- [ ] Imagery settings (D-41–44): media types, max bytes/dimension, minimum receipt-image dimension, extraction enablement. D-41 fixes 320px thumbnail/1024px display; no generation setting (D-44). Store D-08 threshold (`6`) as `phash_duplicate_threshold`.
- [ ] Changing a non-historical calculation setting (for example, cost review threshold) re-derives affected current outputs; effective-dated rates apply prospectively and do not rewrite historical results.

## Feature 9.2 — Governance Rule Enforcement
- [ ] Feature complete
- [ ] Rule 1 — Product key: enforce Variation ID for sellable products in model/service, not UI alone.
- [ ] Rule 1a — Store identity: purchases/costs/expenses use canonical `store_id`. Import/store service creates stores/aliases from source; normalized alias matches exact to one store. Names/grouping never change `Receipt_ID` or raw text. Audited merge re-points aliases/receipts; split is forward-only; posted records retain posting-time store until audited restatement.
- [ ] Rule 1b — Purchased identity: canonical store + store product ID → one `item_id`. Store-observed items retain a store item; setup items may start without one. Square variations use effective recipes or one direct-resale canonical item (D-52). Names/descriptions never identify/auto-merge; unmapped items cannot post.
- [ ] Rule 1c — Imagery (D-41–44): display-only; never identity/match/amount/posting input. Missing uses placeholder and never blocks. Use one media service. Replacing primary requires explicit Yes (default No). Never generate images.
- [ ] Rule 2 — Market Master Immutability: enforced via service layer that blocks UPDATE on historical rows, only allows end-date + insert.
- [ ] Rule 3 — Test Record Isolation: isolate fixtures in test-only databases where practical and enforce production query filters excluding `Test Record = Yes` from every aggregation/dashboard/report; add tests proving test rows cannot leak into production results.
- [ ] Rule 4 — Refresh order: Catalog → per-line product/cost/market readiness → accept passing Orders, stage exceptions → inventory/COGS/rankings → dashboards → tests. One failing line does not block valid lines; later approved changes recalculate downstream in order.
- [ ] Rule 5 — Dedup: upsert by Square `Order ID + Line Item UID`; dedup receipts by composite `Receipt_ID`; both replay-safe/audited.
- [ ] For receipts under Rule 5, distinguish exact-file duplicates, near-match holds, overlapping same-order copies, and reviewed supplemental files. Enforce one canonical receipt per accepted order plus unique accepted line-occurrence/source decisions; a matching merchant item number alone neither merges nor creates an additional purchase. Audit each accept/hold/reject decision and prevent unreviewed evidence from triggering business postings (RM-022).
- [ ] Apply Rule 5 independently at file-content and order-identity levels on each confirmed directory run: unchanged bytes reuse the existing upload; changed versions of an image may hold old and new orders, so resolve any near-match hold and compare each extracted order under database uniqueness before accepting only new identities. A second concurrent or historical-version run cannot add receipts, approved lines, or postings again; report unresolved identities rather than silently treating the file as all old (RM-025).
- [ ] Rule 7 — Cost Review: flags per Capability 4.4.
- [ ] Rule 8 — Spoilage Logic: enforced per Capability 6.2. Every stocked item has explicit Shelf Life, and remaining unsold lots expire once at `Perishable By`. Only an effective recipe version may elect earlier end-of-plan waste for its unsold produced output; an item with no recipe follows only its own Shelf Life. Never waste sold units or dispose of the same remainder twice (D-54).

## Feature 9.3 — Error Logging
- [ ] Feature complete
- [ ] Capability 9 owns the centralized operational-error taxonomy and writer for `tbl_error_log`; domain capabilities report sanitized operational failures through it. Keep expected business holds/exceptions in their owning workflow and user/security actions in `AuditLog`; do not duplicate those as unclassified errors.
- [ ] Record severity, stable error code, source context, correlation/source-event ID when available, UTC timestamp, and retryability. Redact credentials, tokens, receipt values, and unnecessary personal data. Logging failure must not turn a committed business event into a retry that duplicates it.
- [ ] Wire at least upload, OCR worker, and provider-import failure paths through the shared writer in the Receipt MVP implementation sequence. Add a real-entry-point test for each, including retry/idempotency and sensitive-field redaction; make these assertions part of `receipt-mvp` and the later provider profiles.

## Feature 9.4 — Authentication & User Lifecycle
- [ ] Feature complete
- [ ] Create persistent users and revocable login sessions; hash passwords with Argon2id and never log or return password material.
- [ ] Browser pages and same-origin HTMX/JSON requests use an opaque server-side session ID in a `Secure`, `HttpOnly`, `SameSite=Lax` cookie; require CSRF tokens on state-changing cookie-authenticated requests.
- [ ] Machine/API bearer JWTs, if enabled, have configured short expiry, issuer/audience checks, key rotation, and revocation through persisted session/token IDs; use the same user/role authorization service as browser sessions.
- [ ] Provide login, logout/revoke-all, current-user, admin user/role management, and password-reset flows. Rate-limit login/reset attempts and audit authentication, role, and destructive actions.
- [ ] First-admin creation and recovery use the one-time local bootstrap/recovery procedure in Capability 11; no default credentials or public self-registration.
- [ ] Test expired/revoked sessions, JWT expiry/claims/revocation, CSRF failures, rate limiting, role authorization on both UI and API routes, and bootstrap/recovery controls.
