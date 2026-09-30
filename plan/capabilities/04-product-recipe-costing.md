# Capability 4: Product, Recipe & Costing Management

- [ ] **Capability complete** (all features below checked)

Bounded context: `mbs/products/` (blueprint §3.1 #1, Modules 1–4). Product catalog, recipes, ingredient cost history, product cost engine, and derived readiness status.

## Feature 4.1 — Product Master
- [ ] Feature complete
- [ ] `tblProductSetup` model, keyed by Square **Variation ID** (never product name) — Governance Rule 1.
- [ ] In MVP 2, create a minimum sellable product record for every Square Variation ID and require an effective-dated cost before that variation's Orders are accepted. Full recipe, costing-history UI, and product readiness workflow are expanded in MVP 3.
- [ ] Store an `is_perishable` checkbox on each inventory-tracked product; default it to checked/TRUE for new products. The user may uncheck it for non-perishable products; never infer perishability from merchandise category or recipe.
- [ ] Store Target Stock Quantity (the intended replenishment/order quantity) and optional Product URL per Variation ID; use the product's inventory unit. When entering a purchase, offer its quantity as the suggested target and let the user confirm/change it.
- [ ] For MVP 3, capture an opening counted quantity/date/unit for each stocked product and dated restock/manual-adjustment movements so MVP 4 has recorded product stock rather than assuming zero.
- [ ] Treat an opening count as the authoritative balance at its recorded `counted_at` instant. The opening balance is the count plus only approved movements strictly after that instant; a late or backdated movement at or before the count requires an audited correction/restatement and cannot silently change a previously published balance. Define the same cutoff rule for products, ingredients, and supplies.
- [ ] Migrate MVP 1 minimal ingredient/recipe and receipt-item links with stable identities into the MVP 3 models. The migration must be replay-safe, preserve every receipt/item link, mapping, audit identity, and historical cost row, and support tested rollback recovery.
- [ ] Product status derivation: READY / SETUP REQUIRED / CONFIGURE PRODUCT based on recipe completeness + cost presence.
- [ ] Store approved customer-facing product name, sale unit, display price, active/inactive status, and optional customer description separately from internal cost and margin fields. Do not expose internal costs in the market-day price list.
- [ ] Store reviewed allergen, ingredient, storage, best-by, batch/production-date, and preparation information when applicable; keep applicability and review status auditable and do not infer regulatory claims from OCR merchandise categories.
- [ ] `GET/POST /api/v1/products`, `GET/PUT /api/v1/products/{variation_id}` per blueprint §9.1.
- [ ] Handle products missing from Square catalog gracefully (flagged, not silently dropped).

## Feature 4.2 — Recipe Framework
- [ ] Feature complete
- [ ] `tblIngredients` + `tblRecipeMaster` + `tblRecipeIngredients` + `tblProductRecipeMapping`: ingredient master with stable Ingredient ID, name, base unit, active status, and `is_perishable` checkbox defaulting TRUE; recipes link one-or-more ingredient rows with Quantity Per Item + Unit.
- [ ] Store a `Waste Percentage` (0–100%, default 0%) on each recipe input. Add `tblRecipeSupplies` rows for stocked supplies (for example, one cup per finished item) with quantity, unit, and waste percentage so packaging waste is attributable to its stock item; enforce the 0–100 bound in the database and service layer.
- [ ] Calculate expected input waste as `prepared quantity × quantity per item × (Waste Percentage / 100)`. For discrete whole-unit stock such as cups, retain the fractional remainder by recipe input across production events and post a waste movement only when accumulated expected waste reaches a whole inventory unit; do not round each batch up. For stock units that support fractional quantities, post the exact waste quantity.
- [ ] Carry the fractional remainder across batches and week boundaries; production corrections reverse/recalculate the corresponding remainder idempotently. Unconfirmed prep plans do not accrue or post waste.
- [ ] Recipe completeness rule: at least one ingredient row with valid Quantity Per Item and matching Unit.
- [ ] Recipe-derived shopping quantities must preserve the ingredient's base unit and `is_perishable` value.
- [ ] `GET/POST /api/v1/recipes`, ingredient and `tblRecipeSupplies` CRUD endpoints, and validated waste-percentage updates per blueprint §9.2. Use `Decimal` for recipe quantities and costs; reject incompatible units unless a defined conversion exists.

## Feature 4.3 — Ingredient Cost History
- [ ] Feature complete
- [ ] `tblIngredientCostHistory`: ingredient, vendor/supplier, purchase store/location, effective date, purchased and normalized base units, normalized unit cost, currency, source purchase/receipt, and audit fields.
- [ ] Formula: `Effective Cost for Date D = latest Effective Date <= D` for the ingredient and its selected preferred vendor/location. Keep location on every cost row; if no preferred source is configured, label the selected latest-known source and surface that the default sourcing rule was used.
- [ ] Never edit historical cost rows — insert new effective-dated rows only.
- [ ] Allow a preferred vendor/purchase location to be configured per ingredient; changing that preference affects prospective recipe-cost views and must not rewrite historical purchase or sale costs.

## Feature 4.4 — Product Cost Engine
- [ ] Feature complete
- [ ] `tblProductCosts`: manual cost overrides at the Variation ID level with effective dates; most recent cost on/before calc date wins. MVP 2's reviewed costs seed this history; MVP 3 recipe-derived costs are versioned separately and do not silently replace COGS snapshots on accepted sales. Correct prior sales only through an audited adjustment/restate action.
- [ ] `Cost Review Status = REVIEW COST` when Effective Date older than `cost_review_threshold_days` setting (default 90) — Governance Rule 7.
- [ ] Recompute affected derived fields whenever `cost_review_threshold_days` or an ingredient/product cost changes (settings-driven re-derivation, Capability 9).

## Feature 4.5 — Ingredient Purchases & Manual Cost Entry
- [ ] Feature complete
- [ ] Create `tblIngredientPurchases` for approved ingredient purchases with purchase date, ingredient, vendor/supplier, purchase store/location, purchased quantity/unit, normalized base quantity/unit, total cost, receipt/receipt-item link when available, entry source (OCR/manual), approval audit, and test-record flag.
- [ ] Support each ingredient appearing in multiple recipes through the existing ingredient-to-recipe rows in `tblRecipeIngredients`; a receipt line classified as Recipe Ingredient links to one or more recipes and the matching ingredient. These links describe recipe use and must not multiply purchased quantity or cost across recipes.
- [ ] Provide manual purchase entry and manual effective-dated ingredient-cost entry, including vendor/location; both use the same validation and audit rules as OCR-reviewed records.
- [ ] Provide `GET/POST /api/v1/ingredient-purchases` and `PUT /api/v1/ingredient-purchases/{id}`; manually entered and OCR-approved purchases use the same MANAGER+ service and cannot be posted twice.
- [ ] On approval, calculate normalized cost per base unit and append an effective-dated `tblIngredientCostHistory` row; never update prior history. Require a valid ingredient mapping and unit conversion before posting, then record the approved quantity as one dated ingredient-stock purchase movement.
- [ ] Treat ingredient purchases as cost/inventory inputs, not as a second operating-expense charge when COGS is recognized; show purchase cash outlay separately if cash-flow reporting is required.

## Feature 4.6 — Product Restock History
- [ ] Feature complete
- [ ] For products bought for resale/restock, maintain `tblProductRestockHistory` with Variation ID, purchase date, retailer/vendor, store/location, quantity/unit, actual unit/line cost, receipt/receipt-item link, and approval audit.
- [ ] Each approved product restock writes exactly one linked `tblProductInventoryMovement` and provides the last-purchased store/location, date, and cost for low-stock recommendations; do not treat internally produced quantities as purchases.
- [ ] For recipe-made products, derive recommended buying locations from the latest approved purchases for required ingredients instead of inventing a finished-product retailer.
- [ ] Provide manual and OCR-reviewed restock entry through a MANAGER+ purchase service; preserve source receipt and effective-dated costs.

## Feature 4.7 — Ingredient Cost History Screen
- [ ] Feature complete
- [ ] Provide an Ingredient Cost History screen with ingredient selector, date-range filter, and vendor/store-location filter; show each effective date, source location, purchased quantity/unit, normalized cost per base unit, and linked receipt/purchase.
- [ ] Chart normalized unit cost over time, with distinct series or comparison for selected vendors/locations; support table view and export of the displayed history.
- [ ] Show the effective recipe-input cost at a selected date and the source location used; changes in price over the year must visibly change date-specific recipe cost without overwriting prior values.
- [ ] Provide `GET /api/v1/ingredients/{ingredient_id}/cost-history` with date and location filters; restrict history changes to audited purchase/cost services (MANAGER+).

## Feature 4.8 — Stocked Operating Supplies
- [ ] Feature complete
- [ ] Maintain `tblStockedSupplies` for consumables such as cups and napkins, with Supply ID, name, base unit, `is_perishable` checkbox defaulting TRUE, target/restock quantity, optional online URL, and active status.
- [ ] New supply checkboxes start checked; the user explicitly unchecks non-perishables such as empty packaging cups. Food/product portions served in cups use the food product's own perishability setting.
- [ ] Record supply purchases with purchase date, store/vendor location, quantity/unit, unit cost, receipt-line link, and approval audit; update supply stock once per purchase.
- [ ] For receipt lines classified as Ordinary Business Purchase, allow the reviewer to mark the line as a stocked supply or a direct expense. Stocked supplies remain quantity-tracked until used; do not expense the same purchase twice.
- [ ] Route supply usage into `tblSupplyInventoryMovement` with market visit/date and source prep list so usage is attributed to the market that consumed the supplies.

## Feature 4.9 — Units & Conversions
- [ ] Feature complete
- [ ] Maintain a unit catalog in which every unit has exactly one dimension: count (each, pack, dozen), mass (oz, lb, g, kg), or volume (fl oz, pint, qt, gal). Store receipt-text aliases per unit (for example `pt`, `PT`, `pint`, `pints` → pint); alias matching is case-insensitive and exact, and fuzzy matches are suggestions only.
- [ ] Maintain a versioned global conversion registry for same-dimension factors only (1 qt = 2 pint, 1 lb = 16 oz, 1 dozen = 12 each). Global rules never convert between dimensions.
- [ ] Maintain effective-dated, owner-entered per-item conversions for cross-dimension factors on ingredients, products, and supplies (for example Strawberries: 1 pint ≈ 0.75 lb; 1 each ≈ 0.04 lb). They are specific to each item because a pint of strawberries and a pint of blueberries weigh differently. Mark them as estimates; changing one never rewrites previously posted quantities or costs.
- [ ] Normalize a purchase to the item base unit in this order: (1) purchased amount = package count × pack size in the pack unit; (2) stop if already the base unit; (3) apply a global same-dimension factor; (4) if the dimension still differs, apply the item's own conversion; (5) if no path exists, keep the line as a draft and block posting to cost/inventory. Let the reviewer add the missing item conversion inline. Store the as-bought amount/unit, base quantity, normalized unit cost, and the conversion versions used.
- [ ] Keep quantities and conversion factors as exact `Decimal` values through the calculation and round only money/display values at posting. Show values derived from an item conversion as approximate (for example "≈2.25 lb").
- [ ] Cover the worked strawberry example (base unit lb, 1 pint ≈ 0.75 lb) with synthetic tests: `1 PT` qty 3 @ $4.99 → 2.25 lb, $6.65/lb; `1 QT` $6.49 → 1.50 lb, $4.33/lb; `2 LB` $5.98 → 2.00 lb, $2.99/lb; `16 OZ` $3.99 → 1.00 lb, $3.99/lb; no size → blocked. Also cover the "points" → pint suggestion, a missing item conversion, a reversed base unit (pint), and conversion-version changes. Track CO-001 in [the test-case manifest](../test-case-manifest.csv); planned focused command once implemented: `uv run --frozen pytest tests/test_unit_conversions.py -q`.
