# Capability 16: Market-Day Selling & POS Operations

- [ ] **Capability complete** (all features below checked)

Bounded context: `src/mbs/market_day/`. Owns the operational selling workflow at a market stall. It uses Capability 14 for canonical sales, Capability 4 for products/prices, Capability 5 for the market visit, Capability 6 for availability, and Capability 9 for settings and permissions. It does not create a second sales ledger or replace Square's payment processing.

## Feature 16.1 — Market-Day Session
- [ ] Feature complete
- Create one market-day selling session linked to a dated market visit, business timezone, operator, and device/session identifier.
- Record session status: OPEN, PAUSED, CLOSED, or CLOSE_EXCEPTION. Prevent sales after close unless an audited correction or reopening is authorized.
- Show only products configured for the selected market session, with current price, tax treatment, available quantity/status, and customer-facing name.
- Support a fast mobile-responsive interface with product search, favorites/tiles, quantity controls, notes, and minimal typing.
- Allow authorized stall helpers to sell without granting access to settings, tax packages, credentials, or unrelated administration.

## Feature 16.2 — Sale Capture & Tender
- [ ] Feature complete
- Capture Square-originated sales through Capability 14 without creating a duplicate local sale fact.
- Capture cash, check, other-card, and other-tender sales locally through the Capability 14 manual-sale service with a per-sale idempotency key.
- Support quantity changes, line discounts, order discounts, refunds, voids, and corrections as linked events; never overwrite the original sale.
- Support a configured market-session price override only with an audit reason and effective session scope; do not mutate the product master price.
- Allow a sale to be held as a draft during a customer interaction and explicitly completed before it affects the accepted ledger.
- Require every completed sale to have product, quantity, amount, tender, market session, business date, and source identity; unresolved entries remain visible exceptions.

## Feature 16.3 — Connectivity & Synchronization
- [ ] Feature complete
- Decide and document the supported operating mode before production: Square remains the online transactional POS, or this interface supports an offline queue with later synchronization.
- If offline queueing is enabled, store an encrypted local queue with a device/session identity, monotonic event sequence, idempotency key, created timestamp, and visible sync status.
- Reconcile queued events after connectivity returns; retries must be idempotent and conflicts must remain visible for review rather than silently merging.
- Make the UI clear about online, offline, pending-sync, failed, and reconciled states. Never claim a sale is settled when only a local queue record exists.
- Provide a controlled recovery path for device loss or browser refresh without duplicating queued sales.

## Feature 16.4 — Cash Control & Market Close
- [ ] Feature complete
- Record opening cash float, authorized cash removals/additions, and the responsible operator.
- Calculate expected tender totals from accepted sales, refunds, and recorded cash movements, separately for each tender type.
- Record counted closing cash and calculate over/short variance with an explanation and manager review threshold.
- Reconcile Square settlement information separately from cash and other non-Square tenders; do not treat a payment-provider deposit as a second sale.
- Produce a market close summary showing units sold, gross sales, discounts, tax collected, refunds, tender totals, fees where known, cash variance, and unresolved exceptions.
- Require close exceptions to be resolved or explicitly approved before the market visit is considered financially closed.

## Feature 16.5 — Availability, Preorders & Customer Pickup
- [ ] Feature complete
- Show sold-out and reserved quantities during the session and prevent confirmed sales from exceeding available quantity unless an authorized oversell is recorded.
- Support optional preorder/reservation records linked to a market visit, customer contact, requested products, quantity, payment/deposit status, pickup status, substitutions, and cancellation.
- Keep customer contact data consent-aware and access-controlled; do not require customer accounts for an in-person sale.
- Mark pickup orders collected, partially collected, cancelled, or unclaimed; report unclaimed inventory for an explicit disposition.
- Keep preorder fulfillment and deposits traceable to the canonical sales/refund records without counting a deposit and final sale twice.

## Feature 16.6 — Stall Readiness & Customer Information
- [ ] Feature complete
- Provide a pre-open checklist for device/payment readiness, cash float, products, packaging, labels/signage, samples, permits/documents, and emergency supplies.
- Provide a printable or display-mode price list for the selected market session, including product name, unit, price, availability, and approved customer-facing descriptions.
- Products may expose approved ingredient, allergen, storage, best-by, batch/production-date, and preparation information when applicable; do not expose internal margin or cost data.
- Record market-day observations such as weather, foot traffic, promotion, competitor notes, and operational incidents separately from financial facts.
- Provide an end-of-day packing and equipment checklist, including damaged, returned, donated, or discarded stock as explicit inventory events.

## Feature 16.7 — APIs, Permissions & Tests
- [ ] Feature complete
- Provide session, cart/draft, completed-sale, tender-control, closeout, availability, preorder, and checklist endpoints with role checks and CSRF protection for browser actions.
- Use Capability 14's canonical sale and refund services, Capability 6's inventory movements, and Capability 5's dated market visit; this capability must not write parallel sales or inventory tables.
- Test rapid repeated submissions, browser refresh, duplicate sync, offline recovery, partial synchronization, refunds, voids, session price overrides, sold-out protection, preorder deposits, pickup status, cash over/short, tender reconciliation, close exceptions, helper permissions, and no duplicate accepted facts.
- Test that an incomplete or unapproved closeout remains visible and does not silently disappear from market reporting.
