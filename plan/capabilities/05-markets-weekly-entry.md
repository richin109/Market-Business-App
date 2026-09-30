# Capability 5: Markets & Weekly Operations

- [ ] **Capability complete** (all features below checked)

Bounded context: `src/mbs/markets/` (blueprint §3.1 #3, Modules 6–8). Owns market directory/cost history, dated visits, route costs, weekly production, expenses, and asset records. Market shopping lists and prep confirmation belong to Capability 15.

## Feature 5.1 — Market Master
- [ ] Feature complete
- [ ] MVP 2 prerequisite: establish the minimal Market ID, Square Location ID mapping, and dated market-visit records for the Square sales history to be imported. MVP 5 adds the full market administration and weekly operations UI; do not accept sales for unmapped dates/locations before then.
- [ ] Maintain a stable `tblMarketDirectory` with Market ID/name, active status, and Square Location ID mapping. MVP 2 uses this directory plus dated visit records for sale-assignment preflight; selecting a market must not require retyping or create duplicate IDs.
- [ ] Maintain effective-dated regular operating-hour periods for each market, including local open time, local close time, and full-year start/end dates. For example, a market may operate 09:00–12:00 from `2026-07-01` through `2026-08-31` and 09:00–14:00 from `2026-09-01` through `2027-06-30`. Require non-overlapping explicit dates, support schedules spanning multiple calendar years, and do not use the current schedule to reinterpret historical sales.
- [ ] Allow a market to have a closed/exception date or an attendance override for a dated visit. A sale timestamp must match both the mapped Square Location/market and an active operating-hour period for that market date, unless an authorized exception is recorded.
- [ ] `tblMarketMaster` stores date-effective market-cost rows keyed by Market ID, with Market Cost, Cost Start Date, and nullable Cost End Date. Require a start date; a blank end date means no known end/open period.
- [ ] The full market-cost creation UI requires Market Cost and Cost Start Date and allows Cost End Date to remain blank. Adding a new cost period closes the prior period and creates a new row; never overwrite historical costs. Cost-period management may follow the minimal MVP 2 directory/visit setup.
- [ ] Resolve the market cost for a visit where `Cost Start Date <= Market Date <= Cost End Date`, treating a blank end date as open-ended. Validate start <= end and reject overlapping periods or multiple open periods for the same market.
- [ ] Resolve operating hours for a visit where full `Hours Start Date <= Market Date <= Hours End Date`, treating a blank end date as open-ended. Validate complete year-bearing dates, start <= end, reject overlapping periods or ambiguous annual expansions, and interpret open/close times in the market's configured IANA timezone before converting Square timestamps to the business date.
- [ ] Weekly visits may record an actual market-fee override; otherwise use the effective-dated market cost for that visit date and retain the source period/actual-vs-default status.
- [ ] Enforce immutability rule (Governance Rule 2): never edit a historical row; end-date the current row and insert a new one to change defaults.
- [ ] `GET/POST /api/v1/markets`, `POST /api/v1/markets/{market}/end-date` per blueprint §9.3 (ADMIN for writes).
- [ ] Create `tblRouteDistance` with one-way miles keyed by directed origin/destination location pair (including the user's Home location); persist entry source, effective dates, and audit history. A known leg such as Market A → Market B is looked up and reused, not re-entered on each weekly visit.
- [ ] Provide route-distance lookup/create/update APIs; creating a new directed leg requires MANAGER+, while changing an existing leg is audited and effective-dated.

## Feature 5.2 — Weekly Market Entry
- [ ] Feature complete
- [ ] `tblWeeklyMarkets`: one dated market-visit record per market occurrence, with Market Date, week-start date, attendance/status, score, notes, optional actual market-fee override, resolved market-cost period, and Test Record. Preserve the visit date and market so history and rankings can show which markets were actually done and when.
- [ ] Give every market visit an immutable `market_visit_id` and enforce one visit per Market ID plus complete local business date. Migrating or replaying an MVP 2 dated visit must reuse that identity and preserve linked sales, prep, and session records; a conflicting duplicate is rejected rather than creating a second fee or attendance fact.
- [ ] Link an optional Capability 16 market-day selling session and retain its open/close status, close exception state, and responsible operator without duplicating the visit or sales record.
- [ ] Use a searchable dropdown backed by the distinct saved Market IDs/names in Market Master; selecting a market reuses its existing identity and loads the cost period effective for the selected visit date. Do not require retyping market details or create a duplicate market record from weekly entry.
- [ ] Provide an `Add market` action for a genuinely new market that opens the Market Master creation flow, then returns to the weekly entry with the new market selected.
- [ ] Attendance Category derivation: Attended / Excluded (Vacation, Cancelled, etc.) per blueprint Module 7 rules.
- [ ] `GET/POST /api/v1/markets/weekly`, `PUT /api/v1/markets/weekly/{id}` per blueprint §9.3; support filtering by date range and market.
- [ ] Capture the ordered markets visited on each market date. For each market after the first, ask whether the user returned Home before traveling to it or went directly from the prior market.
- [ ] Build the day's route legs from Home through the ordered markets and back Home; resolve saved directed distances automatically, prompting for a one-way distance only when a required directed leg is not yet known. Save new legs for reuse on later entries.

## Feature 5.3 — Travel Cost Calculation
- [ ] Feature complete
- [ ] Formula: `Actual Trip Miles = SUM(one-way miles for each route leg)` and `Travel Cost = Actual Trip Miles × Mileage Rate`. A single-market day is Home → Market → Home; multi-market days follow the selected direct/home itinerary.
- [ ] Every day's final route leg returns to Home. For a single-market day, include both Home → Market and Market → Home one-way legs in that market's travel distance/cost.
- [ ] For multi-market days, allocate each leg to the destination market and the final return-Home leg to the last market visited; total market allocations must equal the trip total and must never charge the full trip total to every market. Preserve the leg-level source and calculation for audit.
- [ ] Apply the mileage rate effective on the market date (`mileage_rate`, initial default $0.67/mile); preserve historical cost results when the current rate changes (Capability 9).
- [ ] Show each leg, its saved or newly entered one-way distance, itinerary choice, total miles, and calculated travel cost. Refresh totals when route order, home/direct choice, or an entered distance changes.
- [ ] Allow an audited one-time actual-distance override for a leg without overwriting the saved default; offer an explicit action to save that actual as a new effective-dated route distance.
- [ ] Test single-market, direct multi-market, and return-home itineraries, asserting that every final leg returns Home, the sum of market allocations equals the calculated trip cost exactly, and later mileage-rate changes do not alter finalized trips.

## Feature 5.4 — Weekly Production Entry
- [ ] Feature complete
- [ ] Create production events keyed by event/source identity, period, Variation ID, and entry identity with produced quantity, notes/exception reason, entry source, and Test Record flag. Capability 15 prep confirmations and manual weekly entries/corrections use this same ledger/service.
- [ ] Deliver this shared production-event service as an explicit MVP 4 prerequisite; MVP 5 extends it with weekly entry UI and corrections but must not create a second production ledger.
- [ ] Enforce a database unique source-event key; commit the production event, ingredient/product/supply movements, and fractional-waste remainder in one transaction. Retried confirmations return the existing result; a failed transaction leaves none of these effects posted.
- [ ] Provide manual entry and audited correction through the shared production-event service; validated production quantities feed `tblInventory.Produced` for the matching week without duplicate aggregation. Corrections append a reversal/replacement or an explicit adjustment; they do not duplicate the original event.
- [ ] Keep samples as a separately recorded inventory movement so they are not confused with produced or sold units.
- [ ] Provide `GET/POST /api/v1/production/weekly` and `PUT /api/v1/production/weekly/{id}` with MANAGER+ write authorization.

## Feature 5.5 — Business Expense Entry
- [ ] Feature complete
- [ ] Create `tblExpenses` with expense date, amount, category, description, optional market/week allocation, receipt and receipt-item links, entry source (OCR/manual), approval audit, and Test Record flag.
- [ ] Enforce a unique immutable provenance key for each receipt-item expense and manual expense event. Approval, retry, or correction appends a linked reversal/replacement instead of creating a second net expense.
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
