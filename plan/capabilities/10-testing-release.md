# Capability 10: Testing & Release Framework

- [ ] **Capability complete** (all features below checked)

The full MBS release gate preserves all 110 source-workbook regression tests and six certification controls. The standalone Receipt MVP uses its own narrower release profile and does not claim full-system certification.

## Feature 10.1 — Regression Test Suite
- [ ] Feature complete
- [ ] Test perishable-list default date/time as list-created timestamp + 7 days, override preservation, copied-list date reset, blank date on non-perishables, and lot waste at expiry/weekly close with zero carry-forward.
- [ ] Test scheduled expiry processing is idempotent, runs at the Perishable By boundary, and does not waste a lot twice or carry an expired remainder into a new week.
- [ ] Test that newly created and migrated unclassified stock items default to Perishable; verify users can explicitly uncheck empty cups, non-perishable items carry forward, and perishable leftovers become waste at weekly close.
- [ ] Define a Receipt MVP test profile covering upload validation, mocked Google Document AI response parsing/review, exact-hash duplicate rejection before OCR, perceptual near-duplicate blocking before OCR, unique Receipt_ID under concurrent imports, exactly-once OCR for accepted files, zero OCR calls for reads/review/export, JSONB/normalized-row consistency, retrieval after restart, access control, and file/database backup and restore.
- [ ] Test browser session expiry/revocation, secure-cookie flags, CSRF rejection, and matching UI/API role authorization; test receipt corrections preserve immutable `receipt_pk` links and surface a conflicting `Receipt_ID` for explicit resolution.
- [ ] Test Decimal/Numeric money and quantity conversions/rounding, configured business-timezone date assignment, and weekly/expiry boundaries across daylight-saving transitions.
- [ ] Port all 110 source-workbook regression cases as a traceable baseline; classify structural checks (for example, “formula exists” or “table populated”) separately from behavioral tests, and add executable behavioral assertions for every material formula/governance outcome before using the suite as a release gate.
- [ ] Add application integration tests for OCR approval and manual-entry parity, receipt-to-purchase/expense links, Square order replay/update/refund idempotency, manual-sale posting/refund and cross-source deduplication, proving refunds never restock inventory without a separate adjustment, inventory input reconciliation, and no purchase/COGS double counting.
- [ ] Add market-day selling tests for fast repeated submissions, browser refresh, helper permissions, session open/pause/close, online/offline or explicitly unsupported connectivity behavior, queued-event recovery, duplicate synchronization, held drafts, discounts, voids, refunds, sold-out protection, session price overrides, preorder deposits and pickup, customer-facing product information, opening float, cash additions/removals, tender closeout, over/short review, close exceptions, and no duplicate sales or inventory movements.
- [ ] Test non-perishable product and stocked-supply alerts at or below 20% of confirmed target (100 ordered → alert at 20 remaining), no alerts for perishable stock, last restock store/location and optional product URL, market-attributed supply usage, crossing/re-arm deduplication, consent/template enforcement, and no repeat alerts while below threshold.
- [ ] Include WhatsApp test-account coverage from Capability 13; real sends remain disabled in CI. Manual sends require explicit confirmation; automated production alerts require an enabled admin rule and valid purpose-specific recipient consent.
- [ ] Test recipe waste percentages: with 1 cup per product and 10% waste, 9 prepared products consume 9 cups with 0 whole waste cups posted; the 10th posts one waste cup (11 cups total inventory reduction). Verify a 6-item batch followed by a 4-item batch produces the same result as one 10-item batch, estimates include expected waste without posting it, unconfirmed plans do not accrue waste, corrections are idempotent, and fractional-capable ingredient units post exact waste quantities.
- [ ] Test Market Load Lists by market/date, store-grouped printable Ingredient Shopping Lists, recipe ingredient roll-up across products, on-hand subtraction, perishable flags, cost estimates, explicit purchase/production posting, and no effect on inventory/profit from unposted plans.
- [ ] Test perishable product, ingredient, and supply lots expiring once at a known Perishable By timestamp or at weekly close when no purchase-lot date is known; test empty cups as non-perishable supplies, market-attributed usage, non-perishable carry-forward, and no double-counting as waste.
- [ ] Test ingredient cost history across multiple dates and purchase locations, preferred-source selection, chart/filter results, and date-specific recipe/product cost changes without mutating prior cost rows.
- [ ] Test tax-year package reconciliation across Square and manual sales, entity-dependent workpaper routing, Florida sales-tax filing periods, 1099-K versus order/payment totals, export lineage, and reproducible frozen snapshots.
- [ ] Test all four remembered receipt dispositions, recipe multi-mapping without duplicated quantities/costs, exact-match rule reuse, ambiguous-match review, rule correction, personal-item exclusion, and capital-asset routing without automatic operating-expense posting.
- [ ] Test one-market and multi-market travel routes, home-versus-direct choices, reuse of previously saved directed legs without re-entry, missing-leg prompts, and market-cost allocations summing exactly to the trip total.
- [ ] Test market visit date history and cost-effective-date boundaries: required start date, blank/open end date, prior-period lookup, closed-period lookup, invalid ranges, and rejection of overlapping/open-ended periods.
- [ ] Test market opportunity component scores are required manager-reviewed 0–100 inputs, weighted-score calculation and tier boundaries match the workbook, and no unapproved metric-to-score derivation occurs.
- [ ] Test reorder calculations use explicit Safety Stock Quantity and match the workbook formula; changing `safety_stock_pct` alone does not change the reorder point.
- [ ] Keep source regression coverage intact when adding application tests; report source-case count and additional integration-case count separately.
- [ ] `tblTesting` equivalent: stores test run results, timestamps, pass/fail counts for audit and the Release Gate.
- [ ] `testing_mode` setting gates inclusion of `Test Record = Yes` fixture rows — must always be `No` in production (Governance Rule 3/Settings §7).

## Feature 10.2 — MVP-Specific Test Profiles
- [ ] Feature complete
- [ ] Each profile runs against the same versioned migrations and release artifact; record profile name, commit/image version, environment, test counts, results, and linked failures in `tblTesting`. A profile covers only the capabilities in that MVP and its integration boundaries; it does not imply full-system certification.
- [ ] `receipt-mvp` (MVP 1): upload/OCR, review/correction, duplicate handling, persistence, authentication, and file/database backup/restore; Google calls are mocked in CI and real OCR budget/configuration is checked for release.
- [ ] `sales-mvp` (MVP 2): Catalog and per-line readiness, accepted Square/manual sales, exception replay, cursor durability, market/cost snapshots, refunds, and no automatic refund restock.
- [ ] `sales-mvp` (MVP 2): Catalog and per-line readiness, accepted Square/manual sales, market-day session capture, effective-dated operating hours, local-time boundaries, tender closeout, availability, helper permissions, connectivity/recovery decision, exception replay, cursor durability, market/cost snapshots, refunds, and no automatic refund restock.
- [ ] `costing-mvp` (MVP 3): product/recipe setup, unit validation/conversions, effective-dated costs, opening stock, receipt/manual purchase parity, and recipe-waste percentage/fraction accumulation.
- [ ] `prep-mvp` (MVP 4): load and store shopping lists, expected-waste estimates, no stock effects from plans, atomic confirmed-prep postings, and WhatsApp manual-send policy using Meta test resources.
- [ ] `markets-mvp` (MVP 5): dated attendance/cost periods, route reuse and allocation, production corrections, samples, and expense posting.
- [ ] `inventory-mvp` (MVP 6): movement/snapshot reconciliation, lot expiry and carry-forward, reorder quantities, low-stock thresholds, and automated WhatsApp alert idempotency/consent.
- [ ] `analytics-mvp` (MVP 7): dashboards, rankings, opportunity-score inputs/formula, forecast boundaries, test-record isolation, and all 110 source-workbook regression cases.
- [ ] `full-mbs` (MVP 8): tax-specific application tests, all preceding profiles, all 110 source-workbook cases, source reconciliation, final controls, security, backup/restore, and production smoke tests.
- [ ] Before promoting MVP N, require its profile and all applicable preceding profiles to pass for the same release candidate; a later failure does not retroactively invalidate a previously released MVP.

## Feature 10.3 — Release Certification Gate
- [ ] Feature complete
- [ ] Receipt MVP release requires its Receipt MVP profile to pass, receipt import errors = 0, critical upload/authentication findings = 0, a successful database plus file-store restore check, and verified OCR budget/configuration. Mark the release as `receipt-mvp`; do not require unbuilt product-cost, inventory, or dashboard gates.
- [ ] For full MBS releases, implement all six blocking controls from the source workbook: All Tests = PASS; Import Errors = 0; Inventory Errors = 0; Missing Costs = 0; Missing Recipes = 0; Health Score >= 95. Block full-release version promotion unless all six pass simultaneously; these controls do not block the separately gated Receipt MVP release.
- [ ] Apply the six controls, all 110 source-workbook cases, and all applicable application integration tests (including tax tests) to full MBS release certification; MVP 7 passing the source-workbook baseline does not bypass or satisfy this final gate.
- [ ] Define Health Score from the workbook data-quality model: start at 100, subtract each issue category's `MIN(100, Open Issues × 25) × Weight`, floor at 0; test the 95-point release threshold.
- [ ] `POST`/`GET` testing & release endpoints per blueprint §9.8 (ADMIN triggers release, VIEWER+ can view status).

## Feature 10.4 — CI Integration
- [ ] Feature complete
- [ ] GitHub Actions selects the matching named profile for each MVP release and pull request, plus tests for affected upstream contracts; MVP 7 runs the 110 source-workbook baseline, and MVP 8 runs `full-mbs`. Failed required tests block promotion of that MVP (see Capability 11).
- [ ] Lint gate: `ruff` + `mypy` for Python (no `eslint`/`jest` needed since the frontend is now server-rendered Jinja2/HTMX, not a separate JS app).
