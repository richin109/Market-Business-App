# MBS MVP Delivery Roadmap

This roadmap defines deployable release order. Capability numbers identify functional areas, not delivery order. Before the next MVP is built, the preceding MVP must be usable **locally with synthetic data**: its executable local profile subset, real entry points, migrations, and acceptance evidence must pass. Owner-only real-data evaluation, live-provider access, and production approval do not block later synthetic development. Production promotion of MVP N separately requires the complete named profile, real-data/provider/restore gates, and all applicable preceding profiles to pass for the same candidate. A failed predecessor local profile cannot be bypassed. Every MVP tracks schema with SQLAlchemy/Alembic and delivered browser UI with Playwright in its release profile (Capabilities 10/11).

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
- Create MVP-sized receipt-linked ingredient-purchase, ordinary-expense, and capital-asset records, plus stable minimal Ingredient and Recipe records for receipt links. These are review/link drafts, not stocked-item postings; if a stocked ingredient is persisted, collect its required Shelf Life first (D-20). Full product setup, unit conversions/costing, depreciation, weekly expenses, and inventory valuation come later.
- Deploy internally with Docker Compose, Postgres, Redis/Celery, persistent file storage, authenticated manager UI, migrations, health check, backups, and tested restore. No Square, WhatsApp, inventory engine, or dashboards required.

**Deferred:** Optional Google Document AI integration (with separate privacy and cost approvals), full cost/accounting logic, multi-receipt business dashboards, Square data, weekly operations, inventory valuation, tax packages, and messaging.

**Done when:** a manager can upload, review/correct, classify and link receipt lines, save, then retrieve all parsed data after a container restart without another OCR run; duplicate paths do not overwrite data or cause unnecessary OCR work. Imported orders create their stores automatically, alias spellings group into one renamed canonical store, and every purchased line resolves through canonical store + store product identifier to a canonical item whose displayed name falls back to the order name until a common name is entered. A repeated directory with unchanged files adds nothing, while an authorized changed source containing previously seen and new complete orders adds only the new identities; ambiguous identities remain visible review holds (RM-025). Local development may use the mocked OCR boundary, but promotion requires the configured local Tesseract + OpenCV adapter, persisted PostgreSQL state, approved accuracy/review thresholds, and a passing `receipt-mvp` profile. The MVP 1 measures in [the implementation-readiness gate](02-implementation-readiness.md) must also pass before promotion.

## MVP 2 — Square Setup, Sales Activation & Market-Day Selling
**Goal:** Establish the shared Square sales ledger and let a small business monitor imports, availability, settlement status, and market closeout without duplicate or untraceable facts.

All MVP 2 market dates and effective periods use full `YYYY-MM-DD` dates, including the year; schedules may span multiple calendar years and must resolve historical sales using the schedule effective on the sale's complete business date.

**In scope**
- Stage A: Capability 3 syncs Square Catalog and stages stable Item/Variation IDs.
- Before Square activation, pass the read-only API gate in Capability 3: verify read-scoped credentials and prove the provider adapter rejects every non-allowlisted or mutating operation before network I/O, including from retries and admin-triggered sync. The local Sync Now command may write staging records in MBS but must never write to Square.
- Stage B: create minimum sellable product records keyed by Variation ID, with reviewed provisional effective cost and confirmed Shelf Life (including `never`) before persistence; create Market IDs, Location-to-Market/channel mappings, and effective-dated operating hours. Create dated visits explicitly; future planned visits do not count as attendance. A Square variation is not a purchased store item (D-52); recipe or direct-canonical-item sourcing expands in MVP 3 without re-keying accepted Square sales.
- MVP 2 recipe-bound `Made N` events before recipes are ready retain reviewed provisional cost, original product Shelf Life, and a visible missing-input-use exception. MVP 3 recipe activation never retrofits those batches with guessed ingredients or a new expiry; MVP 4 new production uses effective recipes, and MVP 7 blocks affected ingredient/profit publication until an evidence-backed audited resolution (D-56; PR-001/PC-001).
- Add a minimal Market Planning form in MVP 2 with an ordered set of dated visits and editable target quantity per Variation ID. Targets estimate shopping/prep and create no stock. Let a user separately record the quantity actually made per Variation ID; this idempotent, auditable event creates finished-product stock. Square sales subtract their reported line quantities; never add both target and made quantity. MVP 4 adds recipe-aware ingredient consumption, shopping, and list finalization/WhatsApp to the same plan without re-keying visits or retroactively guessing MVP 2 ingredient use (D-53).
- Before enabling Direct Sell market loads in MVP 2, add the small receipt-backed stock path in slice 2.2a: explicitly classify an approved MVP 1 receipt line as stock rather than expense, resolve its canonical item and reviewed count package (one 24-bottle pack → 24 each), and post once by line occurrence. The same market screen can plan/confirm bringing 6 without buying 6 again; Square quantity 2 leaves 4 allocated and 22 total. Missing/ambiguous units or an already-expensed line are review holds, not guessed stock. MVP 3 extends this posting path for full conversions and cost history, without reposting existing lines (D-55; DS-001).
- Stage C: Capability 3 stages Square Orders/Payments; Capability 14 accepts each Square line only when its Variation ID, effective product cost, and dated market visit or explicit non-market channel resolve. A market line must also fall within the market's effective-dated operating hours in local time, unless an authorized exception is recorded. Payments never creates a second Square sales fact.
- Stage D: Square remains the only sales-entry system, including cash-tender sales. Capability 14 imports and accepts Square sales, links them to product, date, channel/market, amounts, tax, tender, refunds, and corrections, and feeds shared reporting and tax reconciliation.
- Use stable Square Order ID + Line Item UID idempotency, cursor-based sync, replay/update/refund reconciliation, staging, and sync audit. MBS does not accept manually entered sales; audited local adjustments to market attribution or inventory use their own idempotent source/event IDs without replacing Square facts.
- Reconcile Square order amounts, discounts, refunds, Square-reported tax, Payments, and net deposits; this is transaction reconciliation only. Taxability decisions, liability calculations, and filing workpapers remain MVP 8. Distinguish actual fees from clearly labeled estimates.
- Keep unresolved lines in a visible import-exception queue, not the accepted sales ledger. Valid lines may be accepted while failing lines remain staged; correct prerequisites and retry idempotently.
- Preserve source order/payment IDs and the exact cost/market mappings and COGS snapshot used for each accepted sale so later master-data changes do not silently rewrite history.
- Capability 16 provides a market-day session, Square import and settlement visibility, product availability, closeout, and the ADMIN/MANAGER/VIEWER permission model over Capability 14's canonical services. Square's app/POS outside MBS captures every actual sale; MBS does not capture sales or count cash.
- **Done when:** every accepted Square sales line has a source-specific identity, date-effective cost, and market/channel assignment; a market operator can open a session, use Square for every sale, view imported tender and settlement status, and close a visit; unresolved lines and close exceptions remain visible; retries never duplicate accepted sales. The `sales-mvp` profile in Capability 10 and the MVP 2 measures in [the implementation-readiness gate](02-implementation-readiness.md) must pass before promotion.


## MVP 3 — Products, Recipes & Costing

**Goal:** Expand the lightweight MVP 1 recipe data into the product, ingredient, sourcing, and costing system.

**In scope**
- Expand the MVP 2 Variation ID product/cost records into full masters. Recipe-made variations gain effective recipes with canonical purchased ingredient/supply inputs; directly resold variations retain their MVP 2.2a canonical purchased-item link (D-52). Do not manufacture a purchased item for a recipe output. Extend the MVP 2 reviewed count-pack posting to full unit conversions and dated cost history without reposting any already approved receipt line; receipt amount/cost, not the planned list, supply actual purchase facts (D-53; CO-001; DS-001).
- Require a Shelf Life on every stocked product, ingredient, and supply when it is first added: a duration in days, weeks, or months, or `never` for durable items such as empty packaging cups. The confirmed answer is remembered on the item and becomes the default for every future lot. Set the target replenishment quantity and inventory unit for each item, and a mandatory output shelf life on each recipe.
- Use approved receipt purchases and recorded made quantities as starting stock sources, never Market Planning targets; do not perform physical inventory counts. Record Square line quantities, transfers, dispositions, and expiry movements without double-posting. For `never` items only, provide an audited expected-inventory override screen; perishable items always follow their Shelf Life and cannot be overridden.
- Manual and receipt-linked ingredient/product/supply purchases with retailer, canonical store/location, quantity/unit, actual cost, receipt link, and effective-dated unit-cost history. Every purchase resolves through the MVP 1 canonical store and store-item-to-canonical-item mapping; a purchase may not be keyed by a typed store or item name.
- Date-specific recipe/product cost calculations, preferred source, product readiness/cost-review flags, and ingredient cost-history table/chart.
- Reconcile/update the minimal ingredient and recipe records created in MVP 1 without losing receipt links or history.

**Done when:** a product's recipe and cost can be traced to dated purchases and locations, and prior costs remain unchanged. The `costing-mvp` profile in Capability 10 and the MVP 3 measures in [the implementation-readiness gate](02-implementation-readiness.md) must pass before promotion.

## MVP 4 — Shopping Lists & WhatsApp

**Goal:** Plan what to bring to a market, what ingredients to buy, and send the generated list through WhatsApp.

**In scope**
- Capability 15 provides Market Load Lists by market/date and product Variation ID/desired allocation (for example, 12 X and 10 Y), with copy-previous-list support. Per-market targets share the single planned quantity for each product in the ordered set; they do not create separate starting stock (D-47/D-51).
- Reuse the Market ID/name registry and dated visits established as Square prerequisites in MVP 2; full market-cost administration and route calculations remain with Capability 5 in MVP 5.
- Capability 15 expands the market plan with recipe-made product targets or direct-resale canonical items, ingredient details, and one combined store-grouped shopping list. Finalizing the list freezes the shopping estimate and initiates one explicitly confirmed WhatsApp batch (with print fallback). Approved receipts provide actual purchased quantities/costs; a later recorded made quantity may differ from the list and never triggers another message. Shopping uses expected balances from approved receipts, confirmed production, and accepted Square sales, not planned quantities. No physical counts are entered (D-53).
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
- Weekly product inventory snapshots consuming confirmed made quantities or approved direct-resale receipt restocks, accepted Square line quantities, samples, waste, transfers, and dispositions; ingredient and supply balances consume receipt purchases, confirmed recipe usage, and waste. Market targets remain estimates; no physical count adjustments exist (D-53).
- Each lot's unsold remainder becomes waste at `Perishable By`. An effective recipe may instead specify `waste_at_plan_end` so only its unsold produced output (for example fruit cups) wastes at final market close; unchecked recipe outputs follow their output Shelf Life. Direct Sell water has no recipe checkbox and follows its own item Shelf Life, carrying all 22 unsold bottles from a receipt-24/load-6/sale-2 example. Sold units never waste; expiry and final close cannot post waste twice (D-54/D-55).
- Reorder engine using units-consistent usage, lead time, safety stock, on-hand amount, preferred/last source, and estimated purchase cost.
- Enable automatic WhatsApp utility alerts for shelf-life-eligible stocked products, recipe ingredients, and operating supplies (`never` or at least `low_stock_alert_min_shelf_life_days`, default 30) when on-hand quantity reaches 20% or less of the confirmed target/replenishment quantity (100 ordered means alert at 20 remaining). Include last approved purchase store/location/date and Product URL when available; require a source record, opted-in recipient, approved template/window, and dedup/re-arm controls.

**Done when:** weekly balances reconcile, waste/carry-forward are correct, and alerts are driven by verified quantities. The `inventory-mvp` profile in Capability 10 and the MVP 6 measures in [the implementation-readiness gate](02-implementation-readiness.md) must pass before promotion.

## MVP 7 — Dashboards, Rankings & Forecasting

**Goal:** Add the workbook's decision-support features after the underlying sales, costs, markets, and inventory are reliable.

**In scope:** Operations and Executive dashboards, scorecards, rankings, opportunity scores, forecasts, test-record isolation, refresh orchestration, and source lineage.

**Done when:** dashboard totals reconcile to approved source records and every applicable source-workbook intent is either tested as an application behavior or recorded as a justified `NOT_APPLICABLE` case. Tax-specific application tests and final release controls remain for MVP 8. The `analytics-mvp` profile in Capability 10 and the MVP 7 measures in [the implementation-readiness gate](02-implementation-readiness.md) must pass before promotion.

## MVP 8 — Tax Workpapers & Full-System Release

**Goal:** Produce filing support and certify the integrated application.

Synthetic draft tax profiles and mappings can be built after preceding executable local profiles pass. U-7 tax-professional signoff, owner-supplied provider coverage, and approved year-specific mappings gate real-year package generation/export; U-6 Proxmox readiness additionally gates full production promotion. Neither owner-only action blocks synthetic MVP 8 development.

**In scope:** Sole-proprietor Schedule C-aligned workpaper for Form 1040 use, applicable Florida business-tax schedules, source-document index, year snapshot, tax-professional review, tax-specific application tests, six plan-defined release controls, full-system certification using all applicable source-test intents plus all applicable application tests, Proxmox promotion, backup/restore and operational security review.

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
- Capability 14: canonical Square sales ledger and financial reconciliation in MVP 2.
- Capability 15: market load lists, store-grouped shopping, and prep confirmation in MVP 4.
- Capability 16: market-day sessions, Square settlement visibility, availability, preorders, stall readiness, and customer-facing product information in MVP 2; it consumes Capability 14 and feeds Capability 6.
