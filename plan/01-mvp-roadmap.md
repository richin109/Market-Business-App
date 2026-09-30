# MBS MVP Delivery Roadmap

This roadmap defines deployable release order. Capability numbers identify functional areas, not delivery order. Each MVP should be usable before the next begins; shared security, storage, migrations, and phase-specific tests are foundations from the first release. Every MVP must track PostgreSQL schema changes with SQLAlchemy models and Alembic migrations, and every MVP that delivers browser UI must include its Playwright end-to-end suite in the release profile (see Capabilities 10 and 11).

## MVP 1 — Receipt Capture, Review & Storage

**Goal:** Deploy a receipt application that extracts each accepted receipt once, lets the user correct it, and saves all resulting information for reuse.

**In scope**
- Authenticated upload of image/PDF, file validation, status/progress, receipt list/detail, manual correction, exact/near-duplicate safeguards, audit trail, and soft delete.
- [ ] Allow selecting a local directory to batch-upload its receipt images/PDFs, including subfolders, with confirmation, per-file results, duplicate protection, bounded batch limits, and multi-file fallback where folder selection is unavailable (Capabilities 1.2 and 2.4; RM-020).
- [ ] Reimport the same confirmed directory safely: identical files return existing uploads without OCR, while a changed image/PDF containing old and newly added orders is processed as a new immutable source version and only previously unseen order identities are inserted. A near-match or ambiguous order is held visibly for review, not silently skipped or counted as new (Capabilities 1.2/1.3 and 2.1/2.4; RM-025).
- [ ] Deliver a side-by-side receipt review page showing the stored image beside editable extracted values. Capture each line as package count × pack size × pack unit using a minimal unit/alias catalog, allow filling missing data and adding/removing lines, and remember confirmed pack sizes. Cross-dimension conversions wait for MVP 3 (Capabilities 2.5 and 2.6; RM-021).
- [ ] Create canonical store records automatically from the store read on each imported order/receipt, retain every source spelling as an alias matched by exact normalized key, and deliver a store management screen where a user renames a store's display name and groups multiple alias spellings into one canonical store without rewriting source documents, `Receipt_ID`, or posted records (Capabilities 1.2/1.4 and 2.7; ST-001, ST-002).
- [ ] Key each purchased line by canonical store + the store's own product identifier (merchant item number/SKU), never the printed description, and resolve it to one application-wide canonical item ID that may own many store items across one or many stores (Capabilities 1.2/1.4 and 2.8; IT-001).
- [ ] Allow a user-entered common name on the canonical item and on each store item, defaulting the displayed name to the name read from the order until a common name exists; the raw printed description stays unchanged (Capabilities 2.5/2.8; IT-001).
- [ ] Deliver an item mapping screen that maps different store items to one canonical item, suggests candidates from common names and receipt descriptions, requires explicit confirmation, and supports audited unmap/remap without altering posted purchases (Capability 2.8; IT-002). Automatic creation, common names, and mapping constraints ship first (slices S14/S15); store merge/split and the mapping screen with ranked suggestions follow in slice S16.
- [ ] Deliver a Purchases / Receipts order-history screen for manually entered and scanned receipts, showing each order's reference, store, purchase date, and line-item count, with a clickable link to its saved header and item details (Capability 2.4; RM-019).
- [ ] Support one receipt/order across multiple uploaded PDFs without counting overlapping copies twice; retain each source and require review before adding ambiguous repeated-product lines. The combined line amounts must reconcile to the printed item subtotal before approval (Capabilities 1.3 and 2.1/2.5; RM-022).
- [ ] Verify local OCR and review against both image-only and selectable-text synthetic PDFs: preserve printed item number, package size, weighed pounds, quantity, REF/TR# candidates, payment brand/visible suffix, and differing transaction/print times without inventing absent values (Capabilities 1.1/1.4 and 2.5; RM-023).
- [ ] After explicit real-data approval, evaluate the private local `receipts/` directory against human-reviewed expectations in an isolated offline run; include multi-PDF orders and report OCR accuracy, missing/extra lines, held ambiguities, and subtotal reconciliation without committing source files or identifiable output (Capability 10.1; RM-024).
- Local Tesseract + OpenCV is the selected provider. The source scan is saved in protected persistent file storage; Postgres stores normalized header/items, immutable raw OCR JSONB, and a versioned canonical receipt JSONB snapshot.
- Exact SHA-256 matches are rejected before OCR. Local perceptual matches are held for review before OCR runs. A unique Receipt_ID prevents a second receipt row; a different file with the same reviewed store, purchase date, and order identity is held for overlap-versus-supplement review, then linked to the existing receipt or rejected as a copy without overwriting accepted data.
- Normal viewing, search, correction, and export use stored data and never invoke OCR. Rerun OCR is an explicit audited ADMIN action; failed local jobs retry idempotently without duplicating receipts.
- Include four receipt-line dispositions: Personal/Non-business, Ordinary Business Purchase, Recipe Ingredient, Capital Asset/Equipment. Persist reviewer decisions and remember exact item matches.
- Create MVP-sized receipt-linked ingredient-purchase, ordinary-expense, and capital-asset records, plus stable minimal Ingredient and Recipe records for receipt links. Full product setup, unit conversions/costing, depreciation, weekly expenses, and inventory valuation come later.
- Deploy internally with Docker Compose, Postgres, Redis/Celery, persistent file storage, authenticated manager UI, migrations, health check, backups, and tested restore. No Square, WhatsApp, inventory engine, or dashboards required.

**Deferred:** Optional Google Document AI integration (with separate privacy and cost approvals), full cost/accounting logic, multi-receipt business dashboards, Square data, weekly operations, inventory valuation, tax packages, and messaging.

**Done when:** a manager can upload, review/correct, classify and link receipt lines, save, then retrieve all parsed data after a container restart without another OCR run; duplicate paths do not overwrite data or cause unnecessary OCR work. Imported orders create their stores automatically, alias spellings group into one renamed canonical store, and every purchased line resolves through canonical store + store product identifier to a canonical item whose displayed name falls back to the order name until a common name is entered. A repeated directory with unchanged files adds nothing, while an authorized changed source containing previously seen and new complete orders adds only the new identities; ambiguous identities remain visible review holds (RM-025). Local development may use the mocked OCR boundary, but promotion requires the configured local Tesseract + OpenCV adapter, persisted PostgreSQL state, approved accuracy/review thresholds, and a passing `receipt-mvp` profile. The MVP 1 measures in [the implementation-readiness gate](02-implementation-readiness.md) must also pass before promotion.

## MVP 2 — Square Setup, Sales Activation & Market-Day Selling
**Goal:** Establish the shared sales ledger and let a small business capture and close real market-day sales without duplicate or untraceable facts.

All MVP 2 market dates and effective periods use full `YYYY-MM-DD` dates, including the year; schedules may span multiple calendar years and must resolve historical sales using the schedule effective on the sale's complete business date.

**In scope**
- Stage A: Capability 3 syncs Square Catalog and stages stable Item/Variation IDs.
- Before Square activation, pass the read-only API gate in Capability 3: verify read-scoped credentials and prove the provider adapter rejects every non-allowlisted or mutating operation before network I/O, including from retries and admin-triggered sync. The local Sync Now command may write staging records in MBS but must never write to Square.
- Stage B: create the minimum sellable product records keyed by Variation ID, with a user-reviewed effective product cost; create Market IDs, Square Location-to-Market/channel mappings, and reusable effective-dated local operating-hour schedules. Create dated market visits explicitly per user selection for any past or future business date; schedules never generate visits or imply attendance, and future planned visits are not attended sales attribution until an outcome is recorded.
- Stage C: Capability 3 stages Square Orders/Payments; Capability 14 accepts each Square line only when its Variation ID, effective product cost, and dated market visit or explicit non-market channel resolve. A market line must also fall within the market's effective-dated operating hours in local time, unless an authorized exception is recorded. Payments never creates a second Square sales fact.
- Stage D: Capability 14 provides audited manual entry for cash and other non-Square sales, linked to product, date, channel/market, amounts, tax, tender, and any refund/correction; both sources feed shared reporting and tax reconciliation.
- Use stable Square Order ID + Line Item UID idempotency, cursor-based sync, replay/update/refund reconciliation, staging, and sync audit. Manual entries use an idempotent source/event ID and cannot duplicate Square facts.
- Reconcile Square order amounts, discounts, refunds, Square-reported tax, Payments, and net deposits; this is transaction reconciliation only. Taxability decisions, liability calculations, and filing workpapers remain MVP 8. Distinguish actual fees from clearly labeled estimates.
- Keep unresolved lines in a visible import-exception queue, not the accepted sales ledger. Valid lines may be accepted while failing lines remain staged; correct prerequisites and retry idempotently.
- Preserve source order/payment IDs and the exact cost/market mappings and COGS snapshot used for each accepted sale so later master-data changes do not silently rewrite history.
- Capability 16 provides a market-day session, fast mobile sale capture, configured tender controls, product availability, closeout, and helper permissions over Capability 14's canonical services. Square remains the online POS unless an explicit offline-queue decision is approved; any offline queue must reconcile idempotently before a sale is treated as settled.
- **Done when:** every accepted Square or manual sales line has a source-specific identity, date-effective cost, and market/channel assignment; a market operator can open, sell, reconcile tenders, and close a visit; unresolved lines and close exceptions remain visible; retries never duplicate accepted sales. The `sales-mvp` profile in Capability 10 and the MVP 2 measures in [the implementation-readiness gate](02-implementation-readiness.md) must pass before promotion.


## MVP 3 — Products, Recipes & Costing

**Goal:** Expand the lightweight MVP 1 recipe data into the product, ingredient, sourcing, and costing system.

**In scope**
- Expand the minimum Variation ID product/cost records created in MVP 2 into the full product and ingredient masters, each linked to the MVP 1 canonical item ID so ingredients, products, and supplies inherit the existing store-item mappings and common names rather than re-keying by description; add recipe-to-product/ingredient mappings, quantities, units, and conversions. Normalize purchases to each item's base unit through same-dimension global factors and effective-dated per-item conversions (for example 1 pint strawberries ≈ 0.75 lb), extending the MVP 1 unit/alias catalog rather than replacing it (Capability 4.9; CO-001).
- Require a Shelf Life on every stocked product, ingredient, and supply when it is first added: a duration in days, weeks, or months, or `never` for durable items such as empty packaging cups. The confirmed answer is remembered on the item and becomes the default for every future lot. Set the target replenishment quantity and inventory unit for each item, and a mandatory output shelf life on each recipe.
- Record an initial counted on-hand quantity and unit for stocked products, ingredients, and supplies, plus dated purchase/manual correction movements. This lightweight stock ledger is the authoritative MVP 3 opening balance for MVP 4 shopping; define the opening-count date and retain count audit.
- Manual and receipt-linked ingredient/product/supply purchases with retailer, canonical store/location, quantity/unit, actual cost, receipt link, and effective-dated unit-cost history. Every purchase resolves through the MVP 1 canonical store and store-item-to-canonical-item mapping; a purchase may not be keyed by a typed store or item name.
- Date-specific recipe/product cost calculations, preferred source, product readiness/cost-review flags, and ingredient cost-history table/chart.
- Reconcile/update the minimal ingredient and recipe records created in MVP 1 without losing receipt links or history.

**Done when:** a product's recipe and cost can be traced to dated purchases and locations, and prior costs remain unchanged. The `costing-mvp` profile in Capability 10 and the MVP 3 measures in [the implementation-readiness gate](02-implementation-readiness.md) must pass before promotion.

## MVP 4 — Shopping Lists & WhatsApp

**Goal:** Plan what to bring to a market, what ingredients to buy, and send the generated list through WhatsApp.

**In scope**
- Capability 15 provides Market Load Lists by market/date and product Variation ID/target quantity (for example, 12 X and 10 Y), with copy-previous-list support.
- Reuse the Market ID/name registry and dated visits established as Square prerequisites in MVP 2; full market-cost administration and route calculations remain with Capability 5 in MVP 5.
- Capability 15 calculates recipe-derived ingredient and supply requirements, subtracts counted balances and approved purchases/prep consumption, and provides store-grouped printable lists, source/last-purchase location, units, shelf life with the derived `Perishable By`, and estimated cost.
- WhatsApp Cloud API: manually initiated message batches to at least two opted-in recipients, with add-more support, private individual delivery, approved templates as required, consent/opt-out checks, cost estimate, and delivery status. Manual print/export remains available.
- Capability 15 confirms prep through Capability 5's shared production service, posting ingredient consumption, stocked-supply use, and product quantities exactly once; unconfirmed plans do not change stock. Capability 5 provides full weekly entry and correction workflows in MVP 5.

**Done when:** a dated product target list produces a print-ready store-by-store ingredient list and can be sent to the selected WhatsApp recipients. Automatic stock alerts are deferred until inventory is reconciled in MVP 6. The `prep-mvp` profile in Capability 10 and the MVP 4 measures in [the implementation-readiness gate](02-implementation-readiness.md) must pass before promotion.

## MVP 5 — Markets & Weekly Operations

**Goal:** Manage actual market attendance and the business activity surrounding each visit.

**In scope**
- Extend the MVP 2 Market Master/location mappings and explicitly selected dated visits with the complete market workflow: date-effective cost start/end dates, fees, overlap validation, attendance/status/score/notes, visit history, and audited cancellation of a visit without deleting its market or linked records. Support multiple distinct markets on one date and past/future dates; only explicitly recorded attendance counts as attended.
- One-way route distances stored and reused; multi-market itinerary asks Home versus direct travel; calculate trip miles/cost and retain auditable allocation.
- Capability 5 expands the Capability 15 prep production-event workflow with weekly entry and audited corrections; prep and manual production use the same ledger/service. Add samples, stocked-supply usage by market/date, and business expense entry with audit history. Capability 15 lists can be linked to actual visits; planned quantity is not production.

**Done when:** market/date, route, production, and expenses are captured once and flow into later inventory and reporting. The `markets-mvp` profile in Capability 10 and the MVP 5 measures in [the implementation-readiness gate](02-implementation-readiness.md) must pass before promotion.

## MVP 6 — Inventory & Reorder

**Goal:** Reconcile actual sales, production, purchases, and expiry waste into trustworthy weekly balances.

**In scope**
- Weekly product inventory snapshots consuming accepted Square and manual sales, approved production, restocks, samples, waste, and count adjustments; ingredient on-hand balances consume purchases, recipe usage, waste, and count adjustments.
- Each lot becomes waste when it reaches its own `Perishable By`, posted by an expiry job that runs at startup and on a short interval; unexpired lots and `never` items carry forward across the weekly close. Reconcile inventory movements and value waste.
- Reorder engine using units-consistent usage, lead time, safety stock, on-hand amount, preferred/last source, and estimated purchase cost.
- Enable automatic WhatsApp utility alerts for shelf-life-eligible stocked products, recipe ingredients, and operating supplies (`never` or at least `low_stock_alert_min_shelf_life_days`, default 30) when on-hand quantity reaches 20% or less of the confirmed target/replenishment quantity (100 ordered means alert at 20 remaining). Include last approved purchase store/location/date and Product URL when available; require a source record, opted-in recipient, approved template/window, and dedup/re-arm controls.

**Done when:** weekly balances reconcile, waste/carry-forward are correct, and alerts are driven by verified quantities. The `inventory-mvp` profile in Capability 10 and the MVP 6 measures in [the implementation-readiness gate](02-implementation-readiness.md) must pass before promotion.

## MVP 7 — Dashboards, Rankings & Forecasting

**Goal:** Add the workbook's decision-support features after the underlying sales, costs, markets, and inventory are reliable.

**In scope:** Operations and Executive dashboards, scorecards, rankings, opportunity scores, forecasts, test-record isolation, refresh orchestration, and source lineage.

**Done when:** dashboard totals reconcile to approved source records and all 110 source-workbook regression cases pass. Tax-specific application tests and final release controls remain for MVP 8. The `analytics-mvp` profile in Capability 10 and the MVP 7 measures in [the implementation-readiness gate](02-implementation-readiness.md) must pass before promotion.

## MVP 8 — Tax Workpapers & Full-System Release

**Goal:** Produce filing support and certify the integrated application.

**In scope:** Sole-proprietor Schedule C-aligned workpaper for Form 1040 use, applicable Florida business-tax schedules, source-document index, year snapshot, tax-professional review, tax-specific application tests, six workbook release controls, full-system certification using the 110 source-workbook cases plus all applicable application tests, Proxmox promotion, backup/restore and operational security review.

**Done when:** full-system certification passes. The app prepares documents; it does not sign or file returns. The `full-mbs` profile, all six blocking controls in Capability 10, and the MVP 8 measures in [the implementation-readiness gate](02-implementation-readiness.md) must pass before production promotion.

## Capability Mapping & Shared Foundations

- Capability 1–2: MVP 1.
- Capability 3: Square Catalog/Orders/Payments provider sync and raw staging in MVP 2.
- Capability 4: minimal ingredient/recipe linking in MVP 1; full Product/Recipe/Costing in MVP 3.
- Capability 5: minimal market directory, Square Location mappings, effective-dated operating hours, and dated visits in MVP 2; full market-cost administration and weekly operations in MVP 5.
- Capability 5 operating-hour schedules are year-bearing effective-dated periods; recurring annual patterns must be expanded and validated per calendar year before they are used for sales attribution.
- Capability 6: target stock inputs in MVP 3; full inventory/reorder and automatic low-stock alerts in MVP 6.
- Capability 7–8: MVP 7.
- Capability 9: security, audit, secrets, and required settings from MVP 1 onward; later business settings as their capabilities launch.
- Capability 10: phase-specific test/release profiles; the 110-test/six-control certification applies to full MBS, not the receipt-only MVP.
- Capability 11: Docker Compose, persistent storage, authentication, backups, and restore begin in MVP 1; Proxmox promotion follows when ready.
- Capability 12: MVP 8.
- Capability 13: message transport/consent in MVP 4 and automatic inventory utility alerts in MVP 6.
- Capability 14: canonical Square/manual sales ledger and financial reconciliation in MVP 2.
- Capability 15: market load lists, store-grouped shopping, and prep confirmation in MVP 4.
- Capability 16: market-day sessions, operational sale capture, tender closeout, availability, preorders, stall readiness, and customer-facing product information in MVP 2; it consumes Capability 14 and feeds Capability 6.
