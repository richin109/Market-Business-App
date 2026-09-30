# Capability 6: Inventory Engine

- [ ] **Capability complete** (all features below checked)

Bounded context: `mbs/inventory/` (blueprint §3.1 #2, Modules 5, 15–16). Weekly inventory snapshots, spoilage automation, carry-forward, valuation, and reorder points.

## Feature 6.1 — Weekly Inventory Snapshots
- [ ] Feature complete
- [ ] Maintain `tblProductInventoryMovement` plus ingredient/supply movement ledgers, keyed by source event, for opening counts, restocks/purchases, production, Square and manual sales, samples, spoilage, and count adjustments. Movements are signed, unit-labeled, dated, auditable, and idempotent. Track perishable lots across products, ingredients, and supplies with remaining quantity and an optional actual `Perishable By` timestamp; never infer a purchase-lot expiry date when it is unknown.
- [ ] `tblInventory`: one row per Variation ID per Monday period-start date (per `week_starts_on` setting).
- [ ] Each inventory-tracked product uses the `is_perishable` checkbox from Product Setup, default TRUE. Backfill existing inventory items without an explicit classification as perishable and require review before changing them to non-perishable.
- [ ] Flow fields: Beginning + Restocks + Produced − Square Sales − Manual Sales − Samples − Spoilage + Count Variance = Ending. Beginning is the prior period's ending except for the initial audited opening count; Count Variance is an explicit signed adjustment from a dated physical count, not an unexplained balancing plug.
- [ ] Populate Produced from shared production events and Sold from accepted Square Orders plus manual sales; populate restocks from approved product purchases. Keep physical counts and corrections auditable and prevent refresh/replay from adding quantities twice.
- [ ] Reconcile every snapshot to the signed movement ledger and display the physical-count variance and resulting adjustment separately; surface missing or inconsistent source movements rather than silently balancing the snapshot.
- [ ] Close a weekly period as an immutable snapshot. A late sale/refund, purchase, count adjustment, or production correction for a closed period appends a linked restatement version; rebuild affected later snapshots from idempotent ledger events and retain the original close, reason, actor, and superseding version. Never create spoilage twice or silently revise a previously reported close.
- [ ] `GET/POST` inventory endpoints per blueprint §9.5.

## Feature 6.2 — Spoilage & Carry-Forward
- [ ] Feature complete
- [ ] Perishable rule (Governance Rule 8): when a perishable lot reaches its `Perishable By` timestamp, any remaining quantity is recorded as Spoilage/Waste; at weekly close, all remaining perishable stock is also wasted. Perishable Ending Inventory is zero and none carries into the next week. Negative movement remains an inventory validation error, not negative waste.
- [ ] Run a scheduled expiry job that records one idempotent waste movement when any product, ingredient, or supply lot reaches its known `Perishable By`; do not wait until Monday to recognize already-expired stock. For perishable purchase lots with no known date, the weekly close wastes remaining quantity. The Monday close also wastes any known-date perishable lot whose date has not yet expired.
- [ ] Non-perishable rule: valid Ending Inventory rolls to the next week's Beginning Inventory. Preserve the distinction between true inventory variance and perishable waste in reports.
- [ ] Celery-beat scheduled job to create next week's snapshot rows automatically each Monday (matches the Kubernetes `inventory-snapshot` CronJob concept from the blueprint, run instead via celery-beat regardless of deployment target).
- [ ] Test late and corrected events across a weekly close, proving exactly one waste movement, a linked restatement, correctly rebuilt downstream opening/ending balances and valuation, and correct low-stock alert re-arm behavior.

## Feature 6.3 — Inventory Valuation
- [ ] Feature complete
- [ ] Value current on-hand inventory using effective product cost as of valuation date (Module 16); feeds COGS and waste valuation reporting.

## Feature 6.4 — Reorder Engine
- [ ] Feature complete
- [ ] Derive ingredient usage from approved production quantities × recipe ingredient quantities, normalized to the ingredient base unit; define the averaging window and handle missing/incomplete recipes explicitly.
- [ ] Store lead time in days, average daily usage, and an explicit ingredient-level Safety Stock Quantity; calculate `Reorder Point = ROUNDUP(Average Daily Usage × Lead Time Days + Safety Stock Quantity, 0)` as in the workbook. Do not apply `safety_stock_pct` because the source workbook defines no conversion to a quantity; never silently replace an explicit quantity or mix weekly and daily units.
- [ ] Compare reorder point to on-hand ingredient quantity, incorporating approved ingredient purchases and usage; show suggested purchase quantity and estimated cost, with the underlying units and last cost visible.
- [ ] Surface ingredients below reorder point on the Operations Dashboard (Capability 8).

## Feature 6.5 — Ingredient Inventory & Perishable Waste
- [ ] Feature complete
- [ ] Maintain `tblIngredientInventoryMovement` keyed by movement ID/source event for opening counts, approved purchases, recipe-prep usage, waste, and manual adjustments; store signed quantities in the ingredient base unit with date, source reference, and audit data.
- [ ] Maintain `tblSupplyInventoryMovement` for stocked supplies such as cups and napkins; store signed quantity/unit, market visit/date, movement type, source purchase/prep record, and an idempotency key so usage at different markets reduces the same balance exactly once.
- [ ] Maintain an idempotent fractional-waste remainder per recipe input and stock item for discrete inventory units. Carry it across production events and weekly periods; when it reaches one whole unit, post exactly one waste movement and retain any remainder. Corrections must reverse or recompute the affected remainder and movements without double-counting.
- [ ] Derive current ingredient on-hand as opening balance plus subsequent idempotent movements. MVP 3 supplies the opening count/purchases; MVP 4 confirmed prep records recipe usage; MVP 6 rolls the same ledger into weekly snapshots.
- [ ] Use each ingredient/supply `is_perishable` checkbox, default TRUE for new and migrated unclassified stock. Users may explicitly uncheck durable items such as empty packaging cups. At weekly close, perishable quantities remaining after production/market use are recorded as waste and ending quantity is zero; non-perishable quantities carry forward.
- [ ] Link ingredient waste quantity and valuation to the ingredient's effective-dated cost history and source purchase/location; prevent the same quantity from being both carried forward and expensed as waste.

## Feature 6.6 — Non-perishable Low-stock WhatsApp Alerts
- [ ] Feature complete
- [ ] For non-perishable stocked items—including sale products, recipe ingredients, and operating supplies such as cups—compare on-hand quantity with `Target Stock Quantity × nonperishable_low_stock_threshold_pct` (default 20%); send when on-hand is at or below the threshold. Example: target/restock 100 cups triggers at 20 cups remaining. Do not alert for perishable stock.
- [ ] Re-evaluate after Square sale ingestion and inventory/production/manual/supply-usage movements; trigger once when stock crosses from above the threshold to at or below it. If stock is already below threshold when alerts are enabled, create one initial alert event.
- [ ] Maintain approved product restock history (`tblProductRestockHistory`) with Variation ID, purchase date, retailer/vendor, store/location, quantity, unit cost, and receipt link; use the most recent approved restock as the suggested source. For recipe-made products, include ingredient shopping needs and each ingredient's most recent purchase store/location instead.
- [ ] Send an approved WhatsApp Utility template to configured, opted-in low-stock alert contacts through Capability 13; include product name, current quantity, target/threshold, last purchase store/location and date, and Product URL when configured. For recipe-made products, include ingredient-level source locations.
- [ ] Deduplicate by product and threshold-crossing event; send at most once while stock remains below threshold. Re-arm only after stock returns to or above threshold, and record send failures without losing the alert event.
- [ ] Allow admins to enable/disable alerts, configure alert recipients and cost limits, and inspect alert/send history. Missing target, last-purchase source, recipient consent, valid template, or Meta setup blocks automatic sending and surfaces a clear setup reason; never guess a store/location.
