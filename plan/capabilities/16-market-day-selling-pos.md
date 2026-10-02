# Capability 16: Market-Day Selling & POS Operations

Database: PostgreSQL only; see [D-77](../00-overview.md#postgresql-contract-all-stages).
- [ ] Test concurrent session open/close/allocation, parent locks, declarative production, UTC/DST close, one-time transfers, restart; no parallel sales/stock ledger.

- [ ] **Capability complete** (all features below checked)

Bounded context: `src/mbs/market_day/`. Owns stall sessions, not sales. Square POS captures sales; use Cap 14 sales, Cap 4 products/prices, Cap 5 visits/shared production service (call, never define; D-60), MVP 2 `StockBalanceReader` (D-59), and Cap 9 settings/roles. Cap 6 later replaces reader implementation behind same interface; no parallel ledgers.

## Feature 16.1 — Market-Day Session
- [ ] Feature complete
- [ ] Create one market-day selling session linked to a dated market visit, business timezone, operator, and device/session identifier.
- [ ] Enforce D-03 states: OPEN, PAUSED, CLOSE_EXCEPTION, OPERATIONALLY_CLOSED, SETTLEMENT_RECONCILED. Auto-close 1h after planned close, before any earlier next-market start; opening a new market closes existing OPEN/PAUSED first and audits actor/time/sessions/reason. Keep close exceptions until resolved/approved; close ≠ settlement. Accept unambiguous late Square lines against original qualifying visit/date/location/hours (D-19); hold unresolved attribution for review.
- [ ] Show only products configured for the selected market session, with current price, tax treatment, available quantity/status, and customer-facing name.
- [ ] Show each product's approved primary image as a Square product-reference tile or market display with accessible alternative text from the customer-facing name; a product with no image renders the default placeholder. Serve the D-41 thumbnails (fit inside 320 px, shown at 160 CSS px) and degrade to placeholders if the image store is unavailable rather than blocking market closeout (IM-005).
- [ ] Provide phone touch-friendly status/availability and desktop-wide import, product availability, settlement exceptions, closeout layouts.
- [ ] Use the existing VIEWER role for read-only market-plan, Square-import, availability, and settlement views; MANAGER controls operational plans and exceptions, and ADMIN controls users/settings. Do not add a separate HELPER role in MVP 1–8 (D-12).

## Feature 16.2 — Square Import & Settlement View
- [ ] Feature complete
- [ ] In MVP 3 display Cap 14 imported Orders; never initiate local checkout. Show stale watermark when no provider identity; require authorized resolution of unmatched/ambiguous Orders (D-16).
- [ ] Do not capture sales or tenders locally. The Square app/POS records every sale, including cash-tender sales; MBS imports the resulting Orders and Payments.
- [ ] Display imported quantity changes, line discounts, order discounts, refunds, voids, and corrections as linked provider events; never overwrite the original Square fact.
- [ ] Display the Square Catalog price and imported Square sale amounts; MBS does not apply local price overrides or hold sale drafts.
- [ ] Require every accepted imported Square line to have product, quantity, amount, tender, market session, business date, and provider source identity; unresolved entries remain visible exceptions.
- [ ] Show `PROVIDER_PENDING` only for a registered, correlatable provider identity until its Order is durably staged and accepted by Capability 14. A Square POS transaction without that identity is not a known local pending sale; show last sync/watermark and later exception status instead. Never show a pending estimate as accepted or settled.

## Feature 16.3 — Connectivity & Synchronization
- [ ] Feature complete
- [ ] Square's app/POS remains the external sales system. MBS runs on the laptop initially and may move to Proxmox later; it only reads/imports Square data. MBS does not capture, submit, queue, edit, or separately track sales. Show provider synchronization, import exceptions, and settlement data when available; never claim an unimported Square record is settled.
- [ ] Provide a controlled recovery path for browser refresh or device loss without duplicating imported Square facts or session allocations.

## Feature 16.4 — Square Settlement Visibility & Market Close
- [ ] Feature complete
- [ ] Do not record cash floats, cash removals, cash counts, or over/short variances in MBS. Square remains responsible for tender capture and cash controls.
- [ ] Display Square tender, refund, fee, payout, and settlement information without treating a provider deposit as a second sale.
- [ ] Separate `OPERATIONALLY_CLOSED` from `SETTLEMENT_RECONCILED`. An operational close may retain visibly pending Square orders/payments and unresolved reconciliation exceptions; it becomes settlement reconciled only after the configured provider-import and payout-allocation conditions pass.
- [ ] Run the automatic-close job using each visit's planned local close time and the approved `business_timezone`; make the close idempotent across retries and restarts. Record whether the close was scheduled, capped by the next market, or triggered by opening another market.
- [ ] Produce a market close summary showing imported units sold, gross sales, discounts, tax collected, refunds, Square tender totals, fees where known, settlement status, and unresolved exceptions.
- [ ] Require close exceptions to be resolved or explicitly approved before the market visit is considered settlement reconciled. Record the approver, reason, pending provider identities, and follow-up state for an approved exception.

## Feature 16.5 — Availability, Preorders & Customer Pickup
- [ ] Feature complete
- [ ] Call Capability 6's shared reserve/commit/release/transfer/dispose commands for made or receipt-backed Direct Sell stock; read only via MVP 2 `StockBalanceReader` (D-59/72), never a parallel/session reader. Show recipe/Direct Sell products and load available purchased units. Receipt 24/load 6 reserves 6 (18 unallocated); sale 2 reduces loaded/overall once. Hold excess/unmapped loads; invent no purchase/made events. Transfer only remaining allocation. Refund restock needs audited return (D-52/53/55).
- [ ] Support optional preorder/reservation records linked to a market visit, customer contact, requested products, quantity, provider-linked Square payment/deposit status (or explicitly unpaid/unknown), pickup status, substitutions, and cancellation. MBS never captures or asserts a local payment; an unlinked deposit cannot be treated as paid.
- [ ] Once shelf-life lots exist (MVP 3 onward), exclude lots whose `Perishable By` has passed from session availability and show the remaining `Perishable By` on loaded stock; do not reintroduce an expired lot through a transfer or an unposted reallocation.
- [ ] Keep customer contact data consent-aware and access-controlled; do not require customer accounts for an in-person sale.
- [ ] Mark pickup orders collected, partially collected, cancelled, or unclaimed; report unclaimed inventory for an explicit disposition.
- [ ] Keep preorder fulfillment and deposits traceable to the canonical sales/refund records without counting a deposit and final sale twice. A reservation holds session allocation until pickup, cancellation, or an explicit end-of-day disposition.
- [ ] At market load confirmation, show the effective recipe's saved `waste_at_plan_end` status for recipe-made products, not an editable market-load or receipt checkbox. At final close, waste only remaining unsold units from lots made under a checked recipe; unchecked recipe lots carry until their output Shelf Life expires. Direct Sell products such as water never use recipe end-of-plan waste and follow their item's own `Perishable By`; receipt 24/load 6/sale 2 leaves all 22 unsold bottles in expected stock. Sold units cannot waste, and final close/expiry retries cannot dispose twice (D-47/D-54/D-55).

## Feature 16.6 — Stall Readiness & Customer Information
- [ ] Feature complete
- [ ] Provide a pre-open checklist for Square device/payment readiness, products, packaging, labels/signage, samples, permits/documents, and emergency supplies.
- [ ] Provide a printable or display-mode price list for the selected market session, including product name, unit, price, availability, and approved customer-facing descriptions.
- [ ] Include each product's approved primary image, or the default placeholder, in the printable and display-mode lists. No internal cost, margin, supplier, or store data may appear in any customer-facing view, and image provenance metadata is not exposed to customers. Cover IM-005 in [the test-case manifest](../test-case-manifest.csv); planned focused command once implemented: `docker compose run --rm test pytest tests/test_market_day_product_display.py -q`.
- [ ] Products may expose approved ingredient, allergen, storage, best-by, batch/production-date, and preparation information when applicable; do not expose internal margin or cost data.
- [ ] Record market-day observations such as weather, foot traffic, promotion, competitor notes, and operational incidents separately from financial facts.
- [ ] Provide an end-of-day packing and equipment checklist, including damaged, returned, donated, or discarded stock as explicit session-allocation disposition events. Capability 6 later maps these events to the full inventory movement model.

## Feature 16.7 — APIs, Permissions & Tests
- [ ] Feature complete
- [ ] Provide session, Square-import-status, settlement-status, closeout, availability, preorder, and checklist endpoints with role checks and CSRF protection for browser actions.
- [ ] Use Capability 14's canonical sale and refund services, the shared session-allocation/inventory-movement interface, and Capability 5's dated market visit; this capability must not write parallel sales or inventory tables.
- [ ] Test duplicate sync, partial synchronization, delayed Square Orders/Payments, Square transactions during close, refunds, voids, concurrent sold-out protection, authorized oversell, reservation/pickup/cancellation disposition, payout allocation across sessions, close exceptions, the ADMIN/MANAGER/VIEWER permissions, and no duplicate accepted facts or allocations. Do not test local sale submission or cash counting because those occur in Square outside MBS.
- [ ] Test that an incomplete or unapproved closeout remains visible and does not silently disappear from market reporting.
