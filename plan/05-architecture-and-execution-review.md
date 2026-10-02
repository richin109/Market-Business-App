# Architecture and Execution Review

Review date: 2026-10-02. Scope: the MBS plan set, including the overview, roadmap, readiness gate, active slice, go/no-go assessment, slice specifications, capability files, and test-case manifest. This is a planning review only; no application code was changed.

## Verdict

The chosen deployment shape is appropriate for this business: a PostgreSQL-backed modular monolith, server-rendered web UI, background workers, and explicit provider adapters. The plan also correctly keeps Square as the sale system of record, treats receipts and provider imports as evidence, and separates synthetic development from live-data promotion.

The primary risk is not the technology stack. It is that several documents assign the same writes to different capabilities and repeat detailed rules without a single owner for each persisted fact. That will lead to competing ledgers, cross-context ORM access, circular imports, and inconsistent retries unless the ownership contract below is applied before MVP 2 work begins.

## Findings

1. **High: inventory write ownership is ambiguous.** D-60 and Capability 5 say the production service creates finished-stock, ingredient, supply, and waste movements. Capability 6 describes owning the inventory movement ledgers, while MVP 2 and MVP 3 already create receipt and production stock effects. The plan must distinguish ownership of a business event from ownership of the canonical stock ledger.
2. **High: market planning has two apparent owners.** Capability 5 describes the one-time ordered market-set plan, while Capability 15 owns market plans, load lists, shopping, and prep. MVP 2 starts the minimal plan and MVP 4 expands it, but the record owner and write API are not explicit.
3. **High: no explicit cross-context transaction contract.** Receipt routing, sale acceptance, production, cost history, and allocations must atomically update multiple records. The plan requires atomicity but does not consistently state which service orchestrates the use case, which context owns each table, or how contexts share a transaction without importing one another's ORM models.
4. **High: MVP 6 ledger wording conflicts with earlier writers.** Receipt restock, ingredient/supply purchase, production, sales, and allocation movements are introduced in MVP 2–3. MVP 6 must reconcile and extend that same ledger, not introduce a second movement model or replay earlier facts.
5. **Medium: MVP 1 is a wide vertical slice.** It combines OCR, source/version review, identity registries, routing, expenses/assets, media, retention, and backup. These are defensible release requirements, but treating them as one undifferentiated implementation step creates long feedback cycles. Keep the release boundary, but implement in explicit dependency-ordered sub-slices and require each to pass its own entry-point and migration checks.
6. **Medium: physical schema and conceptual naming can drift.** Capability text mixes naming forms such as `tblProductSetup`, `tblIngredients`, and `tbl_receipt_items`. Future schema work needs one mapping from domain entity to Python model, physical table, owning capability, and source-event key. Do not rename delivered revisions or tables merely to normalize old names.
7. **Medium: central failure handling is not closed.** Capability 9.3 says the error-log table has no writer; the release profiles do not clearly identify the slice that delivers a usable failure taxonomy/writer. Decide and assign that before treating the receipt release profile as complete. Audit events, expected business holds, and operational failures must remain distinct categories.
8. **Medium: plan duplication weakens change control.** Detailed rules and status counts are copied into the overview, roadmap, readiness document, go/no-go report, slice specs, and capability files. The manifest currently has 169 data rows (147 PLANNED, 22 VERIFIED); 117 rows have no runnable validation command. Duplicated snapshots will drift unless they are explicitly dated and subordinate to the owning artifact.
9. **Low: the MVP 4 slice table is malformed.** Slices 4.2 and 4.3 have been concatenated into one broken Markdown row, obscuring the acceptance boundary.

## Corrected Architecture

Keep one deployable application with bounded contexts inside `src/mbs/`. Do not add microservices, a second frontend build, or a general plugin framework. A context owns its domain rules and persisted facts; other contexts call its service API rather than reading or mutating its ORM models directly. Create an abstraction only at an actual boundary (database transaction, file storage, OCR, Square, or Meta).

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

- Keep approved business rules in the owner decision register. This review clarifies component responsibility only; it does not approve a new business rule or override an approved decision.
- Keep cross-cutting architecture in the overview and this boundary matrix; capability files define only their owned facts and service contracts. Roadmap prose describes stage outcomes. Slice specifications contain acceptance criteria; `03-current-slice.md` names the one active task and its evidence. The manifest tracks test traceability, not implementation authorization.
- On conflict, stop before implementation and reconcile the owning decision/capability/slice artifacts. Do not copy a changed rule into every document; update the owner and the directly affected contracts, then record the change and affected tests.
- A stage is complete only when its profile runs through real application entry points, PostgreSQL migrations and browser workflows; all producer/consumer contracts are exercised; errors/holds have a visible resolution path; and the manifest links verified tests and runnable commands. A passing component test alone is not stage evidence.
- Preserve two independent gates: synthetic local predecessor readiness permits the next stage to be developed; production promotion requires the separately named privacy, provider, recovery, security, and owner approvals. Never make real-data approval a prerequisite for synthetic work unless the specific test would process private data.

## Immediate Plan Reconciliation

1. Keep the active queue at D-77 full candidate validation and critical review, then S13 timed restore/restart, then S18-local. Do not start MVP 2 until those gates pass.
2. After D-77, S13, and S18-local pass and an MVP 2 slice is selected, copy the Capability 6 ledger and Capability 15 plan ownership contracts into that active slice; do not start this work ahead of the current queue.
3. Keep Capability 9.3 as the owner of the error-log writer and taxonomy; verify its upload/OCR/import entry-point coverage as part of S18-local and the `receipt-mvp` profile rather than creating an unsequenced parallel task.
4. Resolve or explicitly preserve each open readiness/owner gate (including RM-022 production policy, RM-023 field-authority/evidence, F43 branch identity, F44 shared-item allocation, private-corpus authorization, and PDF scanning); do not silently promote a conditional path to supported behavior.
5. Bring manifest validation commands to 169 unique cases with actual commands/results as their test contracts. At this review, 117 rows still lack a validation command.