# Capability 14: Sales Ledger & Reconciliation

Database: PostgreSQL only; see [D-77](../00-overview.md#postgresql-contract-all-stages).
- [ ] Test concurrent order/line uniqueness, Numeric totals/refunds, immutable cost/market snapshots, full-date/DST attribution, atomic late-event reconciliation without duplicate sales.

- [ ] **Capability complete** (all features below checked)

Bounded context: `src/mbs/sales/`. Owns canonical Square facts/reconciliation; Square POS records all sales, including cash. Cap 3 owns transport/staging, Cap 4 costs, Cap 5 markets/visits, Cap 12 tax workpapers.

## Feature 14.1 — Canonical Sales Model
- [ ] Feature complete
- [ ] Store each canonical line's immutable provider identity, Variation ID, quantity, sale/business dates, market/channel, gross/discount/tax, tender, status, refund links, and audit.
- [ ] Enforce database uniqueness on Square Order ID + Line Item UID. Payments supplement Orders and never create a second Square fact.
- [ ] Store the accepted effective product cost, cost version/source, market/channel assignment, and COGS snapshot on each accepted line. Later master-data changes do not silently rewrite accepted sale history.
- [ ] Provide shared dashboard/inventory/tax queries retaining source type/document links.

## Feature 14.2 — Square Line Acceptance
- [ ] Feature complete
- [ ] Accept staged lines only with product/effective cost and resolved Location/date plus Attended/Partial visit or non-market channel. Planned/Not Attended/Excluded is not attendance; hold pending outcome/audited attribution. Market lines must fit effective local hours or have authorized exception. Close alone does not invalidate late valid orders (D-19).
- [ ] Show `PROVIDER_PENDING` only when a provider identity has been registered and can be correlated to a later Square Order. A separate Square POS transaction without that identity is not a locally captured fact: show sync watermark/staleness until imported. If its Location/date/hours match multiple sessions or none, retain an import exception for authorized assignment; do not invent a pending amount, guess the session, or mark it settled.
- [ ] Accept passing lines and keep failing lines in a visible `IMPORT_EXCEPTION` queue with reason, source IDs, and retry history; one failing line must not block other passing lines. Corrected exceptions can be promoted idempotently.
- [ ] Persist accepted line, market/channel, effective-cost/COGS snapshot, and source links atomically under provider uniqueness. In that transaction, request the corresponding stock movement through Capability 6's ledger writer using the accepted-line source key; do not mutate inventory tables directly.
- [ ] Square refunds/returns reverse financial sales amounts but never restock inventory automatically. Any physically returned/resalable quantity requires a separate audited manual stock adjustment linked to the refund/return.

## Feature 14.3 — Manual Non-Square Sales
- [ ] **Deferred outside the current application scope:** MBS does not create, edit, or post manual non-Square sales. Every actual sale is entered in the Square app/POS and imported through Capability 3. If this policy changes, it requires a new owner decision and a plan revision before any implementation.

## Feature 14.4 — Payments, Fees & Reconciliation
- [ ] Feature complete
- [ ] Join Square Payments to canonical Square Orders for tender, refunds, and actual processing fees; handle multiple tenders and partial refunds idempotently without creating sales facts from Payment records.
- [ ] If actual fee details are unavailable, calculate a clearly labeled effective-dated estimate using `(gross × square_fee_rate) + (transaction count × square_fee_fixed_amount)`; keep estimated and actual fees separate.
- [ ] Reconcile order amounts, discounts, refunds, Square-reported tax, Payments, and net deposits. This is transaction reconciliation only; taxability decisions, liability calculations, and filing workpapers remain in Capability 12.
- [ ] Allocate Square payouts to one or more market sessions using retained order/payment identities. Model operational close separately from settlement reconciliation so delayed, partial, or multi-session payouts remain visible exceptions rather than blocking cash closeout or being treated as settled.
- [ ] Reconcile Square tender and settlement data from the provider without counting physical cash in MBS.
- [ ] Accept market-session metadata, device/session identity, and source-event idempotency keys from Capability 16; these identify the operational capture context but never replace the canonical sale identity.
- [ ] Before MVP 2 implementation, use the approved Square data-attribution workflow (D-16) and shared stock source-event contract (D-17); test late/unmatched provider Orders and one physical stock effect per accepted imported Square line.

## Feature 14.5 — Sales Exceptions & Tests
- [ ] Feature complete
- [ ] Track exception state transitions, reason codes, source identity, attempted retries, and resolution in the sales import log; distinguish rejected/duplicate, unresolved, accepted, cancelled, and refunded states.
- [ ] Provide `GET /api/v1/sales` with pagination, date/source/market filters, `GET /api/v1/sales/exceptions`, and MANAGER+ `POST /api/v1/sales/exceptions/{id}/retry`; failed retries retain their reason/history and cannot create duplicate facts.
- [ ] Test per-line readiness, partial batch acceptance, exception replay, Square order update/refund idempotency, immutable cost/market snapshots, and no automatic inventory restock on refunds.
- [ ] Test full-year date validation, multi-year effective periods, annual schedule expansion, inclusive/exclusive opening and closing boundaries, seasonal schedule changes, timezone and daylight-saving transitions, closed dates, out-of-hours Square sales, and authorized assignment exceptions without rewriting historical market attribution.
