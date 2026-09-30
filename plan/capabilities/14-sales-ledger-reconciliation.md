# Capability 14: Sales Ledger & Reconciliation

- [ ] **Capability complete** (all features below checked)

Bounded context: `src/mbs/sales/`. Owns the canonical sales facts and financial reconciliation across Square and manually entered cash/other sales. Square API transport and raw staging belong to Capability 3; product costs to Capability 4; market identity/visits to Capability 5; tax workpapers to Capability 12.

## Feature 14.1 — Canonical Sales Model
- [ ] Feature complete
- [ ] Maintain one canonical sales-line model for Square and manual sources, with source type, immutable source identity, Variation ID, quantity, sale timestamp, business date, market or non-market channel, gross/discount/tax amounts, status, refund links, and audit fields.
- [ ] Enforce source-specific database uniqueness: Square Order ID + Line Item UID for Square lines; an immutable event/idempotency ID for manual lines. Keep manual source identity distinct and never create a second Square fact from Payments.
- [ ] Store the accepted effective product cost, cost version/source, market/channel assignment, and COGS snapshot on each accepted line. Later master-data changes do not silently rewrite accepted sale history.
- [ ] Provide shared read/query services for dashboards, inventory, and tax workpapers while retaining the source type and source-document links.

## Feature 14.2 — Square Line Acceptance
- [ ] Feature complete
- [ ] Promote staged Square order lines from Capability 3 only when the Variation ID has a Product Setup record and effective product cost for the sale date, and the Location ID/date resolves to a dated market visit or explicit non-market channel. For a market assignment, the Square sale timestamp must also fall within that market's effective-dated local operating hours from Capability 5, unless an authorized exception is recorded.
- [ ] Show `PROVIDER_PENDING` only when a provider identity has been registered and can be correlated to a later Square Order. A separate Square POS transaction without that identity is not a locally captured fact: show sync watermark/staleness until imported. If its Location/date/hours match multiple sessions or none, retain an import exception for authorized assignment; do not invent a pending amount, guess the session, or mark it settled.
- [ ] Accept passing lines and keep failing lines in a visible `IMPORT_EXCEPTION` queue with reason, source IDs, and retry history; one failing line must not block other passing lines. Corrected exceptions can be promoted idempotently.
- [ ] Persist an accepted line, resolved market/channel, effective-cost/COGS snapshot, and source links in one database transaction protected by the source uniqueness constraint.
- [ ] Square refunds/returns reverse financial sales amounts but never restock inventory automatically. Any physically returned/resalable quantity requires a separate audited manual stock adjustment linked to the refund/return.

## Feature 14.3 — Manual Non-Square Sales
- [ ] Feature complete
- [ ] Provide MANAGER+ create, review, and audited correction for cash and other non-Square sales, linked to a Variation ID, sale date/time, market visit or explicit non-market channel, quantity, gross amount, discount, tax collected, tender type, and optional external reference.
- [ ] Capability 16 may use the same service for an authorized market helper, but cannot bypass its validation or audit rules.
- [ ] Accept a manual sale only when its Variation ID, effective product cost for the sale date, and market/channel resolve; otherwise retain it as an unposted draft/exception that does not affect sales, inventory, or tax totals.
- [ ] Record refunds/returns and corrections as linked events without overwriting the original sale. Require an idempotency key and prevent retries from duplicating a manual fact or an associated Square Order.
- [ ] Refunds/returns never restock inventory automatically; physically returned/resalable quantities use a separate audited stock adjustment.
- [ ] Provide `POST/GET /api/v1/sales/manual` and correction/refund endpoints with role checks, validation, source lineage, and audit history.

## Feature 14.4 — Payments, Fees & Reconciliation
- [ ] Feature complete
- [ ] Join Square Payments to canonical Square Orders for tender, refunds, and actual processing fees; handle multiple tenders and partial refunds idempotently without creating sales facts from Payment records.
- [ ] If actual fee details are unavailable, calculate a clearly labeled effective-dated estimate using `(gross × square_fee_rate) + (transaction count × square_fee_fixed_amount)`; keep estimated and actual fees separate.
- [ ] Reconcile order amounts, discounts, refunds, Square-reported tax, Payments, and net deposits. This is transaction reconciliation only; taxability decisions, liability calculations, and filing workpapers remain in Capability 12.
- [ ] Allocate Square payouts to one or more market sessions using retained order/payment identities. Model operational close separately from settlement reconciliation so delayed, partial, or multi-session payouts remain visible exceptions rather than blocking cash closeout or being treated as settled.
- [ ] Reconcile manual cash/other sales separately from Square settlement totals and include both sources in common business reporting and tax-source queries.
- [ ] Accept market-session metadata, device/session identity, and source-event idempotency keys from Capability 16; these identify the operational capture context but never replace the canonical sale identity.
- [ ] Before MVP 2 implementation, approve the Square POS-to-session correlation workflow (D-16) and the shared stock source-event contract (D-17) in the go/no-go decision sheet; test late/unmatched provider Orders and one physical stock effect per accepted sale.

## Feature 14.5 — Sales Exceptions & Tests
- [ ] Feature complete
- [ ] Track exception state transitions, reason codes, source identity, attempted retries, and resolution in the sales import log; distinguish rejected/duplicate, unresolved, accepted, cancelled, and refunded states.
- [ ] Provide `GET /api/v1/sales` with pagination, date/source/market filters, `GET /api/v1/sales/exceptions`, and MANAGER+ `POST /api/v1/sales/exceptions/{id}/retry`; failed retries retain their reason/history and cannot create duplicate facts.
- [ ] Test per-line readiness, partial batch acceptance, exception replay, Square order update/refund idempotency, manual-sale posting/correction/refund, cross-source duplicate prevention, immutable cost/market snapshots, and no automatic inventory restock on refunds.
- [ ] Test full-year date validation, multi-year effective periods, annual schedule expansion, inclusive/exclusive opening and closing boundaries, seasonal schedule changes, timezone and daylight-saving transitions, closed dates, out-of-hours Square sales, and authorized assignment exceptions without rewriting historical market attribution.
