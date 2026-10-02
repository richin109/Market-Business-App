# Slice Implementation Guide

Atomic MVP 1–8 task sequence, derived only from plan text. MVP 1 evidence remains in [03-current-slice.md](03-current-slice.md); outcome contracts remain in [mvp-slice-specifications.md](mvp-slice-specifications.md).

## How to Use This Guide

- Implement one unchecked task at a time; require the prior MVP's local synthetic profile before advancing.
- Keep every task after completion. Mark **Completed** only after acceptance passes; record evidence in `03-current-slice.md`.
- Before work, copy scope, tests, manifest IDs, dependencies, and commands into `03-current-slice.md`. Use synthetic data/mocks unless an explicit gate authorizes otherwise.
- Schema tasks require PostgreSQL fresh/prior upgrades, synthetic rows, guarded downgrade, re-upgrade, and ORM parity. UI tasks require desktop/mobile Playwright. Test runtime behavior through the real app, worker, or CLI.
- For MVP 2–8, run focused pytest through `test-dev`, then Ruff, mypy, and the full `test-dev` suite. Rebuild as required. Record unmounted candidate evidence separately from mounted results.
- Follow PostgreSQL stage acceptance and [00-overview.md](00-overview.md)/[04-go-no-go.md](04-go-no-go.md); do not infer policy or complete blocked tasks.

## MVP 1 — Receipt Capture, Review, and Storage

### Completed in the Existing Slice

The plan marks these **Completed**. Keep original descriptions/evidence in [03-current-slice.md](03-current-slice.md):

- [x] **Completed:** D-77 generic configuration, PostgreSQL fixtures/migrations, blocker repairs, and backup components.
- [x] **Completed:** Fast test runner foundation and infrastructure refresh.
- [x] **Completed:** R1–R8 audit remediation.
- [x] **Completed:** S14–S16 store/item identity and administration.
- [x] **Completed:** S10-Routing, D-66 manual entry, S10-Review, S10a, S10b.
- [x] **Completed:** S11 remembered rules; S12 soft delete, import audit, retention settings.
- [x] **Completed:** S17.1–S17.3 media assets, receipt candidates, owner galleries.
- [x] **Completed:** Listed S4b PDF classification, extraction/reconciliation, merchant patterns, worker/tests, PostgreSQL migration.
- [x] **Completed:** S13 backup/restore module and PostgreSQL components.
- [x] **Completed:** Synthetic RM-022 implementation/validation listed in the current slice.

### Remaining D-77 Candidate Gate

- [ ] **M1-D77.5 (Not started): Build the self-contained test image.** Include plan catalog, synthetic tools, PostgreSQL clients, Chromium; exclude private receipt directories. **Accept:** `docker compose build test` passes; build context contains no private receipt files.
- [ ] **M1-D77.6 (Not started): Run the unmounted candidate suite.** **Accept:** `docker compose run --rm --build test` passes; record image identity/result.
- [ ] **M1-D77.7 (Not started): Run candidate lint/type checks.** **Accept:** candidate `docker compose run --rm test ruff check src tests` and `docker compose run --rm test mypy src tests` pass; record commands/results.
- [ ] **M1-D77.8 (Not started): Run PostgreSQL migration tests.** **Accept:** `docker compose run --rm test-migrations-postgres` passes without database/service skips.
- [ ] **M1-D77.9 (Not started): Complete D-00 review.** Review touched code, tests, migrations, configuration, docs, and manifest commands; reconcile 8 stages/16 capabilities; assess portability, live-data isolation, revision stability, savepoint recovery, image staleness, restore safety. Record/fix findings and rerun checks. **Accept:** no open findings; candidate gates pass.

### OCR and Source Gates

- [x] **M1-S4b.1 (Completed): Verify synthetic merchant patterns.** Amazon-style text, BJ's labeled rows, Walmart image-only rows, weighted/tax lines, reference ambiguity, review holds, and focused tests are checked in [03-current-slice.md](03-current-slice.md). Private-corpus accuracy remains open.
- [ ] **M1-S4b.2 (Blocked: RM-024 approval): Complete private-corpus accuracy.** Separate from S18-local; do not block synthetic MVP 2. Under authorized isolation, tune BJ's mapping, Walmart rows, and Amazon parsing against reviewed expectations. **Accept:** approved OCR/review thresholds pass and only redacted aggregate evidence is recorded; otherwise RM-002/RM-023/S4b stay open.
- [ ] **M1-S4b.3 (Blocked: M1-S4b.2): Review S4b.** Critically review parser, provenance, tests, migration, worker wiring, and docs; fix findings and rerun focused/full checks. Not an MVP 2 prerequisite. **Accept:** findings resolved/evidenced; no private values in repo/evidence.
- [ ] **M1-RM023.1 (Not started): Verify synthetic field evidence.** Use image-only/selectable-text PDFs to distinguish package size vs weighed quantity, merchant item number vs UPC, printed references/times, visible vs masked payment suffix, and subtotal vs tax. **Accept:** `docker compose run --rm test pytest tests/receipts/test_receipt_mvp.py -k test_rm_023 -q` passes; preserve raw alternatives, hold uncertain fields, use no private inputs.
- [ ] **M1-RM023.2 (Not started): Verify synthetic review.** Exercise evidence display/correction in `receipt-mvp`. **Accept:** managers resolve ambiguity without silent promotion; desktop/mobile browser checks pass.
- [ ] **M1-RM024.1 (Blocked: owner authorization): Obtain private-corpus approval.** Record operator, isolated environment, purpose, access, retention/deletion, and redacted-evidence rules per [02-implementation-readiness.md](02-implementation-readiness.md). **Accept:** all approvals precede corpus evaluation; otherwise RM-024 stays unchecked.
- [ ] **M1-RM024.2 (Blocked: M1-RM024.1): Preflight private inputs.** Verify files/expectations are untracked or external, present, reviewed, and checksum-matched; otherwise fail closed. **Accept:** no identifiable output or CI/external OCR transfer.
- [ ] **M1-RM024.3 (Blocked: M1-RM024.1–.2): Run isolated accuracy evaluation.** Run the planned RM-024 test only in the authorized local environment. **Accept:** per-file/combined-order reconciliation meets approved thresholds; record redacted aggregates only; never run in CI.
- [ ] **M1-RM025.1 (Not started): Prove unchanged-directory replay.** Run one synthetic directory twice. **Accept:** rerun creates no duplicate receipts, sources, approvals, or postings.
- [ ] **M1-RM025.2 (Not started): Prove changed source versions.** Replay synthetic sets of 5, 10, then 15 complete orders. **Accept:** each version adds exactly 5 identities; prior IDs/postings stay stable; unchanged/old reruns add none.
- [ ] **M1-RM025.3 (Not started): Prove ambiguity and per-file status.** Test insufficient identities, near-match resolution, retries/concurrency, and browser status. **Accept:** `docker compose run --rm test pytest tests/receipts/test_receipt_mvp.py -k test_rm_025 -q` passes; ambiguous orders stay visible holds, never auto-post; migration/browser checks pass. Production policy remains owner-gated.

### Remaining S13 Recovery and S18 Gates

- [ ] **M1-S13.1 (Not started): Plan synthetic recovery test.** Record candidate/version/scale, writer pause, worker drain, PG snapshot, protected files, target, and measurements. **Accept:** repeatable test uses no production/private data.
- [ ] **M1-S13.2 (Not started): Verify coordinated synthetic restore.** Restore PostgreSQL/files together into an empty target; verify row/source/media counts and checksums; record observed duration as non-production evidence. **Accept:** restored synthetic app is consistent and usable. This does not satisfy production RPO/RTO.
- [ ] **M1-S13.3 (Not started): Prove synthetic restart survival.** Restart Compose after synthetic receipt/source acceptance and exercise RM-025 source versions. **Accept:** receipt/files/media remain reviewable without OCR rerun; multi-order lineage survives; add executable evidence to RM-010/RM-016/RM-022 and RM-025 intent.
- [ ] **M1-S13.4 (Blocked: production readiness approvals): Measure production recovery.** Run timed PostgreSQL/protected-file restore at approved production scale after U-3/readiness approvals, with writers quiesced and workers drained. **Accept:** same candidate proves RPO ≤24h and RTO ≤8h; record scale/version/timings. Required for production, not S18-local.
- [ ] **M1-S18L.1 (Not started): Verify local prerequisites and invocation.** Confirm S14, S15, S10, S10a/b, S11–S13, S16, S17 evidence; record the exact command/test selection that runs `receipt-mvp` against a pinned candidate. **Accept:** no local prerequisite is open and the profile command is runnable; production approvals are not substitutes.
- [ ] **M1-S18L.2 (Not started): Run synthetic `receipt-mvp`.** Use rebuilt unmounted candidate; run its recorded command, migrations, real entry points, synthetic OCR, backup/restart, and browser workflows. **Accept:** profile and desktop/mobile evidence pass without private-corpus processing.
- [ ] **M1-S18L.3 (Not started): Record S18-local evidence.** Record candidate digest, migrations, profile commands/results, browser/version/viewports, exclusions. **Accept:** evidence complete and S18-local checked before synthetic MVP 2.
- [ ] **M1-S18P.1 (Blocked: owner gates): Record production approvals/measures.** Complete U-3 backup/privacy setup, applicable real-data approval, RM-024 evidence, OCR/review thresholds, and D-06 measures. **Accept:** all owner decisions/results recorded; separate from S18-local.
- [ ] **M1-S18P.2 (Blocked: M1-S18P.1): Validate fail-closed PDF scanning.** Test clean, malicious, unavailable scanner, and retry in the production candidate. **Accept:** required fail-closed behavior passes; real PDFs remain blocked until approved.
- Production recovery is M1-S13.4 above; complete it after M1-S18P.1 approvals and before promotion.
- [ ] **M1-S18P.3 (Blocked: M1-S18P.1/.2 and M1-S13.4): Record promotion evidence.** **Accept:** approvals, privacy, RM-024, thresholds, D-06, scan, migrations, timed recovery, and release results refer to one candidate; otherwise block promotion.

## MVP 2 — Square Catalog, Products, Recipes, and Costing

MVP 2 tasks are **Not started**. Start after S18-local; use fixtures/mocks until read-only credentials are approved. No MVP 2 task accepts sales.

### Slice 2.1 — Read-Only Square Adapter

- [ ] **2.1.1 (Not started): Define read allowlist.** Permit approved Catalog/Orders/Payments/Location reads and POST searches only. **Accept:** fixtures cover every allowed call; no writes allowed. Link SQ-001.
- [ ] **2.1.2 (Not started): Enforce credentials.** Live access requires approved read-scoped credentials; tests use mocks/fixtures. **Accept:** missing/over-scoped credentials fail closed; no secrets in logs/evidence.
- [ ] **2.1.3 (Not started): Block forbidden calls pre-network.** Test sync, retry, and admin paths. **Accept:** forbidden/mutating calls send zero requests.

### Slice 2.2 — Catalog Staging and Market Prerequisites

- [ ] **2.2.1 (Not started): Persist raw Catalog pages, cursors, and audit.** **Accept:** replay creates no duplicates; cursor never passes uncommitted data; PostgreSQL migrations pass.
- [ ] **2.2.2 (Not started): Add authorized Catalog-only Sync Now.** **Accept:** authenticated/audited; no market-end polling or Orders/Payments staging (D-69).
- [ ] **2.2.3 (Not started): Add Variation-ID products with required Shelf Life.** **Accept:** reject missing Shelf Life before save; never create a purchased store item from a Square variation (D-52).
- [ ] **2.2.4 (Not started): Add market/location/hour/dated-visit setup.** **Accept:** full-date periods reject overlaps; closed dates, timezone, DST resolve by effective business date; schedules do not create attendance.
- [ ] **2.2.5 (Not started): Add Capability 15's ordered market plan/targets.** Reuse one plan identity through MVP 4; Capability 5 supplies markets/visits/hours. **Accept:** ordered targets persist but create no stock/attendance. Test planned≠attended and target isolation (MP-004; MKT001; SL-001).

### Slice 2.2a — Direct Sell Receipt-Backed Stock

- [ ] **2.2a.1 (Not started): Claim Direct Sell routes only.** **Accept:** unresolved mapping/Shelf Life, prior expense, personal, or unapproved lines stay held with no stock; other destinations untouched.
- [ ] **2.2a.2 (Not started): Resolve one Variation-ID/item link.** **Accept:** canonical item/store item explicit; multiple active variations for one item stay held pending approved conserved allocation.
- [ ] **2.2a.3 (Not started): Convert reviewed count packages.** **Accept:** package count × confirmed count-unit size; missing/unsupported units held; cross-dimension conversion deferred to 2.3.
- [ ] **2.2a.4 (Not started): Post one idempotent dated stock event.** **Accept:** one transaction records receipt/store-item/line/route provenance; retry returns same fact; corrections append linked reversals; fresh/upgrade/downgrade pass. Link DS-001, PH-001/002.

### Slice 2.3 — Units, Product Master, and Readiness

- [ ] **2.3.1 (Not started): Extend units/aliases.** **Accept:** same-dimension factors and package piece counts use Decimal; reject incompatible units (CO-001; D-50).
- [ ] **2.3.2 (Not started): Add dated per-item conversions.** **Accept:** resolve by full business date; reject ambiguous/overlapping periods; retain historical receipt quantities.
- [ ] **2.3.3 (Not started): Add sourcing mode and required Shelf Life.** **Accept:** recipe-made may await recipe; Direct Sell retains 2.2a link; tracked products/items require Shelf Life before stock.
- [ ] **2.3.4 (Not started): Add readiness and legacy migration.** **Accept:** neither mode READY before dated 2.5 cost; migrate `is_perishable` without guessing; test pending/READY (SL-001; RT051–060; RT070).

### Slice 2.4 — Recipes, Supplies, and Cost Engine

- [ ] **2.4.1 (Not started): Add recipe/product/ingredient/supply identities and mappings.** **Accept:** canonical inputs/compatible units enforced; recipe output Shelf Life required (`never` allowed).
- [ ] **2.4.2 (Not started): Calculate recipe waste/fractions.** **Accept:** deterministic Decimal calculations write no stock/production; test `never` cup and two-week 0.60/0.64 fruit-cup cases.
- [ ] **2.4.3 (Not started): Define dated costs and as-of resolver.** **Accept:** use latest valid cost on/before date; label carry-forward; respect recipe versions; 2.5 is first receipt-cost writer (D-57; CS-001).
- [ ] **2.4.4 (Not started): Define typed blocks and exception register.** **Accept:** each block has reason, exception ID, scope; unaffected figures calculate; never substitute zero, omit silently, or use future cost (D-61; BL-001).

### Slice 2.4a — Catalog Imagery

- [ ] **2.4a.1 (Not started): Add galleries over S17.** **Accept:** product/ingredient/supply/recipe resolution is owner image → canonical fallback → placeholder; replace defaults No; no image generation; IM-003/004 desktop/mobile tests pass.

### Slice 2.5 — Purchases, Receipt Links, and Expected Inventory

- [ ] **2.5.1 (Not started): Consume each routing destination once.** **Accept:** Direct Sell extends existing fact; ingredient/supply routes create only their purchase/cost/stock facts; exclude personal; retries/corrections retain lineage without replay (D-73).
- [ ] **2.5.2 (Not started): Migrate route claims/fact links.** **Accept:** fresh/prior PostgreSQL upgrades preserve state/links; guarded downgrade and re-upgrade pass.
- [ ] **2.5.3 (Not started): Wire dated purchase costs to readiness/as-of reads.** **Accept:** real receipt approval writes expected purchase/date cost; carry-forward and typed missing-cost results match business date (CS-001; BL-001).
- [ ] **2.5.4 (Not started): Add `never`-item expected-inventory override.** **Accept:** only `never` items; MANAGER audit/reason required; perishables excluded (D-51; D-61).
- [ ] **2.5.5 (Not started): Prove source/manual parity.** **Accept:** supplements append once, copies add none, manual no-attachment follows same identity/routing, plan targets leave water balance unchanged. Link RM-022, CO-001, PH-001/002.

### Slice 2.6 — Foundational Ledger and Balance Reader

- [ ] **2.6.1 (Not started): Add canonical lots/movements/allocations and one reader.** **Accept:** MVP 2 movements come only from approved receipt purchases/restocks; targets add no stock; no second balance path (D-59).
- [ ] **2.6.2 (Not started): Label inactive sources and expiry.** **Accept:** future sources return `SOURCE_NOT_YET_ACTIVE`; expired-as-of lots are excluded as `EXPIRY_POSTING_PENDING`; missing acquisition instant blocks balance, never use row-created time (D-74).
- [ ] **2.6.3 (Not started): Prove reader through real entry point.** **Accept:** target edits do not change stock; source coverage explicit; reviewed-time expiry exclusion and audited `never` override pass (MP-004; SL-003).

**MVP 2 gate:** `costing-mvp` passes on clean/upgrade databases; prove routing retry/correction, manual parity, units/rounding, readiness, purchases, recipes, as-of costs, blocks, source coverage, and one balance interface. Pass PostgreSQL matrix and desktop/mobile Playwright. No sales or provisional/manual costs.

## MVP 3 — Sales Activation and Market-Day Operations

MVP 3 is **Not started**. Begin after `costing-mvp` passes. Square remains the only sales system; no manual sales/cash counting.

### Slice 3.1 — Orders Staging and Per-Line Acceptance

- [ ] **3.1.1 (Not started): Stage Orders pages before cursor advance.** **Accept:** interrupted/replayed pages neither skip nor duplicate rows; cursor/audit commit atomically.
- [ ] **3.1.2 (Not started): Gate line acceptance.** **Accept:** require Variation ID, dated cost, valid market/channel, and Attended/Partial outcome; retain unresolved/Planned/Excluded lines as exceptions.
- [ ] **3.1.3 (Not started): Add scheduled and manual sync.** **Accept:** start 30 minutes after market end; repeat every 24h while late/unresolved data remains; authorized/audited Sync Now; retries idempotent.
- [ ] **3.1.4 (Not started): Handle late updates/refunds and line identity.** **Accept:** late orders retain original business date and are flagged; `Order ID + Line Item UID` unique; test partial batches, attendance transitions, updates, refunds, duplicate IDs.

### Slice 3.2 — Payment and Settlement Reconciliation

- [ ] **3.2.1 (Not started): Reconcile Orders/Payments without deriving sales from Payments.** **Accept:** reconcile orders, payments, refunds, discounts, tax, fees, settlements by stable provider IDs; cash sales originate in Square.
- [ ] **3.2.2 (Not started): Preserve corrections and sale snapshots.** **Accept:** append late updates/refunds; accepted cost/market snapshots stay immutable; retries add no sales.

### Slice 3.3 — Market-Day Session, Production, and Settlement Visibility

- [ ] **3.3.1 (Not started): Add role-based market sessions.** **Accept:** ADMIN/MANAGER/VIEWER permissions; availability uses only MVP 2 `StockBalanceReader`.
- [ ] **3.3.2 (Not started): Add shared idempotent production service.** **Accept:** one transaction posts `Made N` output and consumes effective recipe inputs; same Variation ID/date is declarative, re-entry corrects (D-60; D-64).
- [ ] **3.3.3 (Not started): Connect allocation, sales, close.** **Accept:** allocate reviewed Direct Sell only; subtract accepted Square quantities once; targets add no stock; transfer unsold allocation at approved close.
- [ ] **3.3.4 (Not started): Prove examples and retries.** **Accept:** fruit cups 12 target/15 made/3 sold leaves 12 with inputs consumed; water 24 purchased/6 loaded/2 sold leaves 4 at market, 22 overall; retries add no stock/COGS. Link MP-002, DS-001, PC-001.

**MVP 3 gate:** `sales-mvp` passes clean/upgrade DBs; prove MP-002 receipt→stock→sale via real entry points, Square provenance, recipe COGS, sync, and visible/retryable exceptions. Pass PostgreSQL and desktop/mobile Playwright checks.

## MVP 4 — Shopping, Prep, and WhatsApp

MVP 4 is **Not started**. Begin after MVP 2 balance/cost and MVP 3 production/sales pass. Use Meta mocks or approved test WABA; no real CI recipients.

### Slice 4.1 — Persisted Production Waste and Corrections

- [ ] **4.1.1 (Not started): Persist production waste remainder.** **Accept:** atomically carry fractions across dates/weeks; use shared production service and MVP 2 reader, never a second balance path (D-59; PC-001).
- [ ] **4.1.2 (Not started): Add audited correction/reversal.** **Accept:** MANAGER reason + idempotency key; preserve confirmed batch; same-date re-entry adjusts output, inputs, supplies, remainder by delta (D-64).
- [ ] **4.1.3 (Not started): Test time, retry, rollback.** **Accept:** 6 then 4 on separate dates differs from 10 once; same-date 6→10 is exact; retries/concurrency/rollback duplicate no stock/COGS; Square subtracts once. Link PD-001.

### Slice 4.2 — Market Planning and Store-Grouped Shopping

- [ ] **4.2.1 (Not started): Extend plan without duplicating visits.** **Accept:** recipe targets show ingredients; Direct Sell uses canonical items; all share ordered visits and one target quantity.
- [ ] **4.2.2 (Not started): Calculate combined shopping list.** **Accept:** group by canonical store; include conversions, expected waste, balance, `Perishable By`, copy, print/export, receipt purchases; plan edits add no stock (MP-001).
- [ ] **4.2.3 (Not started): Display plan-end waste read-only.** **Accept:** effective `waste_at_plan_end` applies only to recipe-made output; edit only in recipe setup, never receipt/load lines (D-54).
- [ ] **4.2.4 (Not started): Test sourcing/quantity limits.** **Accept:** expose missing sourcing/incompatible conversions; separate target from receipt quantity; plan edits leave stock unchanged. Link SL-003/RM-022.

### Slice 4.3 — Finalized Shopping List and WhatsApp Batch

- [ ] **4.3.1 (Not started): Finalize/version combined list.** **Accept:** immutable version identifies one explicit send batch; edits create a new version.
- [ ] **4.3.2 (Not started): Validate consent/recipients.** **Accept:** manual send, at least two opted-in recipients, template/window, private per-recipient messages, cost threshold; retain print fallback.
- [ ] **4.3.3 (Not started): Make sends retry-safe/observable.** **Accept:** idempotent per version/recipient; record webhook status; retry same batch; purchases/made edits do not resend (D-53; MP-003).
- [ ] **4.3.4 (Not started): Test browser flow.** **Accept:** confirmation, recipient choice, status, failure/retry, print pass desktop/mobile Playwright with mocks.

**MVP 4 gate:** `prep-mvp` proves waste/correction, shopping, finalized-list messaging, consent, atomicity, one balance path, and responsive UI.

## MVP 5 — Markets and Weekly Operations

MVP 5 is **Not started**. Begin after MVP 2 visit identity and MVP 3 shared production service pass. D-18/D-22/D-60 are approved.

### Slice 5.1 — Market Costs, Visits, and Attendance

- [ ] **5.1.1 (Not started): Add dated market costs and attendance history.** **Accept:** full-date periods, stable visit identity, multiple markets/day, explicit attendance only.
- [ ] **5.1.2 (Not started): Add closed/exception dates and cancellation.** **Accept:** retain dates; audit cancellation without deleting market/links; resolve history by date. Cover RT071–074, RT077–082.

### Slice 5.2 — Directed Route Legs and Allocations

- [ ] **5.2.1 (Not started): Add directed legs and itinerary selection.** **Accept:** retain direction; support Home/direct travel and effective mileage rates.
- [ ] **5.2.2 (Not started): Add audited overrides and trip allocation.** **Accept:** audit/reason required; allocations equal trip cost; boundaries pass (RT075–076).

### Slice 5.3 — Weekly Production, Expenses, and Assets

- [ ] **5.3.1 (Not started): Add weekly ops via shared production service.** **Accept:** entry, samples, supplies reuse ledger/corrections; no second writer.
- [ ] **5.3.2 (Not started): Add expense/asset workflows.** **Accept:** accepted line/source-page provenance; manual/receipt parity; exclude personal/mixed-use; show capital drafts/unallocated expenses.
- [ ] **5.3.3 (Not started): Prove retries/corrections.** **Accept:** weekly corrections/supplement replay duplicate no COGS/expenses; responsive browser checks pass (RM-022; PC-001).

**MVP 5 gate:** `markets-mvp` proves visit migration, route allocation, production correction, expense idempotency, asset routing, responsive weekly entry.

## MVP 6 — Inventory and Reorder

MVP 6 is **Not started**. Begin after approved sales, purchases, production movements, and inventory decisions. Extend, never replace, MVP 2 ledger/`StockBalanceReader`.

### Slice 6.1 — Ledger Reconciliation and Weekly Snapshots

- [ ] **6.1.1 (Not started): Reconcile lots/movements.** **Accept:** replay adds no stock; preserve lot identity/reviewed instants; hold missing authoritative dates.
- [ ] **6.1.2 (Not started): Add snapshots/reconciliation.** **Accept:** unique scope/period; exclude test rows from production; reconcile all movements without a second ledger.
- [ ] **6.1.3 (Not started): Extend reader/valuation.** **Accept:** deterministic FEFO, lot acquisition cost, no revaluation from later purchases, visible pending expiry. Cover D-57/58/59, CS-003, RT026–035/043/048–050.

### Slice 6.2 — Expiry, Spoilage, Close, and Restatement

- [ ] **6.2.1 (Not started): Add expiry posting/catch-up.** **Accept:** startup/interval posts one waste per eligible expired lot; clear pending only on commit; hold unknown dates.
- [ ] **6.2.2 (Not started): Add immutable close/restatement.** **Accept:** carry unexpired/`never`; never double-count recipe plan-end waste or Square sales; restate idempotently, retain versions.
- [ ] **6.2.3 (Not started): Test concurrency/calendar.** **Accept:** migration/startup replay, DST/month-end, downtime catch-up, concurrent close/expiry, exactly-once restatement; reconcile SL-003/004 pending lots.

### Slice 6.3 — Reorder and Low-Stock Alerts

- [ ] **6.3.1 (Not started): Calculate reorder quantity.** **Accept:** approved safety-stock, unit, usage, lead-time, source, cost formula.
- [ ] **6.3.2 (Not started): Add alert eligibility/re-arm.** **Accept:** alert at ≤20%, re-arm strictly above; eligible only `never` or life ≥ `low_stock_alert_min_shelf_life_days`.
- [ ] **6.3.3 (Not started): Add consent-checked alerts.** **Accept:** source/store/date/URL when available; mock-test consent/templates, dedup/retry, equality/no-op (SL-004).

**MVP 6 gate:** `inventory-mvp` reconciles stock through close/restatement, including pending-expiry catch-up; reorder matches formula; alerts are idempotent/consent-checked.

## MVP 7 — Analytics, Dashboards, and Forecasting

MVP 7 is **Not started**. Begin after MVP 6 snapshots; classify source-test applicability before release.

### Slice 7.1 — Refresh Runs, Watermarks, and Lineage

- [ ] **7.1.1 (Not started): Add refresh IDs/dependencies/watermarks.** **Accept:** record inputs/order; distinguish stale/failed; never publish partial output.
- [ ] **7.1.2 (Not started): Publish coherent snapshots atomically.** **Accept:** concurrency/failure cannot expose mixed versions; test isolation and stable order.
- [ ] **7.1.3 (Not started): Add lineage/block propagation.** **Accept:** drill to sources; D-61 blocks only affected figures; incomplete aggregates list blockers; count orders/lines, not PDFs.
- [ ] **7.1.4 (Not started): Add dated costs/restatements.** **Accept:** cost by business date; later repricing leaves prior reports unchanged; backdated receipts expose original/restated values (D-57; CS-001/002).
- [ ] **7.1.5 (Not started): Implement source-test equivalents.** **Accept:** applicable RT001–025/036–042/065–068/083–085/087–088/108–109 assert behavior/config, not formula text; exclude test rows.

### Slice 7.2 — Scorecards, Rankings, Opportunity, and Forecasts

- [ ] **7.2.1 (Not started): Implement lifecycle/rank rules.** **Accept:** approved lifecycle, market ranks, manager inputs, deterministic ties.
- [ ] **7.2.2 (Not started): Implement forecast history/as-of rules.** **Accept:** fixed as-of, preserved snapshots; cover RT013–021/051–070/083–088.

### Slice 7.3 — Dashboards and Release Evidence

- [ ] **7.3.1 (Not started): Add responsive dashboards/source drill-through.** **Accept:** ops/exec pages, charts, Health Score/issues, KPI links, six controls on desktop/mobile.
- [ ] **7.3.2 (Not started): Classify test intents.** **Accept:** test behavior or document approved N/A; structural cases assert behavior/schema/config.
- [ ] **7.3.3 (Not started): Enforce publication blockers.** **Accept:** withhold calculations while required issues are open; label mixed/incomplete states.

**MVP 7 gate:** `analytics-mvp` runs applicable/transformed tests, reports coverage categories, records approved N/A, rejects mixed-state publication.

## MVP 8 — Tax Workpapers and Full-System Release

MVP 8 is **Not started**. Synthetic drafts may follow predecessor local profiles. U-7 gates real-year export; U-6 gates Proxmox production.

### Slice 8.1 — Tax Profile and Effective Mappings

- [ ] **8.1.1 (Not started): Add entity/year/jurisdiction profiles.** **Accept:** explicit supported years/jurisdictions; no Florida individual-income form.
- [ ] **8.1.2 (Not started): Add draft effective tax mappings.** **Accept:** preparer review, applicability, conditional Florida duties, encrypted IDs; no production approval without U-7.
- [ ] **8.1.3 (Not started): Test synthetic year selection/gate real export.** **Accept:** synthetic profiles work; real-year output fails closed without signed mappings/decisions.

### Slice 8.2 — Reconciliation and Frozen Workpapers

- [ ] **8.2.1 (Not started): Reconcile financial sources.** **Accept:** Square/1099-K, refunds, tax, COGS, inventory, expenses, assets, mileage, payments trace to source.
- [ ] **8.2.2 (Not started): Reconcile receipt evidence.** **Accept:** each accepted line traces through one canonical order to all PDFs; copies/personal/unresolved gaps do not inflate totals (RM-022).
- [ ] **8.2.3 (Not started): Generate/freeze synthetic workpapers.** **Accept:** PDF/XLSX/CSV use immutable year snapshot; retries do not alter it.
- [ ] **8.2.4 (Not started): Gate owner-facing exports.** **Accept:** real-year export fails closed until provider coverage, signed mapping, and decisions pass.

### Slice 8.3 — Certification and Production Promotion

- [ ] **8.3.1 (Not started): Complete owner production prerequisites.** **Accept:** record U-6/U-7, signed year mappings, provider coverage; otherwise stop.
- [ ] **8.3.2 (Not started): Compose release controls.** **Accept:** close checklist, six controls, tax approvals/coverage, predecessor profiles, tax tests on one candidate.
- [ ] **8.3.3 (Not started): Prove deployment/recovery.** **Accept:** backup/restore, migration rollback, worker drain, immutable digest, smoke/security checks; exclude dev/test and example credentials.
- [ ] **8.3.4 (Not started): Preserve filing boundary.** **Accept:** workpapers support review; app never files returns or advises final liability.

**MVP 8 gate:** `full-mbs` passes predecessor profiles, applicable/transformed source tests, approved N/A, tax/security/recovery/deployment evidence. Missing professional approval or coverage permanently blocks production.

## Plan-Derived Sequencing and Ownership Improvements

- Sequence D-77 candidate → S13 recovery/restart → S18-local → MVP 2. Keep S18-production/RM-024 separate from synthetic readiness (D-76/77).
- Keep synthetic OCR/replay separate from private evaluation. RM-023/synthetic RM-025 may run locally; RM-024 is authorized-only and never CI.
- Preserve ownership: one `StockBalanceReader` (D-59), Cap 5 production service (D-60), destination-specific route claims (D-73); no parallel ledgers/writers.
- Preserve MVP boundaries/numbers; keep Direct Sell stock (2.2a) separate from ingredient/supply purchase posting (2.5), and local gates separate from production.

## Cross-MVP Release Order

1. Finish the remaining MVP 1 D-77 candidate gate.
2. Complete S13 synthetic restore/restart and S18-local certification. Production-scale timed recovery remains a separate production gate.
3. Implement MVP 2 slices 2.1 through 2.6, then pass `costing-mvp`.
4. Implement MVP 3 slices 3.1 through 3.3, then pass `sales-mvp`.
5. Implement MVP 4 slices 4.1 through 4.3, then pass `prep-mvp`.
6. Implement MVP 5 slices 5.1 through 5.3, then pass `markets-mvp`.
7. Implement MVP 6 slices 6.1 through 6.3, then pass `inventory-mvp`.
8. Implement MVP 7 slices 7.1 through 7.3, then pass `analytics-mvp`.
9. Implement MVP 8 slices 8.1 through 8.3; keep synthetic development separate from U-6/U-7 production gates; pass `full-mbs` before production promotion.

Profiles do not clear production-only gates. A checkbox requires actual command, migration/profile result, and evidence in the active slice/manifest.
