# MVP Slice Specifications

This document makes MVP 2-8 executable by an AI coding agent. It does not approve owner decisions, credentials, live providers, or production promotion. Each row is one bounded implementation slice; an agent may implement only a row whose prerequisites and owner decisions are satisfied.

## Slice Contract

Every slice must satisfy all of these rules before its checkbox is checked:

- **Scope:** implement only the named bounded context and its listed interfaces.
- **Dependencies:** confirm the preceding migration, service contract, owner decisions, and test fixtures exist.
- **Acceptance:** add focused unit/integration tests using synthetic data or provider mocks; add Playwright tests for changed browser UI.
- **Receipt-derived acceptance:** when a slice consumes approved receipt lines, first prove its accounting, stock, and reporting effects with committed synthetic fixtures. Include an RM-025 changed-image replay where five existing orders remain stable while later versions add five at a time: only newly approved line occurrences may create cost, inventory, expense, dashboard, or tax facts. After the real-data gate authorizes RM-024, also run a separate isolated local evaluation against the private `receipts/` corpus for that slice's affected boundary, but only for entries with human-reviewed dispositions, units/conversions, expected postings, and applicable business/tax mappings. Missing annotations remain review holds, not passing facts. Keep the original files, expectations, and identifiable logs out of git/CI; carry only approved redacted aggregate evidence into the profile.
- **Traceability:** link applicable manifest IDs or add a focused test name to `03-current-slice.md`; planned manifest rows are not evidence.
- **Schema:** add SQLAlchemy models and a reviewed Alembic migration for every schema change; test a fresh database and an upgrade from the prior revision.
- **Validation:** run the focused test first, then `uv run --frozen ruff check src tests`, `uv run --frozen mypy src tests`, and `uv run --frozen pytest`. Run the same profile inside the pinned Compose candidate when the slice changes deployment or release behavior.
- **Stop conditions:** stop for an unapproved D-decision, missing user-only action, missing source contract, unresolved fixture conflict, failed migration, or a test failure that cannot be diagnosed locally. Do not infer business policy.
- **Evidence:** record the actual command, result, commit/image digest where applicable, and remaining unchecked work beside the slice in `03-current-slice.md`.

## MVP 2 — Sales Activation and Market-Day Selling

Owner decisions required before the first slice: D-01, D-02, D-03, D-04, D-05, D-12, D-16, D-17, D-18, and D-19. U-4 is required only for sandbox-provider tests; all unit tests use recorded fixtures or mocks.

| Slice | Bounded outcome | Acceptance and traceability |
|---|---|---|
| 2.1 | Read-only Square adapter and credential gate | Allowlisted Catalog/Orders/Payments/Location reads, approved POST searches, and zero outbound calls for forbidden operations from sync, retry, and admin paths. Link SQ-001. |
| 2.2 | Catalog staging and market prerequisites | Durable raw staging, Variation ID normalization, cursor/audit records, effective product-cost records, Market IDs, Location mappings, dated visits, and operating-hour validation. Test full-date, overlap, closed-date, timezone, and DST boundaries. |
| 2.3 | Orders staging and per-line acceptance | Persist each page before advancing cursors; replay safely; accept only lines with product/cost/market resolution; retain unresolved lines as exceptions. Test partial batches, late orders, updates, refunds, and duplicate `Order ID + Line Item UID`. |
| 2.4 | Manual sales and payment reconciliation | Add audited manual sales with event idempotency, linked corrections/refunds, payment joins, actual-versus-estimated fees, and no payment-created sale facts. Test cross-source deduplication and immutable cost/market snapshots. |
| 2.5 | Market-day session and closeout | Add HELPER permissions, session transitions from D-03, tender controls, cash over/short review, allocation reservation/commit/release/disposition, and operational-close versus settlement-reconciled views. Test browser refresh, repeated submissions, concurrent allocation, close exceptions, and unsupported offline mode. |

**MVP 2 profile:** `sales-mvp` runs 2.1-2.5 against a clean database and an upgrade path, includes SQ-001, Playwright mobile/desktop coverage, the approved targets from D-05, and zero unresolved release-blocking exceptions.

## MVP 3 — Products, Recipes, and Costing

Prerequisites: MVP 2 accepted Variation IDs and market identity; approve D-20, D-26, D-27, D-28, D-29, D-30, D-31, and D-35.

| Slice | Bounded outcome | Acceptance and traceability |
|---|---|---|
| 3.1 | Units, product master, and readiness status | Extend the MVP 1 unit/alias catalog into the approved unit/dimension registry with same-dimension global factors and effective-dated per-item conversions (Capability 4.9; CO-001), Decimal precision, Variation ID product records linked to their canonical `item_id` and existing store-item mappings, product status rules, required per-item Shelf Life (`days`/`weeks`/`months`/`never`) remembered as the item default, target stock, and customer-facing fields. Test that an item without a shelf life cannot be stocked and that legacy `is_perishable` values migrate per D-20. Cover SL-001, RT051-RT060, and RT070 with isolated fixtures. |
| 3.2 | Recipes, supplies, and cost engine | Add recipe/product/ingredient/supply mappings, compatible conversions, a mandatory recipe output shelf life (`never` permitted) that overrides the product's own shelf life for produced lots, waste percentages and fractional remainder behavior, effective-dated ingredient/product costs, preferred sources, and REVIEW COST status. Cover SL-002, RT061-RT069, and boundary tests. |
| 3.2a | Catalog imagery | D-41–D-44 approved 2026-09-30; starts after S17 has shipped. Add product, ingredient, supply, and recipe galleries over the S17 media-asset service with owner → canonical item → default placeholder resolution, D-41 sizes, and the D-42 replace prompt (default No). Build no image-generation component (D-44). Cover IM-003 and IM-004 with `uv run --frozen pytest tests/test_catalog_images.py -q`. |
| 3.3 | Purchases, receipt links, migration, and opening counts | Route manual/OCR purchases through one approval service keyed by accepted receipt-line occurrence, not PDF or merchant item number; resolve every purchase to a canonical `store_id` and canonical `item_id` from the MVP 1 registries rather than typed store/item text, and block posting for an unmapped store item; preserve every linked source/page and personal-line exclusion across MVP 1 migration. Normalize package count × pack size × pack unit to the item base unit (blocking lines with no conversion path), write one stock movement and cost-history row per approved line with conversion versions, replay MVP 1 links without duplication, and apply D-31 opening-count semantics. Test supplemental repeated-product lines, overlapping copies, rollback, late movements, and source lineage (RM-022; CO-001). |

**MVP 3 profile:** `costing-mvp` proves migration replay/rollback, unit and rounding rules, purchase parity, recipe waste accumulation, and opening-balance reconciliation before release.

## MVP 4 — Shopping, Prep, and WhatsApp

Prerequisites: MVP 3 stock inputs and D-17/D-32 balance contract. Meta calls remain mocked or use a test WABA until U-5 and the messaging approval record are complete.

| Slice | Bounded outcome | Acceptance and traceability |
|---|---|---|
| 4.1 | Shared stock reader and production service | Implement one `StockBalanceReader`, one production-event identity, atomic movement posting, retry/concurrency/rollback behavior, and no stock effect for unconfirmed plans. Test allocation is not subtracted twice. |
| 4.2 | Market load and store-grouped shopping | Calculate recipe/supply requirements, expected waste, as-of balance subtraction, grouping by canonical store from the MVP 1 registry so grouped alias spellings produce one list, shelf-life-derived `Perishable By` and expired-lot exclusion, copy-previous behavior, print/export, and explicit purchase posting. Match an OCR-approved receipt-line purchase to an existing shopping-list item instead of posting another manual purchase; never use a held PDF or unreviewed weight/size as stock. Test missing recipes, missing shelf life, incompatible units, supplemental/replayed lines, and no-plan-side-effects (SL-003; RM-022). |
| 4.3 | WhatsApp manual batches | Implement consent-aware recipient/template validation, minimum-two manual recipients, private per-recipient messages, cost threshold, idempotent attempts, webhook status handling, and print fallback. Test all sends with Meta mocks; no real recipients in CI. |

**MVP 4 profile:** `prep-mvp` covers 4.1-4.3, Playwright list/confirmation/send flows, and the approved balance, atomicity, consent, and messaging evidence.

## MVP 5 — Markets and Weekly Operations

Prerequisites: MVP 2 visit identity and MVP 4 shared production service. Approve D-18 and D-22 before implementation.

| Slice | Bounded outcome | Acceptance and traceability |
|---|---|---|
| 5.1 | Market costs, visits, and attendance | Add immutable effective-dated market costs, attendance vocabulary, visit replay identity, closed/exception dates, and history. Cover RT071-RT074 and RT077-RT082. |
| 5.2 | Directed route legs and allocations | Add reusable directed legs, Home/direct itinerary selection, effective mileage rates, audited overrides, and exact allocation summing to trip cost. Cover RT075-RT076 and route boundary tests. |
| 5.3 | Weekly production, expenses, and assets | Extend the shared production service with corrections, samples, expense provenance by accepted receipt-line occurrence and source page, receipt/manual parity, personal/mixed-use exclusion, capital-asset drafts, and unallocated-expense reporting. Test retries, supplemental-source replay, corrections, and no duplicate COGS/expense posting (RM-022). |

**MVP 5 profile:** `markets-mvp` proves visit migration, route allocation, production corrections, expense idempotency, asset routing, and responsive weekly-entry workflows.

## MVP 6 — Inventory and Reorder

Prerequisites: accepted sales, approved purchases, production movements, and D-20/D-21/D-33/D-35/D-36 approval.

| Slice | Bounded outcome | Acceptance and traceability |
|---|---|---|
| 6.1 | Movement ledgers and weekly snapshots | Implement signed product/ingredient/supply movements keyed to approved receipt-line occurrences for purchases (not source file), period snapshots, test-record exclusion, and reconciliation to source events. Include repeated-product supplements, overlapping-copy exclusion, and late approved-line restatements; cover RM-022, RT026-RT035, RT043, and RT048-RT050. |
| 6.2 | Expiry, spoilage, close, and restatement | Implement per-lot `Perishable By` derivation, the startup plus interval expiry job, carry-forward of unexpired and `never` stock, immutable closes, late-event restatements, shelf-life-change recomputation, and idempotent rebuilds. Test DST, month-end, and subsecond boundaries, stopped-system catch-up, and overlapping runs without double waste. Cover SL-003 and SL-004. |
| 6.3 | Reorder and low-stock alerts | Implement explicit safety-stock quantity, unit-consistent reorder calculations, last-source recommendations, 20% threshold crossing/re-arm, consent/template checks, and alert eligibility limited to `never` or shelf life at or above `low_stock_alert_min_shelf_life_days`. Test WhatsApp with mocks and cover SL-004. |

**MVP 6 profile:** `inventory-mvp` proves all stock classes reconcile through close/restatement, reorder outputs match approved formulas, and alert events are idempotent and consent-checked.

## MVP 7 — Analytics, Dashboards, and Forecasting

Prerequisites: MVP 6 snapshots and D-23, D-24, D-25, D-26, and D-27 approval. The 110 source cases are not complete until each has an application fixture and result.

| Slice | Bounded outcome | Acceptance and traceability |
|---|---|---|
| 7.1 | Refresh runs, watermarks, and lineage | Add refresh-run identity, dependency ordering, source watermarks, atomic publication, stale/failed states, drill-through lineage, and test-record filters. For receipt-derived costs and expenses count accepted canonical orders/lines rather than PDFs; expose all source evidence without multiplying KPI totals. Implement application equivalents for structural/meta cases RT001-RT025, RT036-RT042, RT065-RT068, RT083-RT085, RT087-RT088, and RT108-RT109 (RM-022). |
| 7.2 | Scorecards, rankings, opportunity, and forecasts | Implement approved product lifecycle, market ranks, manager-entered opportunity inputs, deterministic tie-breaks, forecast history rules, and D-27 fixed as-of behavior. Cover RT013-RT021, RT051-RT070, and RT083-RT088. |
| 7.3 | Operations/executive dashboards and release evidence | Add responsive dashboard pages/charts, health score, KPI source drill-through, six-control reporting, and all remaining workbook application equivalents including RT091-RT110. Structural cases become behavior/schema/config assertions, never formula-presence checks. |

**MVP 7 profile:** `analytics-mvp` runs all 110 application-equivalent cases, reports behavioral/configuration/meta coverage separately, and refuses mixed-state dashboard publication.

## MVP 8 — Tax Workpapers and Full Release

Prerequisites: all preceding profiles pass; U-6 and U-7; approved tax-year mappings and provider coverage certificate.

| Slice | Bounded outcome | Acceptance and traceability |
|---|---|---|
| 8.1 | Tax profile and effective mappings | Add entity/year/jurisdiction profile, preparer-reviewed tax mappings, applicability rules, Florida conditional obligations, and encrypted identifiers. Test supported-year selection and no Florida individual-income form. |
| 8.2 | Reconciliation and frozen workpapers | Reconcile Square/manual sales, 1099-K, refunds, tax, COGS, inventory, expenses, assets, mileage, and payments; trace each accepted receipt-line amount through one canonical order to all supporting PDFs and exclude duplicate copies, personal lines, and unresolved source gaps. Produce source-linked PDF/XLSX/CSV schedules and immutable year snapshots; block on missing provider coverage or tax decisions (RM-022). |
| 8.3 | Certification and production promotion | Add close checklist, six workbook controls, tax approval/coverage controls, full profile composition, backup/restore, migration rollback, worker drain, immutable image/digest promotion, and production smoke tests. No direct filing or tax-liability advice. |

**MVP 8 profile:** `full-mbs` runs all preceding profiles, all 110 source equivalents, tax-specific tests, security, restore, rollback, and deployment evidence. A missing tax-professional approval or provider coverage certificate is a permanent production stop.

## Agent Operating Rule

The agent advances to the next row only when the current row's acceptance tests and validation evidence pass. A later MVP may be designed in this document, but it must not be implemented until its prerequisites and owner decisions are recorded in `03-current-slice.md`. The agent must never convert a proposed default into an approved business rule or use a planned manifest ID as evidence.
