# Capability 5: Markets & Weekly Entry

- [ ] **Capability complete** (all features below checked)

Bounded context: `mbs/markets/` (blueprint §3.1 #3, Modules 6–8). Market master defaults, weekly attendance entries, and travel cost calculation.

## Feature 5.1 — Market Master
- [ ] Feature complete
- [ ] MVP 2 prerequisite: establish the minimal Market ID, Square Location ID mapping, and dated market-visit records for the Square sales history to be imported. MVP 5 adds the full market administration and weekly operations UI; do not accept sales for unmapped dates/locations before then.
- [ ] Maintain a stable `tblMarketDirectory` with Market ID/name, active status, and Square Location ID mapping. MVP 2 uses this directory plus dated visit records for sale-assignment preflight; selecting a market must not require retyping or create duplicate IDs.
- [ ] `tblMarketMaster` stores date-effective market-cost rows keyed by Market ID, with Market Cost, Cost Start Date, and nullable Cost End Date. Require a start date; a blank end date means no known end/open period.
- [ ] The full market-cost creation UI requires Market Cost and Cost Start Date and allows Cost End Date to remain blank. Adding a new cost period closes the prior period and creates a new row; never overwrite historical costs. Cost-period management may follow the minimal MVP 2 directory/visit setup.
- [ ] Resolve the market cost for a visit where `Cost Start Date <= Market Date <= Cost End Date`, treating a blank end date as open-ended. Validate start <= end and reject overlapping periods or multiple open periods for the same market.
- [ ] Weekly visits may record an actual market-fee override; otherwise use the effective-dated market cost for that visit date and retain the source period/actual-vs-default status.
- [ ] Enforce immutability rule (Governance Rule 2): never edit a historical row; end-date the current row and insert a new one to change defaults.
- [ ] `GET/POST /api/v1/markets`, `POST /api/v1/markets/{market}/end-date` per blueprint §9.3 (ADMIN for writes).
- [ ] Create `tblRouteDistance` with one-way miles keyed by directed origin/destination location pair (including the user's Home location); persist entry source, effective dates, and audit history. A known leg such as Market A → Market B is looked up and reused, not re-entered on each weekly visit.
- [ ] Provide route-distance lookup/create/update APIs; creating a new directed leg requires MANAGER+, while changing an existing leg is audited and effective-dated.

## Feature 5.2 — Weekly Market Entry
- [ ] Feature complete
- [ ] `tblWeeklyMarkets`: one dated market-visit record per market occurrence, with Market Date, week-start date, attendance/status, score, notes, optional actual market-fee override, resolved market-cost period, and Test Record. Preserve the visit date and market so history and rankings can show which markets were actually done and when.
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

## Feature 5.4 — Weekly Production Entry
- [ ] Feature complete
- [ ] Create production events keyed by event/source identity, period, Variation ID, and entry identity with produced quantity, notes/exception reason, entry source, and Test Record flag. Prep-list confirmations in MVP 4 and manual weekly entries/corrections use this same ledger/service.
- [ ] Provide manual entry and audited correction through the shared production-event service; validated production quantities feed `tblInventory.Produced` for the matching week without duplicate aggregation. Corrections append a reversal/replacement or an explicit adjustment; they do not duplicate the original event.
- [ ] Keep samples as a separately recorded inventory movement so they are not confused with produced or sold units.
- [ ] Provide `GET/POST /api/v1/production/weekly` and `PUT /api/v1/production/weekly/{id}` with MANAGER+ write authorization.

## Feature 5.5 — Business Expense Entry
- [ ] Feature complete
- [ ] Create `tblExpenses` with expense date, amount, category, description, optional market/week allocation, receipt and receipt-item links, entry source (OCR/manual), approval audit, and Test Record flag.
- [ ] Provide manual expense entry and correction using the same validation and audit rules as OCR-reviewed expense lines.
- [ ] Include approved business expenses in the appropriate reporting period; ingredient purchases remain separate cost/inventory inputs to avoid counting purchases again on top of COGS.
- [ ] Allow valid expenses to remain unallocated to a market and surface them as unallocated rather than silently dropping them from business totals.
- [ ] Exclude ingredient purchases, Square fees, and market fees already recognized from duplicate posting as generic expenses; support `GET/POST /api/v1/expenses` and `PUT /api/v1/expenses/{id}` with MANAGER+ write authorization.

## Feature 5.6 — Capital Asset / Equipment Tracking
- [ ] Feature complete
- [ ] Create `tblBusinessAssets` for equipment and other capital assets with description, vendor, acquisition date/cost, receipt and receipt-line links, asset category, serial/model, placed-in-service date, useful life, depreciation method, status, and audit history.
- [ ] Route receipt lines classified as Capital Asset / Equipment to a reviewable asset draft, not an ordinary operating expense; allow manual asset entry through the same service.
- [ ] Require authorized confirmation of capitalization and organization accounting policy before posting depreciation; do not infer tax treatment or silently expense the full purchase.
- [ ] Provide asset list/detail and `GET/POST /api/v1/assets`, `PUT /api/v1/assets/{id}` with MANAGER+ write authorization.

## Feature 5.7 — Market Shopping & Prep List
- [ ] Feature complete
- [ ] Provide a Market Load List for a selected market visit date using the saved Market dropdown; allow entry of product Variation ID and target quantity (for example, 12 of Product X and 10 of Product Y), notes, and prep status.
- [ ] For items marked Perishable, show an editable `Perishable By` date/time defaulted to exactly seven days after the list item's creation timestamp. Leave it blank for non-perishable items; recompute the default when copying a list into a newly created list, while preserving an explicit user override.
- [ ] Save Market Load Lists by market and visit date; allow copying a prior list for the same market and editing quantities without re-entering market details.
- [ ] Include stocked operating supplies such as cups in the store-grouped shopping list with quantity/unit and target-restock threshold; subtract their on-hand balance just like ingredients.
- [ ] For recipe-backed products, calculate expected ingredient and stocked-supply requirements from target product quantities, recipe input quantities, and each input's waste percentage; aggregate shared inputs across the list and include expected waste in net-to-buy estimates. Surface missing recipes or units rather than silently omitting those needs. Planned estimates do not accrue waste or change stock; only confirmed production events do.
- [ ] Subtract on-hand ingredient inventory and create store-grouped Ingredient Shopping Lists using the preferred or selected purchase store/location (for example, BJ's, Walmart); allow the user to assign/reassign each ingredient to a store before printing.
- [ ] Provide a print-friendly page/PDF per store with store name, ingredient/supply, net-to-buy quantity and unit, Perishable/Non-perishable status, optional estimated unit/line cost, and checkboxes/space for handwritten notes. Keep the Market Load List separate from store purchase lists.
- [ ] For WhatsApp, render the selected store list as readable line-delimited text (store heading followed by item, quantity, and unit); no document attachment is required. Validate message/template length before sending and offer print/export as the complete-list fallback.
- [ ] Display preferred vendor/location and latest applicable unit cost as planning estimates; estimates remain distinct from actual purchase cost until a purchase is recorded.
- [ ] Allow manual ingredient additions and quantity adjustments. Completing a list or marking items purchased must not automatically create purchases; provide an explicit action to record approved purchases through Capability 4 with vendor/location, actual quantity, and actual cost.
- [ ] Provide an explicit action to create/link the shared production event and corresponding recipe-ingredient consumption, product-production, and market-supply usage movements exactly once; apply each recipe input's waste percentage and carry discrete-unit fractions forward until a whole waste unit is reached. Associate usage with the market visit/date and copy `Perishable By` onto the resulting perishable stock lot. Planned quantities alone must not affect inventory, production, sales, or profit.
- [ ] Support `GET/POST /api/v1/markets/prep-lists` and `GET/PUT /api/v1/markets/prep-lists/{id}` with date, market, and status filters.
