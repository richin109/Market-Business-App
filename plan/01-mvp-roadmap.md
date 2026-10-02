# MBS MVP Delivery Roadmap

This roadmap defines deployable release order. Capability numbers identify functional areas, not delivery order. Before the next MVP is built, the preceding MVP must be usable **locally with synthetic data**: its executable local profile subset, real entry points, migrations, and acceptance evidence must pass. Owner-only real-data evaluation, live-provider access, and production approval do not block later synthetic development. Production promotion of MVP N separately requires the complete named profile, real-data/provider/restore gates, and all applicable preceding profiles to pass for the same candidate. A failed predecessor local profile cannot be bypassed. Every MVP tracks schema with SQLAlchemy/Alembic and delivered browser UI with Playwright in its release profile (Capabilities 10/11).

## MVP 1 — Receipt Capture, Review & Storage

**Database rule for MVP 1-8 (D-77):** PostgreSQL is the sole runtime and database-test engine. Every stage follows the [shared PostgreSQL contract](00-overview.md#postgresql-contract-all-stages) and [stage-specific acceptance matrix](mvp-slice-specifications.md#postgresql-stage-acceptance). SQLAlchemy/Alembic and core services remain generic; changing a connection URL alone does not certify another backend.

**Goal:** Deploy a receipt application that extracts each accepted receipt once, lets the user correct it, and saves all resulting information for reuse.

**In scope**
- Authenticated upload of image/PDF, file validation, status/progress, receipt list/detail, manual correction, exact/near-duplicate safeguards, audit trail, and soft delete.
- MANAGER+ manual receipt entry with no image/PDF (audited manual source identity, canonical store selection, manual store-product identifier; D-66).
- Batch and directory upload with duplicate protection, bounded limits, and multi-file fallback (RM-020, RM-025).
- Side-by-side receipt review page with editable extracted values and package count × pack size × pack unit capture (RM-021).
- Canonical store registry auto-created from order text, alias grouping, and store management screen (ST-001, ST-002, D-37).
- Purchased-item identity keyed by canonical store + store product identifier, resolved to canonical item ID with common names (IT-001, D-38, D-39).
- Item mapping screen with ranked suggestions and audited remap (IT-002, D-40).
- Order-history screen with links to saved header and item details (RM-019).
- Media-asset service and galleries for items/store items, 320px/1024px sizes, and replace prompt; no AI image generation (S17; IM-001, IM-002, D-41–D-44).
- Multi-PDF receipt association without duplicate line counts; reconciliation to printed subtotal (RM-022).
- Verification of local OCR against synthetic image-only and selectable-text PDFs (RM-023).
- Real PDF imports only after an approved fail-closed scanner is installed and validated in the promoted candidate; mocked scanning is limited to synthetic development (D-09).
- Isolated offline evaluation against private local `receipts/` directory after explicit authorization (RM-024).
- Local Tesseract + OpenCV provider with persistent file and PostgreSQL storage (normalized header/items, raw OCR JSONB, versioned canonical JSONB).
- Four receipt-line dispositions (Personal, Ordinary Business Purchase, Recipe Ingredient, Capital Asset) with remembered defaults and pending routing intents.
- Docker Compose local deployment with Postgres, Redis/Celery, persistent file storage, migrations, health check, and tested backup/restore.
- *Execution contract:* See active and queued items in [03-current-slice.md](03-current-slice.md).

**Deferred:** Optional Google Document AI integration (with separate privacy and cost approvals), full cost/accounting logic, multi-receipt business dashboards, Square data, weekly operations, inventory valuation, tax packages, and messaging.

**Done when:** a manager can upload an image/PDF or manually enter a receipt without an attachment, review/correct, classify and link receipt lines, save, then retrieve all parsed data after a container restart without another OCR run; duplicate paths do not overwrite data or cause unnecessary OCR work. Imported orders create their stores automatically, alias spellings group into one renamed canonical store, and every purchased line resolves through canonical store + store product identifier to a canonical item whose displayed name falls back to the order name until a common name is entered. A repeated directory with unchanged files adds nothing, while an authorized changed source containing previously seen and new complete orders adds only the new identities; ambiguous identities remain visible review holds (RM-025). Confirmed receipt-embedded and uploaded images resolve through the single media-asset service to the owner's primary, then the canonical item's primary, then the default placeholder, and an item with no image remains fully reviewable and approvable (IM-001, IM-002). Local development may use the mocked OCR boundary and scanner, but promotion requires the configured local Tesseract + OpenCV adapter, fail-closed real-PDF scanning, persisted PostgreSQL state, approved accuracy/review thresholds, and a passing `receipt-mvp` profile. The MVP 1 measures in [the implementation-readiness gate](02-implementation-readiness.md) must also pass before promotion.

## MVP 2 — Square Catalog, Products, Recipes & Costing
**Goal:** Establish Square product identity and market prerequisites, then build the full product, recipe, ingredient and costing system **before** the first Square sale is ever accepted, so every accepted sale carries a real recipe-derived cost instead of a typed estimate.

All MVP 2 market dates and effective periods use full `YYYY-MM-DD` dates, including the year; schedules may span multiple calendar years and must resolve historical sales using the schedule effective on the sale's complete business date.

**Sequencing note (D-63):** sales activation and market-day selling moved to MVP 3 so that recipes precede the first accepted sale. Provisional product costs and provisional recipe-bound `Made N` lots are no longer part of the planned build path; D-56 is retained only as the rule that applies if such a lot is ever created, not as planned work.

**In scope**
- Stage A: Capability 3 syncs Square Catalog and stages stable Item/Variation IDs.
- Before Square activation, pass the read-only API gate in Capability 3: verify read-scoped credentials and prove the provider adapter rejects every non-allowlisted or mutating operation before network I/O, including from retries and admin-triggered sync. The local Sync Now command may write staging records in MBS but must never write to Square.
- Stage B: create sellable product records keyed by Variation ID with confirmed Shelf Life (including `never`) before persistence; create Market IDs, Location-to-Market/channel mappings, and effective-dated operating hours. Create dated visits explicitly; future planned visits do not count as attendance. A Square variation is not a purchased store item (D-52).
- Add a minimal Market Planning form with an ordered set of dated visits and editable target quantity per Variation ID. Targets estimate shopping/prep and create no stock (D-53; MP-004). Full recipe-aware shopping and list finalization/WhatsApp remain MVP 4.
- Add the receipt-backed stock path in slice 2.2a: explicitly classify an approved MVP 1 receipt line as stock rather than expense, resolve its canonical item and reviewed count package (one 24-bottle pack → 24 each), and post once by line occurrence. Missing/ambiguous units or an already-expensed line are review holds, not guessed stock (D-55; DS-001).
- Stage C: expand the Variation ID records into full masters. Slice 2.3 records a pending recipe-made sourcing choice; slice 2.4 validates effective recipes with canonical purchased ingredient/supply inputs, and slice 2.5 wires actual dated purchase costs before either sourcing mode becomes READY. Directly resold variations retain their 2.2a canonical purchased-item link (D-52). Do not manufacture a purchased item for a recipe output. Extend the reviewed count-pack posting to full unit conversions and dated cost history without reposting any already approved receipt line; receipt amount/cost, not the planned list, supply actual purchase facts (D-53; CO-001; DS-001).
- Require a Shelf Life on every stocked product, ingredient, and supply when it is first added: a duration in days, weeks, or months, or `never` for durable items such as empty packaging cups. The confirmed answer is remembered on the item and becomes the default for every future lot. Set the target replenishment quantity and inventory unit for each item, and a mandatory output shelf life on each recipe.
- Manual and receipt-linked ingredient/product/supply purchases with retailer, canonical store/location, quantity/unit, actual cost, receipt link, and effective-dated unit-cost history. Every purchase resolves through the MVP 1 canonical store and store-item-to-canonical-item mapping; a purchase may not be keyed by a typed store or item name.
- Date-specific recipe/product cost calculations resolved as of the business date being reported, carried-forward labelling, blocking when no earlier cost exists, preferred source, product readiness/cost-review flags, and the ingredient cost-history table/chart (D-57; CS-001).
- Use approved receipt purchases as MVP 2 stock sources, never Market Planning targets; later confirmed made quantities and accepted Square lines register behind the same balance interface in MVP 3. Do not perform physical inventory counts. For `never` items only, provide an audited expected-inventory override screen; perishable items always follow their Shelf Life and cannot be overridden.
- Reconcile/update the minimal ingredient and recipe records created in MVP 1 without losing receipt links or history.
- Build the single expected-inventory read interface here, not a temporary one (D-59 option B): one `StockBalanceReader` serves market-day availability, shopping, and reporting from approved receipt purchases, confirmed made events, recipe consumption, accepted Square line quantities, transfers, dispositions, and expiry. No second or interim balance path is created at any stage.

**Done when:** a product's recipe and cost can be traced to dated purchases and locations, prior costs remain unchanged when later weeks reprice, and one balance interface answers every stock question. The `costing-mvp` profile in Capability 10 and the MVP 2 measures in [the implementation-readiness gate](02-implementation-readiness.md) must pass before promotion.

## MVP 3 — Sales Activation & Market-Day Selling
**Goal:** Turn on the shared Square sales ledger and let a small business monitor imports, availability, settlement status, and market closeout without duplicate or untraceable facts — with real costs already in place from MVP 2.

**In scope**
- Capability 3 stages Square Orders/Payments; Capability 14 accepts each Square line only when its Variation ID, effective product cost, and dated market visit or explicit non-market channel resolve. A market line must also fall within the market's effective-dated operating hours in local time, unless an authorized exception is recorded. Payments never creates a second Square sales fact. The effective product cost is the MVP 2 recipe-derived or direct-item cost; no provisional estimate is accepted.
- Square remains the only sales-entry system, including cash-tender sales. Capability 14 imports and accepts Square sales, links them to product, date, channel/market, amounts, tax, tender, refunds, and corrections, and feeds shared reporting and tax reconciliation.
- Use stable Square Order ID + Line Item UID idempotency, cursor-based sync, replay/update/refund reconciliation, staging, and sync audit. MBS does not accept manually entered sales; audited local adjustments to market attribution or inventory use their own idempotent source/event IDs without replacing Square facts.
- Reconcile Square order amounts, discounts, refunds, Square-reported tax, Payments, and net deposits; this is transaction reconciliation only. Taxability decisions, liability calculations, and filing workpapers remain MVP 8. Distinguish actual fees from clearly labeled estimates.
- Keep unresolved lines in a visible import-exception queue, not the accepted sales ledger. Valid lines may be accepted while failing lines remain staged; correct prerequisites and retry idempotently.
- Preserve source order/payment IDs and the exact cost/market mappings and COGS snapshot used for each accepted sale so later master-data changes do not silently rewrite history.
- Record the quantity actually made per recipe-made Variation ID. This idempotent, auditable event creates finished-product stock **and consumes its effective recipe's ingredients and supplies**, because recipes exist before this point. Square sales subtract their reported line quantities; never add both target and made quantity (D-53).
- Capability 16 provides a market-day session, Square import and settlement visibility, product availability, closeout, and the ADMIN/MANAGER/VIEWER permission model over Capability 14's canonical services, reading availability through the MVP 2 `StockBalanceReader`. Square's app/POS outside MBS captures every actual sale; MBS does not capture sales or count cash.
- **Done when:** every accepted Square sales line has a source-specific identity, recipe-derived or direct-item date-effective cost, and market/channel assignment; a market operator can open a session, use Square for every sale, view imported tender and settlement status, and close a visit; unresolved lines and close exceptions remain visible; retries never duplicate accepted sales. The `sales-mvp` profile in Capability 10 and the MVP 3 measures in [the implementation-readiness gate](02-implementation-readiness.md) must pass before promotion.


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
- Capability 3: Square Catalog provider sync and raw staging in MVP 2; Orders/Payments sync and staging in MVP 3.
- Capability 4: minimal ingredient/recipe linking in MVP 1; full Product/Recipe/Costing in MVP 2, before any sale is accepted (D-63).
- Capability 5: minimal market directory, Square Location mappings, effective-dated operating hours, and dated visits in MVP 2; the shared production-event service in MVP 3 (D-60); full market-cost administration and weekly operations in MVP 5.
- Capability 5 operating-hour schedules are year-bearing effective-dated periods; recurring annual patterns must be expanded and validated per calendar year before they are used for sales attribution.
- Capability 6: the single `StockBalanceReader` and its expected-inventory movement sources (approved receipt purchases and recorded made events) in MVP 2; full inventory/reorder and automatic low-stock alerts in MVP 6. A Market Planning target is never one of those sources (D-51/D-53), and no second or interim balance path is built at any stage (D-59).
- Capability 7–8: MVP 7.
- Capability 9: security, audit, secrets, and required settings from MVP 1 onward; later business settings as their capabilities launch.
- Capability 10: phase-specific test/release profiles; the 110-test/six-control certification applies to full MBS, not the receipt-only MVP.
- Capability 11: Docker Compose, persistent storage, authentication, backups, and restore begin in MVP 1; Proxmox promotion follows when ready.
- Capability 12: MVP 8.
- Capability 13: message transport/consent in MVP 4 and automatic inventory utility alerts in MVP 6.
- Capability 14: canonical Square sales ledger and financial reconciliation in MVP 3.
- Capability 15: market load lists, store-grouped shopping, and prep confirmation in MVP 4.
- Capability 16: market-day sessions, Square settlement visibility, availability, preorders, stall readiness, and customer-facing product information in MVP 3; it consumes Capability 14 and the MVP 2 `StockBalanceReader`, and feeds Capability 6.
