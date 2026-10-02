# Architecture and Execution Review

Review date: 2026-10-02. Scope: all MBS plan docs and manifest. Planning-only; no application code changed.

## Verdict

The PostgreSQL modular monolith, server-rendered UI, workers, and provider adapters fit. Square remains sales system of record; receipts/imports are evidence; synthetic work is separate from live-data promotion.

Primary risk: documents assign writes to multiple capabilities and repeat rules without a fact owner, risking duplicate ledgers, cross-context ORM access, circular imports, and inconsistent retries. Apply the ownership contract before MVP 2.

## Findings

1. **High: inventory ownership.** D-60/Cap 5 owns production events; Cap 6 owns stock ledger; MVP 2–3 already write stock. Separate business-event ownership from canonical ledger ownership.
2. **High: planning ownership.** Cap 5 and Cap 15 both appear to own plans. Name the record owner/API across MVP 2 start and MVP 4 expansion.
3. **High: cross-context transactions.** Define orchestration, table ownership, and shared transaction handling for routing, sales, production, costs, allocations without cross-context ORM imports.
4. **High: MVP 6 ledger.** Reconcile/extend MVP 2–3 receipt, production, sales, allocation movements; never create a second ledger or replay facts.
5. **Medium: MVP 1 breadth.** Keep release scope but split OCR, identity, routing, media, retention, and backup into dependency-ordered slices with entry-point/migration checks.
6. **Medium: schema naming.** Map domain entity → Python model → physical table → owner → event key; do not rename delivered objects/revisions for consistency.
7. **Medium: error handling.** Assign Capability 9.3's taxonomy/writer before receipt release; keep operational errors, business holds, and audit events distinct.
8. **Medium: duplicated plan facts.** Rules/statuses repeat across docs; 169 manifest rows (147 PLANNED/22 VERIFIED), 117 lack commands. Date subordinate snapshots and keep authority in owning docs.
9. **Low: MVP 4 table.** Repair the joined 4.2/4.3 row so boundaries are clear.

## Corrected Architecture

Keep one deployable app with bounded contexts in `src/mbs/`; no microservices, second frontend build, or plugin framework. Contexts own rules/facts; others call services, not ORM tables. Abstract only real boundaries (transactions, files, OCR, Square, Meta).

| Capability | Owns and writes | Does not own |
|---|---|---|
| 1 Receipt Capture & OCR | Immutable source files, upload/OCR job state, extraction candidates, provider/version evidence | Canonical business purchases or stock postings |
| 2 Receipts Management | Canonical receipt/line occurrences, review/correction, source association, store/alias/item identity, receipt routing records, shared media assets | Consumer purchase facts or stock movements |
| 3 Square Integration | Square credentials/allowlist, raw Catalog/Order/Payment staging, cursors and provider-sync runs | Accepted sales, COGS, or inventory effects |
| 4 Product/Recipe/Costing | Variation/product setup, recipe versions, ingredient/supply purchase and cost facts, derived as-of costs/readiness | Canonical stock movement ledger or accepted Square sales |
| 5 Markets & Weekly Operations | Markets/visits/routes, the production-event lifecycle and corrections, business expenses and asset records | Stock ledger implementation or a second production/expense path |
| 6 Inventory | Canonical lots, signed stock movements, allocation commands, balance query implementation, period snapshots, expiry and valuation | Receipt, sale, recipe, or production source facts |
| 7 Rankings & Forecasting | Ranking/forecast calculations and versioned outputs | Source facts or dashboard publication orchestration |
| 8 Dashboards & KPIs | Read models, refresh versions, coherent KPI publication and lineage | Independent cost, balance, or exception calculations |
| 9 Settings & Governance | Settings catalog, authentication/authorization, audit/error taxonomy and shared policy enforcement | Business-context records or provider business facts |
| 10 Testing & Release | Test profiles, manifest evidence, release controls | Runtime business behavior |
| 11 Deployment & Infrastructure | Images, Compose/deployment, migrations operation, backup/restore | Domain policy |
| 12 Tax Support | Tax mappings, year snapshots, workpapers and exports | Source accounting facts or filing/signature decisions |
| 13 WhatsApp | Consent, outbound message batches, delivery state and webhook processing | Shopping-list or low-stock decisions |
| 14 Sales Ledger | Canonical accepted Square order lines, refunds, reconciliation, immutable market/cost snapshots | Provider transport or inventory ledger tables |
| 15 Shopping & Prep | Market-plan target extensions, load/shopping lists, finalization and prep UI | Market/visit identity, production ledger, or stock ledger |
| 16 Market-Day Operations | Session lifecycle and operator UI, invoking sales, production, and allocation services | Local sales, production, or inventory ledgers |

**Write and transaction contract**

- The source context owns the business event; Capability 6 alone owns stock lots/movements and balance calculations. Capability 5's production use case owns the Made N event and calls Capability 6's posting operation. Capability 4 purchase posting and Capability 14 sale acceptance do the same for their events. Capability 15 and 16 are callers, not alternate writers.
- Each use case has one orchestration service and one transaction boundary. Pass the active SQLAlchemy session/unit of work through the call chain; the top-level use case commits or rolls back. Context services validate and write only their own tables. No cross-context ORM relationship or direct table mutation is allowed.
- Cross-context commands carry stable source identity, idempotency key, actor/reason when required, and the expected source/version. Reads use explicit query services or DTOs. External calls happen after commit through an outbox/workflow record; never hold database locks across provider calls.
- Capability 2's approved receipt-line routing record is the durable handoff. A consumer claims only its own destination record and writes its own purchase/expense/asset fact. Receipt approval never directly writes Capability 4 or 6 facts. Corrections append reversals/replacements in the owning context.
- Capability 6 establishes the foundational lot/movement and allocation model with the first MVP 2 stock writer. Later purchase, production, sale, transfer, disposition, and expiry writers register against that model. MVP 6 adds full period snapshots, valuation, expiry automation, and restatement/reconciliation; it does not create a parallel ledger.
- Capability 15 owns the `MarketPlan` identity from its minimal MVP 2 form through its MVP 4 expansion. Capability 5 owns `Market`, `MarketVisit`, operating hours, and attendance. Capability 16 owns `MarketSession`, linked to a visit, and invokes the shared plan/allocation/sales services.
- Use PostgreSQL as the only supported runtime and database-test engine. Keep SQLAlchemy/Alembic and domain logic generic where straightforward, but do not build or claim alternate-database support. Use the established physical naming convention for delivered objects; document the entity-to-model/table mapping before adding each new schema group.

## Corrected Delivery Sequence

This clarifies ownership and schema timing without changing approved business behavior or MVP numbering. The active-slice document remains the sole implementation authorization; no future stage starts from this table alone.

| Stage | Deliver in order | Gate / explicit non-goal |
|---|---|---|
| Foundation | PostgreSQL configuration, migrations, auth, audit/error conventions, test/CI and protected file storage | No production data before readiness and restore gates |
| MVP 1 | (1) upload/outbox/OCR/source evidence; (2) canonical receipt review/corrections and identity; (3) destination routing and thin drafts; (4) media; (5) backup/recovery and `receipt-mvp` | Keep OCR evidence separate from approved business facts. Complete S13 and S18-local before synthetic MVP 2; S18-production remains a separate authorization/scanner/accuracy gate |
| MVP 2 | (1) read-only Catalog adapter and staging; (2) market/location/visit prerequisites and the minimal Capability 15 plan; (3) product/recipe/unit masters; (4) receipt routing consumers for Direct Sell, ingredients, supplies, costs; (5) foundational Capability 6 lots/movements/allocation plus the single `StockBalanceReader`; (6) `costing-mvp` | No Orders/Payments staging or sale acceptance; no plan quantity as stock; no production events or provisional costs |
| MVP 3 | (1) Orders/Payments staging; (2) canonical per-line acceptance and cost/market snapshots; (3) Capability 5 production-event service; (4) Capability 6 production/sale/allocation writers; (5) Capability 16 session UI and settlement visibility | Every accepted sale has resolved product, cost, market/channel and immutable source identity; no local sale ledger |
| MVP 4 | Expand the same market plan into shopping/load lists; finalize/version lists; invoke Capability 5 production and Capability 13 messaging | Do not create a second plan, balance, or production model; sends are explicit and idempotent |
| MVP 5 | Market costs, route and attendance workflows, expenses/assets, weekly UI over the existing production service | No duplicate visit, expense, asset, or production identity |
| MVP 6 | Reconcile existing stock events; add weekly snapshots, FEFO valuation, expiry/waste jobs, closed-period restatement and reorder/alerts | No duplicate movement ledger; preserve original event and close versions |
| MVP 7 | Versioned refresh/read models, rankings, forecasts, dashboards and source-test intent transformations | Publish only coherent refresh versions; consume shared blocked results |
| MVP 8 | Tax profiles/mappings, reconciled frozen workpapers, full certification and deployment | Synthetic work may proceed after predecessors; real-year export and production require owner/provider/tax-professional gates |

## Plan Governance and Completion Rules

- Owner decisions remain business authority; this review clarifies technical ownership only.
- Overview owns cross-cutting architecture; capability files own facts/contracts; roadmap defines stage outcomes; slice specs define acceptance; `03-current-slice.md` owns active task/evidence; manifest tracks tests, not authorization.
- On conflict, stop and reconcile owning docs. Update only the owner and affected contracts; record changed tests.
- Complete a stage only after real-entry-point profile, PG migrations, browser workflows, producer/consumer contracts, visible error/hold resolution, and manifest commands/results pass. Unit tests alone are insufficient.
- Keep local development and production gates separate. Private-data local tests and detailed local diagnostics are owner-authorized on 2026-10-02; keep inputs/outputs ignored/external and untracked. Redaction applies only before sharing/committing evidence. Production/provider approvals and reviewed ground truth for accuracy acceptance do not block exploratory local tests.

## Immediate Plan Reconciliation

1. Queue: D-77 candidate/review → S13 synthetic restore/restart → S18-local. Keep the timed production RPO/RTO drill as a separate promotion gate; do not start MVP 2 before S18-local.
2. After these gates, copy Capability 6 ledger and Capability 15 plan ownership into the selected MVP 2 slice.
3. Keep Capability 9.3 as error writer/taxonomy owner; verify upload/OCR/import entry points in S18-local/`receipt-mvp`, not a parallel task.
4. Resolve or preserve RM-022 production policy, RM-023 authority/evidence, F43/F44, private-corpus production accuracy acceptance, and production PDF scanning. Local private-corpus use is already owner-authorized. Do not silently promote conditional behavior.
5. Add actual commands/results to all 169 unique manifest cases; 117 currently lack commands.