# Capability 16: Market-Day Selling & POS Operations

- [ ] **Capability complete** (all features below checked)

Bounded context: `src/mbs/market_day/`. Owns the operational selling workflow at a market stall. It uses Capability 14 for canonical sales, Capability 4 for products/prices, Capability 5 for the market visit, a narrow MVP 2 session-allocation service for availability, and Capability 9 for settings and permissions. Capability 6 later extends the same allocation/movement interface into the full inventory engine; it must not introduce a parallel availability ledger. This capability does not create a second sales ledger or replace Square's payment processing.

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
- Apply a session price override only to a manual tender, or require the identical audited price/discount to be created in Square before accepting the Square sale. A local override must never make a Square order, payment, tax, or closeout amount differ without a visible reconciliation exception.
- Allow a sale to be held as a draft during a customer interaction and explicitly completed before it affects the accepted ledger.
- Require every completed sale to have product, quantity, amount, tender, market session, business date, and source identity; unresolved entries remain visible exceptions.
- Treat a Square transaction as `PROVIDER_PENDING` until its Order fact has been durably staged and accepted by Capability 14. The market session may show a pending estimated tender total, but it must not represent that total as reconciled or settled.

## Feature 16.3 — Connectivity & Synchronization
- [ ] Feature complete
- Decide and document the supported operating mode before production: Square remains the online transactional POS, or this interface supports an offline queue with later synchronization.
- Before MVP 2 production, approve the quantitative targets in [the implementation-readiness gate](../02-implementation-readiness.md) for sale acknowledgement, provider synchronization delay, outage duration, and device/browser recovery. The selected operating mode and targets are release-profile inputs; absence of an approved value blocks production promotion.
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
- Separate `OPERATIONALLY_CLOSED` from `SETTLEMENT_RECONCILED`. An operational close may retain visibly pending Square orders/payments and unresolved reconciliation exceptions; it becomes settlement reconciled only after the configured provider-import and payout-allocation conditions pass.
- Produce a market close summary showing units sold, gross sales, discounts, tax collected, refunds, tender totals, fees where known, cash variance, and unresolved exceptions.
- Require close exceptions to be resolved or explicitly approved before the market visit is considered settlement reconciled. Record the approver, reason, pending provider identities, and follow-up state for an approved exception.

## Feature 16.5 — Availability, Preorders & Customer Pickup
- [ ] Feature complete
- Use the MVP 2 session-allocation service to atomically reserve, commit, reverse, and explicitly dispose of quantities by market session. Show sold-out and reserved quantities and prevent confirmed sales from exceeding available quantity unless an authorized oversell is recorded. Every allocation event has a source identity and idempotency key; Capability 6 consumes or extends these events rather than recreating stock facts.
- Support optional preorder/reservation records linked to a market visit, customer contact, requested products, quantity, payment/deposit status, pickup status, substitutions, and cancellation.
- Keep customer contact data consent-aware and access-controlled; do not require customer accounts for an in-person sale.
- Mark pickup orders collected, partially collected, cancelled, or unclaimed; report unclaimed inventory for an explicit disposition.
- Keep preorder fulfillment and deposits traceable to the canonical sales/refund records without counting a deposit and final sale twice. A reservation holds session allocation until pickup, cancellation, or an explicit end-of-day disposition.

## Feature 16.6 — Stall Readiness & Customer Information
- [ ] Feature complete
- Provide a pre-open checklist for device/payment readiness, cash float, products, packaging, labels/signage, samples, permits/documents, and emergency supplies.
- Provide a printable or display-mode price list for the selected market session, including product name, unit, price, availability, and approved customer-facing descriptions.
- Products may expose approved ingredient, allergen, storage, best-by, batch/production-date, and preparation information when applicable; do not expose internal margin or cost data.
- Record market-day observations such as weather, foot traffic, promotion, competitor notes, and operational incidents separately from financial facts.
- Provide an end-of-day packing and equipment checklist, including damaged, returned, donated, or discarded stock as explicit session-allocation disposition events. Capability 6 later maps these events to the full inventory movement model.

## Feature 16.7 — APIs, Permissions & Tests
- [ ] Feature complete
- Provide session, cart/draft, completed-sale, tender-control, closeout, availability, preorder, and checklist endpoints with role checks and CSRF protection for browser actions.
- Use Capability 14's canonical sale and refund services, the shared session-allocation/inventory-movement interface, and Capability 5's dated market visit; this capability must not write parallel sales or inventory tables.
- Test rapid repeated submissions, browser refresh, duplicate sync, offline recovery, partial synchronization, delayed Square Orders/Payments, Square transactions during close, refunds, voids, session price overrides for both Square and manual tenders, concurrent sold-out protection, authorized oversell, reservation/pickup/cancellation disposition, cash over/short, payout allocation across sessions, close exceptions, helper permissions, and no duplicate accepted facts or allocations.
- Test that an incomplete or unapproved closeout remains visible and does not silently disappear from market reporting.
