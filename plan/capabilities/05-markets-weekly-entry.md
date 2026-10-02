# Capability 5: Markets & Weekly Operations

Database: PostgreSQL only; see [D-77](../00-overview.md#postgresql-contract-all-stages).
- [ ] Test full/open dates, overlap races, visit identity, exact route allocation, and atomic declarative production/expense corrections in independent sessions.

- [ ] **Capability complete** (all features below checked)

Bounded context: `src/mbs/markets/` (blueprint §3.1 #3, Modules 6–8). Owns markets/costs, visits, routes, weekly production, expenses, and assets. Under D-60, Capability 5 alone owns the MVP 3 `Made N` event service and its corrections/movements; Capabilities 15, 16, and 5 weekly entry call it. Shopping/prep lists belong to Capability 15.

## Feature 5.1 — Market Master
- [ ] Feature complete
- [ ] MVP 2 prerequisite: establish the minimal Market ID, Square Location ID mapping, and dated market-visit records for the Square sales history to be imported. MVP 5 adds the full market administration and weekly operations UI; do not accept sales for unmapped dates/locations before then.
- [ ] Maintain a stable `tblMarketDirectory` with Market ID/name, active status, and Square Location ID mapping. MVP 2 uses this directory plus dated visit records for sale-assignment preflight; selecting a market must not require retyping or create duplicate IDs.
- [ ] Maintain reusable, effective-dated regular operating-hour periods for each market, including local open time, local close time, and full-year start/end dates. For example, a market may operate 09:00–12:00 from `2026-07-01` through `2026-08-31` and 09:00–14:00 from `2026-09-01` onward with a blank end date. A blank end date means the period remains effective indefinitely until explicitly closed by a later period; allow at most one open-ended period and reject overlaps. Support schedules spanning multiple calendar years, and do not use the current schedule to reinterpret historical sales.
- [ ] Market Master hours define when a market normally operates; they never create, schedule, or imply attendance for any date. Record a market visit only when the user explicitly adds that market to a complete business date.
- [ ] Allow a market to have a closed/exception date or an attendance override for a dated visit. A sale timestamp must match both the mapped Square Location/market and an active operating-hour period for that market date, unless an authorized exception is recorded.
- [ ] `tblMarketMaster` stores date-effective market-cost rows keyed by Market ID, with Market Cost, Cost Start Date, and nullable Cost End Date. Require a start date; a blank end date means no known end/open period.
- [ ] The full market-cost creation UI requires Market Cost and Cost Start Date and allows Cost End Date to remain blank. Adding a new cost period closes the prior period and creates a new row; never overwrite historical costs. Cost-period management may follow the minimal MVP 2 directory/visit setup.
- [ ] Resolve the market cost for a visit where `Cost Start Date <= Market Date <= Cost End Date`, treating a blank end date as open-ended. Validate start <= end and reject overlapping periods or multiple open periods for the same market.
- [ ] Resolve operating hours for a visit where full `Hours Start Date <= Market Date <= Hours End Date`, treating a blank end date as open-ended. Validate complete year-bearing dates, start <= end, and reject overlapping periods or ambiguous annual expansions. D-01 is approved: one configurable `business_timezone`, seeded `America/New_York`, governs all market hours and business dates; per-market timezones are not active unless a later decision and migration permit them. Assign overnight sessions an explicit visit business date, resolve source UTC instants through the approved zone, reject nonexistent local times, and disambiguate repeated DST times. Display stored instants in the user's browser timezone with a visible label.
- [ ] Visits may record actual fee override; otherwise use date-effective market cost and retain source period/actual/default status.
- [ ] Enforce immutability rule (Governance Rule 2): never edit a historical row; end-date the current row and insert a new one to change defaults.
- [ ] `GET/POST /api/v1/markets`, `POST /api/v1/markets/{market}/end-date` per blueprint §9.3 (ADMIN for writes).
- [ ] Create `tblRouteDistance` with one-way miles keyed by directed origin/destination location pair (including the user's Home location); persist entry source, effective dates, and audit history. A known leg such as Market A → Market B is looked up and reused, not re-entered on each weekly visit.
- [ ] Provide route-distance lookup/create/update APIs; creating a new directed leg requires MANAGER+, while changing an existing leg is audited and effective-dated.

## Feature 5.2 — Weekly Market Entry
- [ ] Feature complete
- [ ] `tblWeeklyMarkets`: one user-created visit per market/date with date, week start, attendance/status, score/notes, optional fee override, cost period, and Test Record. Allow valid past/future dates and multiple markets/day. Schedules do not create attendance; future visits stay Planned. Preserve market/date for history/rankings.
- [ ] Give every market visit an immutable `market_visit_id` and enforce one visit per Market ID plus complete local business date. Migrating or replaying an MVP 2 dated visit must reuse that identity and preserve linked sales, prep, and session records; a conflicting duplicate is rejected rather than creating a second fee or attendance fact.
- [ ] Link an optional Capability 16 market-day selling session and retain its open/close status, close exception state, and responsible operator without duplicating the visit or sales record.
- [ ] Use a searchable dropdown backed by the distinct saved Market IDs/names in Market Master; selecting a market reuses its existing identity and loads the cost period effective for the selected visit date. Do not require retyping market details or create a duplicate market record from weekly entry.
- [ ] Provide an `Add market` action for a genuinely new market that opens the Market Master creation flow, then returns to the weekly entry with the new market selected.
- [ ] Attendance Category derivation: `Attended`, `Partial Day` (arrived late or left early), `Excluded` (`Vacation`, `Cancelled`, `Family`, `Personal`, `Sick`, `Emergency`), or `Not Attended` per D-18.
- [ ] Provide an explicit remove/cancel action for a market on a date. Cancellation sets the visit to Cancelled/Excluded, removes it from active attendance and route/travel calculations, and preserves the immutable visit identity and audit history. Never delete or deactivate the Market Master record; retain linked sales, prep, and session records and require audited correction/resolution rather than silently deleting or reassigning them.
- [ ] Deliver visit cancellation and linked-history correction with the MVP 5 weekly-operations UI, not the MVP 2 minimal visit setup. MVP 2 must still reject duplicate Market ID/date visits and preserve a stable identity for later cancellation (MKT001); test cancellation in `markets-mvp` through `tests/test_market_visits.py::test_cancel_visit`.
- [ ] Capability 15 owns one `MarketPlan` from MVP 2 through MVP 4 (D-47/48/51). Capability 5 supplies referenced markets, visits, and hours; it creates no second plan. Store weekday, local times, chosen date; default to next weekday in `business_timezone`; edits affect this plan only, never Market Master/other plans.
- [ ] `GET/POST /api/v1/markets/weekly`, `PUT /api/v1/markets/weekly/{id}` per blueprint §9.3; support filtering by date range and market.
- [ ] Capture the ordered markets visited on each market date. For each market after the first, ask whether the user returned Home before traveling to it or went directly from the prior market.
- [ ] Build the day's route legs from Home through the ordered markets and back Home; resolve saved directed distances automatically, prompting for a one-way distance only when a required directed leg is not yet known. Save new legs for reuse on later entries.

## Feature 5.3 — Travel Cost Calculation
- [ ] Feature complete
- [ ] `Actual Trip Miles = SUM(one-way route legs)`; `Travel Cost = miles × Mileage Rate`. Single market: Home→Market→Home; multi-market follows chosen itinerary.
- [ ] Every day's final route leg returns to Home. For a single-market day, include both Home → Market and Market → Home one-way legs in that market's travel distance/cost.
- [ ] For multi-market days, allocate each leg to the destination market and the final return-Home leg to the last market visited; total market allocations must equal the trip total and must never charge the full trip total to every market. Preserve the leg-level source and calculation for audit.
- [ ] Apply the mileage rate effective on the market date (`mileage_rate`, initial default $0.67/mile); preserve historical cost results when the current rate changes (Capability 9).
- [ ] Show each leg, its saved or newly entered one-way distance, itinerary choice, total miles, and calculated travel cost. Refresh totals when route order, home/direct choice, or an entered distance changes.
- [ ] Allow audited one-time distance override without changing default; separately offer saving it as a new effective-dated route.
- [ ] Test single-market, direct multi-market, and return-home itineraries, asserting that every final leg returns Home, the sum of market allocations equals the calculated trip cost exactly, and later mileage-rate changes do not alter finalized trips.

## Feature 5.4 — Weekly Production Entry
- [ ] Feature complete
- [ ] Extend the MVP 3 idempotent `Made N` event keyed by source identity, period, Variation ID, and entry identity with actual produced quantity, notes/exception reason, source, and Test Record flag. Capability 15 recipe-aware confirmations and MVP 5 weekly corrections use the same event ID and ledger; a plan target is not a production event (D-53).
- [ ] D-63: MVP 3 creates production after recipes exist; confirmation posts finished units and consumes effective recipe ingredients/supplies atomically. MVP 4 adds persisted fractional remainder and audited correction/reversal; MVP 5 adds weekly UI to the same service/history (PC-001). No provisional cost-only production.
- [ ] Enforce a database unique source-event key; commit the production event, ingredient/product/supply movements, and fractional-waste remainder in one transaction. Retried confirmations return the existing result; a failed transaction leaves none of these effects posted.
- [ ] D-64: one declarative quantity per Variation ID/business date; re-entry replaces total (15→16 means 16), never adds or creates another same-day event. No add-batch control. Append audited delta (actor/time/reason), hide delta from UI, and adjust recipe inputs/supplies/waste remainder atomically. Closed-period edits restate production date per D-57(d).
- [ ] Provide manual entry/correction through the shared production-event service. Pass the validated event to Capability 6's writer for `tblInventory.Produced`/stock movements; do not write the stock ledger directly or aggregate twice. Corrections append a linked reversal/replacement or adjustment.
- [ ] Keep samples as a separately recorded inventory movement so they are not confused with produced or sold units.
- [ ] Provide `GET/POST /api/v1/production/weekly` and `PUT /api/v1/production/weekly/{id}` with MANAGER+ write authorization.

## Feature 5.5 — Business Expense Entry
- [ ] Feature complete
- [ ] Create `tblExpenses` with expense date, amount, category, description, canonical `store_id` when the expense has a purchase source, optional market/week allocation, receipt and receipt-item links, entry source (OCR/manual), approval audit, and Test Record flag.
- [ ] Enforce a unique immutable provenance key for each receipt-item expense and manual expense event. Approval, retry, or correction appends a linked reversal/replacement instead of creating a second net expense.
- [ ] Preserve the accepted receipt-line occurrence and originating PDF/page/line as separate expense provenance. A duplicate source PDF contributes no expense; an approved supplemental occurrence may contribute exactly one new expense even when its merchant item number matches a prior line. Personal/non-business lines remain excluded, and corrections use linked reversal/replacement instead of a second charge (RM-022).
- [ ] Provide manual expense entry and correction using the same validation and audit rules as OCR-reviewed expense lines.
- [ ] Include approved business expenses in the appropriate reporting period; ingredient purchases remain separate cost/inventory inputs to avoid counting purchases again on top of COGS.
- [ ] Allow valid expenses to remain unallocated to a market and surface them as unallocated rather than silently dropping them from business totals.
- [ ] Exclude ingredient purchases, Square fees, and market fees already recognized from duplicate posting as generic expenses; support `GET/POST /api/v1/expenses` and `PUT /api/v1/expenses/{id}` with MANAGER+ write authorization.
- [ ] Test OCR approval retry, concurrent approval, manual submission retry, correction, and cross-path duplicate attempts, proving one net expense and retained source lineage.

## Feature 5.6 — Capital Asset / Equipment Tracking
- [ ] Feature complete
- [ ] Create `tblBusinessAssets` for equipment and other capital assets with description, vendor, acquisition date/cost, receipt and receipt-line links, asset category, serial/model, placed-in-service date, useful life, depreciation method, status, and audit history.
- [ ] Route receipt lines classified as Capital Asset / Equipment to a reviewable asset draft, not an ordinary operating expense; allow manual asset entry through the same service.
- [ ] Require authorized confirmation of capitalization and organization accounting policy before posting depreciation; do not infer tax treatment or silently expense the full purchase.
- [ ] Provide asset list/detail and `GET/POST /api/v1/assets`, `PUT /api/v1/assets/{id}` with MANAGER+ write authorization.
