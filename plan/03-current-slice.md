# Current Implementation Slice

Status: **in progress — S1 through S9 receipt foundations are validated; final receipt lifecycle work remains pending**.

Evidence recorded 2026-09-30 (host, Python 3.12.10, uv-managed environment from `uv.lock`): `pytest` 50 passed; `ruff check src tests` passed; `mypy src tests` (strict) passed; HTTP `GET /health` returned `{"status":"ok"}` from uvicorn. Receipt tests cover normalization, raw OCR snapshots and metadata, upload validation, exact and canonical-ID deduplication, perceptual near-duplicate holds/resolution, in-memory retrieval, immutable review dispositions, audited corrections, Receipt_ID collision holds, remembered-rule matching, editable category rules, SQLAlchemy receipt persistence, OCR-free read APIs, and idempotent four-disposition approvals. S1 adds the synchronous SQLAlchemy model contract, Alembic baseline, six seeded settings, audit/error log tables, and a fresh-database migration test. S2 adds Argon2id users, revocable opaque cookie sessions, CSRF validation, role authorization, audited reset/recovery flows, bootstrap/recovery CLI commands, login throttling, and authenticated API tests. S3 adds protected local file storage with atomic writes, fail-closed ClamAV adapter behavior, injectable outbox events, SHA-256 deduplication, and an authenticated upload endpoint. S4 adds the provider-neutral local OCR boundary, lease-aware in-memory job store, retry/review outcomes, duplicate-safe receipt processing, and Celery task entry point. S5 adds Alembic receipt upload/header/item tables, immutable UUID keys, unique Receipt_ID enforcement, raw/canonical JSON persistence, and authenticated list/detail/items APIs. S6 adds Pillow/imagehash perceptual image fingerprints, thresholded near-match holds, and explicit manager resolution. S7 adds seeded editable category rules, database rule loading, and classifier wiring without replacing remembered-item rules. S8 adds Alembic correction holds, audited normalized corrections, immutable raw OCR preservation, canonical snapshot updates, and Receipt_ID collision protection. S9 adds Alembic line-approval records, four disposition-to-routing mappings, personal NO_POST handling, approval audit events, and idempotent retries. Docker Compose (2026-09-30, Docker Desktop 29.8.1, Compose v5.5.1): rebuilt web image; all 50 tests passed; in-container `ruff check src tests` and `mypy src tests` passed.

## Completed Task — S8 Receipt Review and Correction Persistence

Persist manager corrections without changing immutable receipt identity or raw OCR evidence. This remains local development work and is permitted under the conditional-go status in [the implementation-readiness gate](02-implementation-readiness.md). The mocked OCR boundary remains the development provider; real local OCR is a separate release-readiness requirement.

**Scope**
- Persist header and line-item corrections transactionally while leaving `raw_ocr_document` unchanged.
- Refresh the versioned `receipt_document` snapshot from corrected normalized rows and retain reviewer, timestamp, reason, and audit lineage.
- Detect a correction that would produce another receipt's `Receipt_ID`; hold it for explicit ADMIN resolution without changing `receipt_pk` or child links.
- Keep review and read paths OCR-free and preserve the existing merchandise-category and business-disposition rules.
- Exercise the persisted correction path with synthetic data; do not add real receipt files or live providers.

**Dependencies**
- The Python stack and local services are confirmed in [the implementation overview](00-overview.md) and [Capability 11](capabilities/11-deployment-infrastructure.md).
- Docker Desktop 29.8.1 with Compose v5.5.1 is installed and verified (U-1 done); the Compose stack is a validation environment, not a production approval.
- WSL 2 distribution Ubuntu 26.04 LTS is installed and default (verified 2026-09-30: `wsl -l -v` shows `* Ubuntu-26.04` VERSION 2; WSL 3.0.1.0), per Capability 11.1. Docker Desktop 29.8.1 with Compose v5.5.1 is installed and verified (U-1 done).
- No Square, Meta, or Google credentials, real receipts, or production infrastructure are required.

**Out of scope**
- Real Tesseract/OpenCV engine integration, Google Document AI calls, PDF page rendering, production malware scanning, real data, and production deployment.
- Any decision about market-specific timezone behavior, MVP 2 price/session allocation, or settlement state transitions.

**Acceptance evidence**
- Corrected normalized rows and the canonical snapshot remain consistent after persistence and reload.
- `raw_ocr_document` and `receipt_pk` remain unchanged after correction.
- A `Receipt_ID` collision is held for ADMIN resolution without overwriting either receipt.
- Focused correction/persistence tests, the full test suite, Ruff, and mypy complete successfully.
- No real receipt files, live providers, or real local OCR calls are used.

**Validation commands used for this slice**
- `uv run --frozen pytest tests/test_receipt_corrections.py tests/test_receipt_persistence.py -q`
- `uv run --frozen pytest`
- `uv run --frozen ruff check src tests`
- `uv run --frozen mypy src tests`

The foundation's Docker validation passed on 2026-09-30 (see evidence above).

The focused correction command is the S8 target validation. Record any command adjustment in the README and Copilot instructions when the slice is implemented.

## Owner Decisions Required Before Affected Work

These do not block the local foundation, but must be resolved and recorded before implementing the affected MVP 2 behavior.

| Decision | Clarification required | Affected plans |
|---|---|---|
| Timezone authority | Confirm whether each market has its own IANA timezone, or whether the configured business timezone is authoritative for operating-hour interpretation and business-date assignment. Preserve full-date historical attribution either way. | `00-overview.md`, Capabilities 5 and 14, MVP 2 |
| Market-session price and availability | Confirm the MVP 2 source of customer-facing price, the permitted scope of a session override, and the contract for reserving/committing/reversing/disposition of available quantity before full inventory ships. Keep Square order amounts authoritative for Square sales. | Capabilities 4, 14, and 16; MVP 2 |
| Sale and closeout states | Record one transition table distinguishing provider-staged/pending, accepted, import exception, operationally closed, and settlement-reconciled states, including which totals each state may affect. | Capabilities 3, 14, and 16; Capability 10 sales-mvp |
| Store registry and item mapping | Confirm D-37–D-40 in [the go/no-go sheet](04-go-no-go.md): store alias normalization and ambiguity holds, who may rename/group stores, the store product identifier used per source, common-name defaulting, and the effective-dated remap/restatement rule. | `00-overview.md`, Capabilities 1, 2, 4, 9, 15; MVP 1 |
| Square provider item bridge | Decide whether a synced Square Variation ID is also registered as a store item of a Square provider source for cost/stock traceability, or whether Square catalog identity stays outside the purchase-store registry and links only through the product's single Variation ID → `item_id` mapping. D-37 currently defines a store as a purchase source, so the bridge is not approved and must not be implemented by inference. | Capabilities 2.8, 3.2, 4.1; MVP 2/3 |

Do not choose these rules by inference. Ask the business owner and update the governing plan before coding them.

## S1 Evidence — SQLAlchemy/Alembic Baseline

- [x] Add synchronous SQLAlchemy base, session factory, and baseline models for `tbl_settings`, `tbl_audit_log`, and `tbl_error_log`.
- [x] Add reviewed Alembic revision `0001_baseline` with six synthetic settings and no `create_all()` schema path.
- [x] Link RT093 to `tests/test_database_baseline.py::test_baseline_migration_creates_seeded_settings_and_logs` in `plan/test-case-manifest.csv`.
- [x] Validate host and Compose checks: focused migration test, full host suite, Ruff, and mypy.

## S2 Evidence — Authentication Foundation

- [x] Add persistent users with Argon2id password hashes and role authorization for ADMIN, MANAGER, and VIEWER.
- [x] Add revocable opaque server sessions with two-hour idle and twelve-hour absolute expiry, plus CSRF token verification.
- [x] Add one-time admin password reset records and a local `bootstrap-admin` CLI with no default password.
- [x] Add login, current-user, logout, and admin user-list API routes with secure cookie flags and focused RM-014 coverage.
- [x] Add Alembic revision `0002_authentication` and validate the migration chain on host and in Compose.
- [x] Validate `29` host tests, Ruff, mypy, and the Compose S1/S2 focused tests, Ruff, and mypy.
- [x] Add D-11/D-13 login and reset rate limits, audited admin recovery/reset routes, local bootstrap/recovery commands, and abuse-control tests. The throttle is process-local for this development slice; a shared store is still required before multi-worker production deployment.

## S3 Evidence — Protected Receipt Upload Boundary

- [x] Extend receipt upload validation with protected local storage, atomic file promotion, and media-type-derived keys.
- [x] Add fail-closed scanner states: clean, infected, and unavailable (`SCAN_PENDING`); OCR does not run until a scan is clean.
- [x] Add injectable outbox publication after protected storage and preserve exact SHA-256 duplicate protection.
- [x] Add authenticated `POST /api/v1/receipts/upload` delegation with explicit invalid, duplicate, malware, and scanner-unavailable responses.
- [x] Link RM-003 to its implemented exact-deduplication test; leave RM-001 planned because PDF page and image-dimension limits remain unimplemented.
- [x] Validate 36 host tests, Ruff, mypy, and the full Compose test/lint/type suite.

## S4 Evidence — OCR Task Boundary

- [x] Add `LocalOCREngine` provider boundary with synthetic extractor injection and local provider/schema metadata defaults.
- [x] Add lease-aware job claims that block concurrent processing and permit reclaim after lease expiry.
- [x] Add idempotent OCR processing with retry, terminal review, and duplicate receipt-ID outcomes.
- [x] Add Celery task entry point delegating to the configured processor.
- [x] Validate four focused S4 tests, 40 host tests, Ruff, mypy, and the full Compose test/lint/type suite.
- [ ] Integrate real Tesseract/OpenCV binaries and persist job/receipt state in PostgreSQL; this remains follow-up work.

## S5 Evidence — Receipt Persistence and Read APIs

- [x] Add `tbl_receipt_uploads`, `tbl_receipts`, and `tbl_receipt_items` SQLAlchemy models with reviewed Alembic revision `0003_receipts`.
- [x] Preserve immutable source-derived Receipt_ID uniqueness, UUID receipt keys, raw OCR JSON, canonical receipt JSON, normalized line items, and protected file metadata.
- [x] Add transaction-ready persistence helpers and fresh-database round-trip/unique-constraint tests.
- [x] Add authenticated list/detail/items APIs with store/date filters, pagination, soft-delete visibility, and line-based item counts.
- [x] Link RM-007 to the OCR-free persisted read API test.
- [x] Validate 43 host tests, Ruff, mypy, and the full Compose test/lint/type suite.

## After This Slice

## S6 Evidence — Perceptual Duplicate Review

- [x] Add injectable Pillow/imagehash perceptual fingerprints for synthetic image pages without hardcoded receipt files.
- [x] Hold thresholded near matches as `POSSIBLE_DUPLICATE` before OCR and retain the pending source by SHA-256.
- [x] Add explicit resolution for “already imported” versus “process as new,” preserving Receipt_ID deduplication.
- [x] Link RM-004 to the generated-image near-duplicate test.
- [x] Validate 45 host tests, Ruff, mypy, and the full Compose test/lint/type suite.
- [ ] Add PDF page rendering and persistent perceptual fingerprint records; keep this deferred until the page-renderer/storage boundary is approved.

## After This Slice

## S7 Evidence — Editable Category Rules

- [x] Add `tbl_category_rules` with seeded Blueprint 6.5 keywords through Alembic revision `0004_category_rules`.
- [x] Load enabled database rules into normalization while preserving the existing remembered-item rule module.
- [x] Prove a database-edited keyword changes merchandise classification without hardcoded receipt files.
- [x] Link RM-018 to the focused editable-rule test.
- [x] Validate 46 host tests, Ruff, mypy, and the full Compose test/lint/type suite.

## After This Slice

## S8 Evidence — Review and Correction Persistence

- [x] Persist corrected receipt header and line-item rows in one transaction while preserving immutable raw OCR JSON and `receipt_pk`.
- [x] Rebuild the canonical `receipt_document` snapshot from corrected normalized rows with reviewer audit metadata.
- [x] Hold `Receipt_ID` collisions for ADMIN resolution without overwriting either receipt or re-keying relationships.
- [x] Link RM-008 and RM-013 to focused correction/persistence tests in `plan/test-case-manifest.csv`.
- [x] Validate the focused S8 tests, 48-test host suite, Ruff, mypy, and equivalent Compose checks.

## After This Slice

## S9 Evidence — Idempotent Disposition Approval

- [x] Add `tbl_receipt_line_approvals` through Alembic revision `0006_line_approvals` with one approval per receipt line and unique source event.
- [x] Route Personal/Non-business to `NO_POST`; route the three business dispositions to their thin posting kinds.
- [x] Add approval audit events and make repeated approvals idempotent while rejecting disposition changes.
- [x] Link RM-011 to the focused four-disposition approval test.
- [x] Validate 50 host tests, Ruff, mypy, and the full Compose test/lint/type suite.

## After This Slice

Next unchecked step: implement S10 thin ingredient-purchase, ordinary-expense, capital-asset, and minimal ingredient/recipe records behind the approval routing boundary. Real Tesseract/OpenCV integration, database-backed job state, PDF page rendering, and production malware scanning remain explicit follow-up work; real-data OCR remains blocked until the readiness approvals are complete.

Queued after S10: side-by-side receipt review page with package count × pack size × pack unit capture and the minimal unit/alias catalog (Capabilities 2.5 and 2.6; RM-021). Cross-dimension conversions remain MVP 3 (Capability 4.9; CO-001). Item and recipe imagery (S17; IM-001, IM-002) depends on that review page and on the S14–S16 store/item identity work, because a confirmed candidate image attaches to a store item and its canonical item.

## Queued Store & Item Identity Work — ST-001/ST-002, IT-001/IT-002

- [ ] Implement S14 canonical store registry, minimum scope (Capabilities 1.2/1.4 and 2.1/2.7; D-37): `tbl_stores` and `tbl_store_aliases`, automatic store/alias creation from the store value read on each imported order/receipt, exact normalized-key matching with holds for missing, unreadable, or multiply-matching values, a store list with display-name editing and a confirmation warning on duplicate names, canonical `store_id` filtering on receipt reads, and a reviewed migration that adds `tbl_receipts.store_id` as nullable, backfills stores/aliases from existing normalized `store` text, then enforces non-null. Keep the store component of `Receipt_ID` on the normalized printed text. Validate with `uv run --frozen pytest tests/test_store_registry.py -q`, fresh/upgrade/downgrade migration tests, `ruff`, `mypy`, and the full suite. Use synthetic orders only.
- [ ] Implement S15 purchased-item identity, minimum scope (Capabilities 1.2/1.4 and 2.1/2.5/2.8; D-38, D-39): `tbl_store_items` uniquely keyed by `store_id` + `store_product_id`, `tbl_items` canonical identity, many-to-one mapping enforcing one item per store item and the last-store-item rule for store-observed items, user-entered common names on items and store items with display defaulting to the order description, blocked posting for unmapped store items, remembered item rules re-keyed to the store item, and a reviewed migration that adds nullable `store_item`/`item_id` to `tbl_receipt_items`, backfills lines that carry a merchant item number, and flags identifier-less legacy lines as mapping holds. Validate with `uv run --frozen pytest tests/test_item_identity.py -q`, fresh/upgrade/downgrade migration tests, `ruff`, `mypy`, and the full suite.
- [ ] Implement S16 store and item administration (Capabilities 2.7/2.8; D-37, D-40): audited store merge that re-points aliases and receipts, forward-only split leaving posted records on their resolved `store_id` until an audited restatement, the item mapping screen with ranked confirmation-required suggestions bounded by `item_mapping_suggestion_limit`, move/split operations, and effective-dated remap restatement. Include Playwright desktop/mobile coverage for both screens. Validate with `uv run --frozen pytest tests/test_store_registry.py tests/test_item_mapping.py -q`, `ruff`, `mypy`, and the full suite.
- [ ] Leave all three unchecked until D-37–D-40 are recorded as approved in [the go/no-go sheet](04-go-no-go.md) and the implementation, migrations, browser coverage, and manifest evidence exist in the repository.

## Queued Receipt Source Work — RM-022

- [ ] After S10, implement multi-PDF receipt association and review using synthetic source files: one full scan, an overlapping copy, and a supplementary partial scan whose repeated product line is a distinct purchase occurrence. Keep one `receipt_pk`, immutable per-file OCR evidence, audited copy/supplement decisions, and source/page/line provenance. Reconcile the reviewed combined item lines to the printed item subtotal with tax separate; hold conflicts instead of guessing. Capabilities 1.2-1.4 and 2.1/2.5 own this change; the current single-upload FK and duplicate-ID rejection need a reviewed Alembic migration and service/API changes.
- [ ] Validate RM-022 with `uv run --frozen pytest tests/receipts/test_receipt_mvp.py -k test_rm_022 -q`, a fresh/upgrade migration test, `uv run --frozen ruff check src tests`, `uv run --frozen mypy src tests`, and `uv run --frozen pytest`. Leave this unchecked until the feature, synthetic browser/API coverage, and readiness approvals exist; no real receipts are permitted as fixtures under the conditional-go gate.
- [ ] Validate RM-023's synthetic image-only/text-layer OCR and field-evidence review with `uv run --frozen pytest tests/receipts/test_receipt_mvp.py -k test_rm_023 -q` plus the `receipt-mvp` browser profile. Verify package size versus weighed lb/count, merchant item number versus UPC, printed REF/TR#/timestamps, visible versus masked payment suffix, and subtotal/tax separation; do not treat the private real-receipt review files as automated test fixtures.
- [ ] After the real-data gate approves local use, validate RM-024 with `uv run --frozen pytest tests/receipts/test_private_receipt_corpus.py -k test_rm_024 -q` against the private `receipts/` directory and reviewed expectations. Require a tracked-file/checksum preflight, isolated local execution, per-file and combined-order reconciliation, approved OCR thresholds, and redacted aggregate release evidence. Leave unchecked while authorization, reviewed ground truth, or the test harness is missing; never run it in CI or expose identifiable output.
- [ ] Implement and validate RM-025 before claiming directory upload is replay-safe: repeat an unchanged synthetic directory, then reselect it after one multi-order image changes from five to ten to fifteen complete orders. Validate `uv run --frozen pytest tests/receipts/test_receipt_mvp.py -k test_rm_025 -q` plus fresh/upgrade migration, near-match resolution, concurrency/retry, and browser per-file/per-order status checks. Expect exactly five additional receipts per changed version, zero additions on unchanged or old-version reruns, stable prior IDs/approved postings, and visible holds for ambiguous identities. Keep unchecked until the extraction boundary can segment multiple orders from one image.

## Queued Item & Recipe Imagery Work — IM-001/IM-002

- [ ] Implement S17 media-asset store and item imagery (Capabilities 1.6, 2.9, and 4.10; D-41, D-42, D-43): `tbl_media_assets` keyed by SHA-256 content key plus `tbl_media_asset_links` with a partial unique index enforcing one active primary per owner, both through a reviewed Alembic migration. Add one ingest service that verifies file signatures, scans fail-closed, enforces `image_allowed_media_types`/`image_max_bytes`/`image_max_dimension_px`, strips EXIF, derives a thumbnail, and deduplicates by SHA-256 then perceptual hash. Extract embedded per-line product images during OCR with file/page/region provenance, excluding logos, barcodes, images below `receipt_image_min_dimension_px`, and the receipt page itself, and create them as PENDING candidates. Add reviewer confirm/reject on the side-by-side review page and MANAGER+ upload, mobile capture, reorder, primary change, and display-only detach on items and store items, with VIEWER read-only and full audit. Serve bytes and thumbnails under the receipt's authentication, role, and soft-delete rules.
- [ ] Validate S17 with `uv run --frozen pytest tests/test_item_images.py -q`, a fresh-database and prior-revision upgrade migration test, the `receipt-mvp` Playwright gallery coverage, `uv run --frozen ruff check src tests`, `uv run --frozen mypy src tests`, and `uv run --frozen pytest`. Use synthetic source documents only; no real receipts and no live providers.
- [ ] Ship the provider-neutral `ImageGenerationEngine` boundary and its deterministic stub with `image_generation_enabled` seeded to `No`, and prove no provider call occurs from any entry point while it is disabled. Leave live recipe generation (IM-004) unchecked until D-44 is approved and U-8 is complete; product, ingredient, supply, and recipe galleries land with MVP 3 slice 3.2a (IM-003).
- [ ] Leave this work unchecked until D-41, D-42, and D-43 are recorded as approved in [the go/no-go sheet](04-go-no-go.md) and the implementation, migration, browser coverage, and manifest evidence exist in the repository.

## Future MVP Queue

After MVP 1 is released, activate one row at a time from [mvp-slice-specifications.md](mvp-slice-specifications.md). Do not implement MVP 2-8 from the roadmap prose alone. Copy the selected row here with its owner decisions, dependencies, manifest IDs, focused test names, and validation commands before coding.