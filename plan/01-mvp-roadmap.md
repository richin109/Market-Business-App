# MBS MVP Delivery Roadmap

This roadmap sets release order; capability numbers are functional areas. Before building MVP N+1, MVP N's local synthetic profile, real entry points, migrations, and acceptance evidence must pass. Owner-only data/provider/production gates do not block later synthetic work. Promotion requires the full profile and all applicable predecessor profiles on the same candidate, plus real-data/provider/restore gates. No failed predecessor may be bypassed. Track schema with SQLAlchemy/Alembic and changed UI with Playwright (Capabilities 10/11).

## MVP 1 — Receipt Capture, Review & Storage

**D-77:** PostgreSQL is the sole runtime/test DB for MVP 1–8. Follow the [PostgreSQL contract](00-overview.md#postgresql-contract-all-stages) and [stage matrix](mvp-slice-specifications.md#postgresql-stage-acceptance). Keep SQLAlchemy/Alembic/core generic; a URL change does not certify another backend.

**Goal:** Extract each accepted receipt once; let users correct it and reuse saved results.

**In scope**
- Authenticated upload of image/PDF, file validation, status/progress, receipt list/detail, manual correction, exact/near-duplicate safeguards, audit trail, and soft delete.
- MANAGER+ manual receipt entry with no image/PDF (audited manual source identity, canonical store selection, manual store-product identifier; D-66).
- Batch/directory upload with duplicate protection, limits, and multi-file fallback (RM-020, RM-025).
- Side-by-side receipt review page with editable extracted values and package count × pack size × pack unit capture (RM-021).
- Canonical stores/aliases auto-created from order text, with store management (ST-001/002; D-37).
- Purchased identity = canonical store + store product ID → canonical item, with common names (IT-001; D-38/39).
- Item mapping screen with ranked suggestions and audited remap (IT-002, D-40).
- Order-history screen with links to saved header and item details (RM-019).
- S17 media service and item/store-item galleries (320/1024px, replace prompt); no generated images (IM-001/002; D-41–44).
- Multi-PDF receipt association without duplicate line counts; reconciliation to printed subtotal (RM-022).
- Verification of local OCR against synthetic image-only and selectable-text PDFs (RM-023).
- Real PDF imports only after an approved fail-closed scanner is installed and validated in the promoted candidate; mocked scanning is limited to synthetic development (D-09).
- Isolated offline evaluation against private local `receipts/` directory after explicit authorization (RM-024).
- Local Tesseract/OpenCV with persistent files/PostgreSQL (normalized header/items, raw OCR JSONB, versioned canonical JSONB).
- Four receipt-line dispositions (Personal, Ordinary Business Purchase, Recipe Ingredient, Capital Asset) with remembered defaults and pending routing intents.
- Docker Compose local deployment with Postgres, Redis/Celery, persistent file storage, migrations, health check, and tested backup/restore.
- *Execution contract:* See active and queued items in [03-current-slice.md](03-current-slice.md).

**Deferred:** Optional Google Document AI integration (with separate privacy and cost approvals), full cost/accounting logic, multi-receipt business dashboards, Square data, weekly operations, inventory valuation, tax packages, and messaging.

**Done when:** managers can upload or manually enter receipts, review/correct/classify lines, and retrieve saved results after restart without OCR rerun or duplicate overwrites. Imports auto-create stores/aliases; each line resolves by store + product ID to a canonical item; display falls back to order text until renamed. RM-025: unchanged directory adds nothing; an authorized changed source adds only new complete orders; ambiguity stays held. IM-001/002: images resolve owner primary → canonical primary → placeholder; no image never blocks review/approval. Promotion requires local Tesseract/OpenCV, fail-closed PDF scanning, PostgreSQL persistence, approved accuracy/review thresholds, `receipt-mvp`, and MVP 1 readiness measures.

## MVP 2 — Square Catalog, Products, Recipes & Costing
**Goal:** Establish Square identity and market prerequisites, then complete product/recipe/ingredient costing before any sale so each accepted sale has a real derived cost.

Use full `YYYY-MM-DD` dates and multi-year effective periods; resolve history by each sale's complete business date.

**D-63:** Sales/market-day move to MVP 3, after recipes. Provisional costs and recipe-bound `Made N` without consumption are off-path; D-56 is contingency-only.

**In scope**
- Stage A: Capability 3 syncs Catalog and stages stable Item/Variation IDs. Before activation, verify read-scoped credentials and block every non-allowlisted/mutating call pre-network, including retry/admin paths; Sync Now writes MBS staging only.
- Stage B: create Variation-ID products only after Shelf Life (including `never`); add Market/Location/channel mappings, effective hours, and explicit dated visits. Planned visits are not attendance; Square variations are not purchased items (D-52).
- Add Capability 15's ordered dated `MarketPlan` with editable per-Variation targets; Capability 5 supplies saved markets/visits/hours. Targets estimate shopping/prep, never stock (D-53; MP-004). Recipe-aware lists/WhatsApp are MVP 4.
- Slice 2.2a: classify approved receipt lines as Direct Sell stock, resolve canonical item and reviewed count pack (24-pack → 24 each), and post once per occurrence. Hold unknown/ambiguous units or prior expenses (D-55; DS-001).
- Stage C: 2.3 adds sourcing mode; 2.4 validates effective recipes/canonical inputs; 2.5 adds dated purchase costs before READY. Direct Sell retains its 2.2a item link; recipe outputs are not purchased items (D-52). Extend count posting to conversions/cost history without replay; receipts, not targets, are purchase facts (D-53; CO-001; DS-001).
- Require/remember Shelf Life for every stocked product/ingredient/supply; allow days/weeks/months/`never`, no default. Require replenishment target/unit per item and output Shelf Life per recipe.
- Support manual/receipt-linked ingredient/product/supply purchases with retailer, canonical store/location, quantity/unit, actual cost, receipt link, and dated unit cost. Resolve via MVP 1 store/item identity; never key by typed names.
- Calculate recipe/product costs as of business date; label carry-forward, block absent prior cost, and expose preferred source, readiness/review flags, ingredient history/chart (D-57; CS-001).
- Only approved receipts add MVP 2 stock; never targets. MVP 3 registers made/Square movements via same reader. No counts. Only `never` items allow audited expected-inventory override; perishables follow Shelf Life.
- Update MVP 1 minimal ingredient/recipe records without losing receipt links/history.
- Build one `StockBalanceReader` now (D-59 option B) for approved receipts, made/consumed quantities, accepted Square lines, transfers, dispositions, expiry, and market/shopping/report reads. No alternate reader at any stage.

**Done when:** recipe/cost traces to dated purchases/locations; later repricing leaves prior costs unchanged; one reader supplies every balance. Pass `costing-mvp` and the MVP 2 readiness measures before promotion.

## MVP 3 — Sales Activation & Market-Day Selling
**Goal:** Activate the shared Square ledger and market-day visibility with traceable facts and MVP 2 costs.

**In scope**
- Capability 3 stages Orders/Payments; Capability 14 accepts lines only with Variation ID, effective cost, and resolved visit/channel. Market lines must also fit effective local hours or have an authorized exception. Payments never creates a second sale. Costs come from MVP 2; no provisional estimate.
- Square alone records sales, including cash. Capability 14 imports/accepts sales and links product, date, channel/market, amounts, tax, tender, refunds, corrections for reporting/tax reconciliation.
- Use permanent `Order ID + Line Item UID`, cursor sync, replay/update/refund reconciliation, staging, audit. No manual MBS sales. Local attribution/inventory adjustments use separate idempotent events and never replace Square facts.
- Reconcile orders, discounts, refunds, provider tax, payments, net deposits; this is not tax liability. Keep actual fees distinct from estimates. Tax workpapers remain MVP 8.
- Keep unresolved lines in visible exceptions; accept valid lines independently; retry staged failures idempotently.
- Snapshot source order/payment IDs and exact cost/market/COGS per accepted sale; later master changes cannot rewrite them.
- Record made quantity per recipe-made Variation ID; one audited idempotent event adds finished stock and consumes effective recipe inputs. Square lines subtract reported quantity; targets never add stock (D-53).
- Capability 16 supplies role-based sessions, import/settlement, availability, closeout; read only via MVP 2 `StockBalanceReader` and Capability 14 services. Square captures all sales; MBS never enters sales/counts cash.
- **Done when:** each accepted line has permanent source identity, effective recipe/direct-item cost, and market/channel; operators can run sessions, view tender/settlement, close visits; exceptions stay visible; retries never duplicate. Pass `sales-mvp` and MVP 3 readiness measures.


## MVP 4 — Shopping Lists & WhatsApp

**Goal:** Plan market loads/purchases and send finalized lists through WhatsApp.

**In scope**
- Capability 15 provides dated Market Load Lists by Variation ID/desired allocation, with copy-previous. Targets share one set quantity per product and create no stock (D-47/D-51).
- Reuse MVP 2 market IDs/dated visits; full costs/routes are Capability 5 in MVP 5.
- Capability 15 adds recipe-made targets/direct-resale items, ingredients, and one store-grouped list. Finalize to freeze the estimate and start one explicitly confirmed WhatsApp batch; retain print fallback. Receipts provide actual purchases; later made quantities do not resend. Shopping reads approved receipts, confirmed production, accepted sales, never targets; no counts (D-53).
- WhatsApp Cloud API: manually send to ≥2 opted-in recipients; support add-more, private per-recipient delivery, templates, consent/opt-out, cost estimate, delivery status. Keep print/export.
- Capability 15 confirms prep through Capability 5's shared service; post ingredients, supplies, and product quantities once. Unconfirmed plans do not change stock. Capability 5 adds weekly entry/corrections in MVP 5.

**Done when:** dated targets produce a printable store-grouped ingredient list sendable to chosen recipients. Stock alerts wait for MVP 6. Pass `prep-mvp` and MVP 4 readiness measures before promotion.

## MVP 5 — Markets & Weekly Operations

**Goal:** Record attendance and related market operations.

**In scope**
- Extend MVP 2 markets/locations/dated visits with effective costs, fees, overlap validation, attendance/status/score/notes/history, and audited cancellation without deleting linked records. Support multiple markets/date and past/future dates; only explicit attendance counts.
- Store/reuse directed route legs; choose Home/direct itinerary, calculate miles/cost, audit exact allocation.
- Capability 5 extends Capability 15 prep via shared production service for weekly entry/corrections. Add samples, dated supply use, audited expenses; link lists to visits; targets are not production.

**Done when:** market/date, route, production, and expenses are captured once and feed inventory/reporting. Pass `markets-mvp` and MVP 5 readiness measures before promotion.

## MVP 6 — Inventory & Reorder

**Goal:** Reconcile actual sales, production, purchases, and expiry waste into trustworthy weekly balances.

**In scope**
- Snapshot product stock from made quantities, approved Direct Sell receipts, accepted Square lines, samples, waste, transfers, dispositions; ingredients/supplies from purchases, recipe use, waste. Targets remain estimates; no physical counts (D-53).
- Waste unsold lots at `Perishable By`; effective recipe `waste_at_plan_end` may waste only its unsold output at final close; other outputs follow Shelf Life. Direct Sell water follows item life (receipt 24/load 6/sale 2 leaves 22 overall). Never waste sold units or double-post expiry/final-close waste (D-54/55).
- Reorder from unit-consistent usage, lead time, safety stock, on-hand, preferred/last source, estimated cost.
- Send automatic WhatsApp utility alerts at ≤20% of confirmed target for eligible `never` or shelf life ≥ `low_stock_alert_min_shelf_life_days` (default 30) products/ingredients/supplies. Include last approved source/location/date and URL when available; require source, opt-in, approved template/window, dedup/re-arm.

**Done when:** weekly balances reconcile, waste/carry-forward is correct, and alerts use verified quantities. Pass `inventory-mvp` and MVP 6 readiness measures before promotion.

## MVP 7 — Dashboards, Rankings & Forecasting

**Goal:** Add decision support after sales, costs, markets, and inventory are reliable.

**In scope:** Operations and Executive dashboards, scorecards, rankings, opportunity scores, forecasts, test-record isolation, refresh orchestration, and source lineage.

**Done when:** dashboard totals reconcile to approved sources; each applicable workbook intent is tested or justified `NOT_APPLICABLE`. Tax tests/release controls remain MVP 8. Pass `analytics-mvp` and MVP 7 readiness measures before promotion.

## MVP 8 — Tax Workpapers & Full-System Release

**Goal:** Produce filing support and certify the integrated application.

Build synthetic drafts after predecessor local profiles pass. U-7 professional signoff/provider coverage/year mappings gate real-year export; U-6 Proxmox readiness gates production. Neither blocks synthetic development.

**In scope:** Sole-proprietor Schedule C-aligned Form 1040 support, applicable Florida business-tax schedules, source index/year snapshot, professional review, tax tests, six release controls, full-system/source-test certification, Proxmox, backup/restore, security review.

**Done when:** full-system certification passes. The app prepares, never signs/files returns. Pass `full-mbs`, all six Capability 10 controls, and MVP 8 readiness measures before promotion.

## Capability Mapping & Shared Foundations

- Capabilities 1–2: MVP 1.
- Capability 3: Catalog sync/staging MVP 2; Orders/Payments MVP 3.
- Capability 4: minimal ingredient/recipe links MVP 1; full product/recipe/cost MVP 2, before sales (D-63).
- Capability 5: market/location/hours/visits MVP 2; shared production service MVP 3 (D-60); full costs/weekly ops MVP 5.
- Capability 5 hours use year-bearing effective periods; expand/validate annual patterns per year before attribution.
- Capability 6: one MVP 2 `StockBalanceReader` with approved receipt purchases/made-event sources; full inventory/reorder/alerts MVP 6. Targets never source stock (D-51/53); never add another reader (D-59).
- Capabilities 7–8: MVP 7.
- Capability 9: security/audit/secrets/settings from MVP 1; add business settings with owning capability.
- Capability 10: stage-specific profiles; 110-test/six-control certification is full MBS, not receipt MVP.
- Capability 11: Compose, persistence, auth, backup/restore begin MVP 1; Proxmox later.
- Capability 12: MVP 8.
- Capability 13: message/consent MVP 4; inventory alerts MVP 6.
- Capability 14: canonical Square ledger/reconciliation MVP 3.
- Capability 15: load lists, grouped shopping, prep confirmation MVP 4.
- Capability 16: sessions, settlement, availability, preorders, readiness, customer info MVP 3; consume Cap 14/MVP 2 reader and feed Cap 6.
