# Capability 16: Market-Day Selling & POS Operations

- [ ] **Capability complete** (all features below checked)

Bounded context: `src/mbs/market_day/`. Owns the operational market-session workflow at a market stall. Actual sales are captured in the Square app/POS outside MBS; this capability uses Capability 14 for imported Square sales, Capability 4 for products/prices, Capability 5 for the market visit and for the shared production-event service it calls but never defines (D-60), the single MVP 2 `StockBalanceReader` for availability (D-59), and Capability 9 for settings and permissions. Capability 6 later replaces that reader's implementation behind the same interface; no capability may introduce a parallel availability, production, or sales ledger.

## Feature 16.1 — Market-Day Session
- [ ] Feature complete
- [ ] Create one market-day selling session linked to a dated market visit, business timezone, operator, and device/session identifier.
- [ ] Record OPEN, PAUSED, CLOSE_EXCEPTION, OPERATIONALLY_CLOSED, and SETTLEMENT_RECONCILED with the approved D-03 transition table. Automatically move an OPEN or PAUSED session to `OPERATIONALLY_CLOSED` one hour after its planned close time, but never at or after the next planned market's start; if the next market starts sooner, close immediately before that start. Opening any new market first automatically closes any existing OPEN or PAUSED session and records the actor, time, previous session, new session, and automatic-close reason. A close exception cannot disappear until resolved or approved, and operational close does not imply settlement. A late Square line with unambiguous provider identity, qualifying visit/outcome, location, business date, and operating hours is accepted against its original visit even after close (D-19); only unresolved or ambiguous attribution remains an exception requiring authorized review.
- [ ] Show only products configured for the selected market session, with current price, tax treatment, available quantity/status, and customer-facing name.
- [ ] Show each product's approved primary image as a Square product-reference tile or market display with accessible alternative text from the customer-facing name; a product with no image renders the default placeholder. Serve the D-41 thumbnails (fit inside 320 px, shown at 160 CSS px) and degrade to placeholders if the image store is unavailable rather than blocking market closeout (IM-005).
- [ ] Support a fast session dashboard on phones and computer browsers: compact touch-friendly status and availability controls on mobile, and a desktop layout that uses the wider viewport for Square import status, product availability, settlement exceptions, and closeout without stretching a narrow mobile screen.
- [ ] Use the existing VIEWER role for read-only market-plan, Square-import, availability, and settlement views; MANAGER controls operational plans and exceptions, and ADMIN controls users/settings. Do not add a separate HELPER role in MVP 1–8 (D-12).

## Feature 16.2 — Square Import & Settlement View
- [ ] Feature complete
- [ ] Square POS handles Square checkout in MVP 3; this interface displays imported Square Orders via Capability 14 rather than initiating a second local Square sale. D-16 data attribution is approved; show import-watermark staleness when Square POS has no registered provider identity, and require authorized resolution of unmatched or ambiguous Orders.
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
- [ ] Use one shared allocation command interface to reserve, commit, release, transfer, and dispose of confirmed recipe-made units or Direct Sell receipt-backed stock by ordered market set. It reads availability only through the MVP 2 `StockBalanceReader`, records idempotent allocation/movement commands, and must not calculate a second balance or introduce a session-specific inventory reader (D-59, D-72). The same market screen lists recipe products and offers Square variations marked `Direct Sell` in a dropdown; the user edits the bring target and confirms a market load from available purchased units. A 24-bottle receipt creates 24 units once; confirming "bring 6" reserves 6, leaving 18 unallocated. Square sales reduce the loaded and overall balances once, not once for sale and again for allocation. A Direct Sell load cannot exceed approved receipt-backed available units; hold insufficient/unmapped stock instead of inventing a purchase or made event. Transfer only remaining allocated units, leave the other purchased stock untouched, and require an audited return for refund restocking (D-52/D-53/D-55).
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
- [ ] Include each product's approved primary image, or the default placeholder, in the printable and display-mode lists. No internal cost, margin, supplier, or store data may appear in any customer-facing view, and image provenance metadata is not exposed to customers. Cover IM-005 in [the test-case manifest](../test-case-manifest.csv); planned focused command once implemented: `uv run --frozen pytest tests/test_market_day_product_display.py -q`.
- [ ] Products may expose approved ingredient, allergen, storage, best-by, batch/production-date, and preparation information when applicable; do not expose internal margin or cost data.
- [ ] Record market-day observations such as weather, foot traffic, promotion, competitor notes, and operational incidents separately from financial facts.
- [ ] Provide an end-of-day packing and equipment checklist, including damaged, returned, donated, or discarded stock as explicit session-allocation disposition events. Capability 6 later maps these events to the full inventory movement model.

## Feature 16.7 — APIs, Permissions & Tests
- [ ] Feature complete
- [ ] Provide session, Square-import-status, settlement-status, closeout, availability, preorder, and checklist endpoints with role checks and CSRF protection for browser actions.
- [ ] Use Capability 14's canonical sale and refund services, the shared session-allocation/inventory-movement interface, and Capability 5's dated market visit; this capability must not write parallel sales or inventory tables.
- [ ] Test duplicate sync, partial synchronization, delayed Square Orders/Payments, Square transactions during close, refunds, voids, concurrent sold-out protection, authorized oversell, reservation/pickup/cancellation disposition, payout allocation across sessions, close exceptions, the ADMIN/MANAGER/VIEWER permissions, and no duplicate accepted facts or allocations. Do not test local sale submission or cash counting because those occur in Square outside MBS.
- [ ] Test that an incomplete or unapproved closeout remains visible and does not silently disappear from market reporting.
