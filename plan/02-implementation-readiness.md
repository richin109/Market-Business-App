# Implementation Readiness Gate

Status: **conditional go for local MVP 1 foundations only**. Do not ingest real receipts, enable live providers, or promote a release until every applicable item below is complete and approved by the business owner.

## Requirements Baseline & Change Control

- [ ] Record the approving owner, approval date, repository commit, and SHA-256 checksum for each governing source: `plan/00-overview.md`, `plan/01-mvp-roadmap.md`, all MVP 1 capability files, `plan/Python MBS v3.3 + Receipt OCR Blueprint.docx`, `support/Market_Business_System_v3_3_Testing_Dashboard.xlsx`, and `support/Walmart_Receipt_Complete_With_AI.xlsx`.
- [ ] Record each source artifact's title, path, version/date when available, and status (governing, reference-only, or superseded). The Devin MBS prompt is historical/reference-only for business requirements; its Java/Spring/React/Kubernetes stack is superseded by `plan/00-overview.md`.
- [ ] Classify `support/WDS_v2_1_Reconstruction_Grade_Specification 1.docx` and `support/Devin_MBS_v3_3_Prompt.docx` / `.txt` as reference-only or superseded, and record the approving owner and rationale; they are not independent authority for implementation choices.
- [ ] Resolve conflicting requirements before implementation. Precedence is: approved signed readiness decision, then `00-overview.md`, then `01-mvp-roadmap.md`, then capability files, then source documents/workbooks. A lower-precedence source must not silently override a higher-precedence requirement.
- [ ] Log a requirement change with its rationale, approving owner, affected capability, migration impact, and regression-test impact before implementing it.
- [ ] Complete `plan/test-case-manifest.csv`, mapping every MVP 1 acceptance criterion and each of the 110 source-workbook cases to source artifact/tab/cell or scenario, concrete application fixture and expected result, structural/behavioral test type, implemented automated test ID, runnable validation command, and release profile. It currently contains 133 rows: 124 `PLANNED` and 9 `VERIFIED`; 119 rows still lack validation commands. Planned rows may retain proposed future test IDs, but they do not count as coverage until the referenced file, command, and result exist. This does not satisfy the gate. Translate structural cases into executable application equivalents and update evidence from the actual repository before certification.

## Real-Data Privacy & Provider Approval

- [ ] 🧑‍💻 Approve a data classification for receipt scans, OCR payloads, receipt records, audit data, and backups; record the data owner and permitted users.
- [ ] 🧑‍💻 Approve local OCR accuracy/review thresholds and recovery from failed processing before MVP 1 production.
- Future optional Google Document AI activation separately requires approval of processor region, data-transfer terms, monthly spend limit, budget alerts, and uncertain-submission policy; see Capability 1's future enhancement. This is not part of the MVP 1 gate.
- [ ] 🧑‍💻 Approve retention periods and legal/operational hold rules for source files, raw OCR payloads, canonical receipts, audit data, and backups. Record the deletion and restoration verification owner.
- [ ] Select and document the upload malware-scanning service or explicitly approve a compensating control before accepting real files.
- [ ] Verify that the chosen production CSS asset is version-pinned, locally served, covered by the content-security policy, and available without a third-party CDN. The Tailwind CDN may be used only for local prototyping.

## MVP 1 Release Measures

The owner must approve values before MVP 1 production promotion. Measure them in the production-like environment using the release candidate and retain results in `tblTesting`.

| Measure | Required approval value | Acceptance evidence |
|---|---|---|
| Upload acknowledgement latency | p95 target for supported file sizes | Timed load test excluding OCR processing |
| OCR processing visibility | Maximum time to show queued/running/succeeded/failed state | Worker outage and normal-processing test |
| Failed-job recovery | Maximum recovery time and no-loss criterion | Broker/worker restart test with idempotency verification |
| Backup recovery | RPO <= 24 hours and RTO <= 8 hours | Timed restore of Postgres and protected receipt files |
| Security verification | Zero unresolved critical authentication/upload findings | Release security test report |

## MVP 2 Market-Day Measures

Before MVP 2 production, approve and test values for online sale acknowledgement, Square synchronization delay, queued-sale state visibility, outage recovery, browser/device recovery, and tender-closeout discrepancy handling. The documented decision must also state whether offline sale queueing is supported; if not, the UI must prevent offline sale submission and make that limitation explicit.

- [ ] Before connecting any live Square account or promoting `sales-mvp`, verify the granted Square credential permissions are read-only and restricted to required Catalog, Orders, Payments, and Location reads; broad/write-capable credentials fail activation. Run the Capability 3 adapter allowlist tests, including approved read-only POST searches and attempted create/update/delete/cancel/refund calls from sync, retries, and admin routes; prove forbidden calls are rejected locally with zero outbound provider requests. Record the credential scope review and test results with the release candidate.

## MVP 3 Costing & Opening-Balance Measures

Before MVP 3 production, approve and record the product/ingredient/supply unit catalog, conversion authority, quantity precision, and rounding policy. Global conversions apply only within one dimension (count, mass, or volume). Any count/mass/volume crossing, including produce sold by container such as a pint of strawberries, requires an owner-entered, effective-dated per-item conversion marked as an estimate (Capability 4.9, CO-001). Define the opening-count cutoff instant and treatment of late or backdated movements. The `costing-mvp` profile must prove that MVP 1 ingredient, recipe, receipt-item, expense, and asset links migrate replay-safely without loss or duplicate posting; opening counts plus subsequent movements must reconcile to a known physical count.

| Measure | Required approval value | Acceptance evidence |
|---|---|---|
| Unit conversion authority | Approved catalog and receipt aliases, same-dimension-only global rule, and per-item cross-dimension conversion policy | Versioned conversion registry, per-item conversion history, and CO-001 validation tests |
| Opening-count cutoff | Timestamp semantics and late-event/restatement rule | Seeded count-and-movement reconciliation |
| Historical migration | Approved source-to-target mapping for all MVP 1 thin records | Replay, rollback, and source-lineage test results |

## MVP 4 Prep & Messaging Measures

Before MVP 4 production, approve the lightweight stock-balance interface used by shopping and prep until Capability 6 is available. The shared production service must be active before confirmation can post any stock effect. Production WhatsApp activation additionally requires the approved WABA, consent/privacy treatment, spend threshold, webhook verification, and a controlled opted-in-recipient smoke test.

| Measure | Required approval value | Acceptance evidence |
|---|---|---|
| Balance authority | One read interface and movement sources for MVP 4 shopping/prep | No parallel balance calculation in integration tests |
| Prep atomicity | Shared production-event identity and correction policy | Retry, concurrency, rollback, and correction tests |
| Messaging activation | WABA/phone/display-name, consent, privacy, and spend approvals | Signed activation record and controlled production smoke test |

## MVP 5 Market & Expense Measures

Before MVP 5 production, approve the immutable market-visit identity and the expense provenance model. The `markets-mvp` profile must prove that MVP 2 dated visits migrate without duplication, route allocations reconcile exactly to each trip, and receipt/manual expense retries or corrections produce one net audited expense.

| Measure | Required approval value | Acceptance evidence |
|---|---|---|
| Visit migration | MVP 2-to-MVP 5 identity and duplicate-rejection policy | Replay migration preserving sales, prep, and session links |
| Route allocation | Directed-leg allocation and mileage-rate snapshot policy | Itinerary tests where allocations equal total trip cost |
| Expense posting | Source-event uniqueness and correction/reversal policy | Concurrent/replayed source posting tests |

## MVP 6 Inventory & Reorder Measures

Before MVP 6 production, approve the effective-dated calendar-period policy used for weekly close, expiry, reporting, and alerts. Product, ingredient, and supply balances must each have reproducible versioned period snapshots. A late event affecting a closed period must produce a linked restatement rather than silently rewrite history.

| Measure | Required approval value | Acceptance evidence |
|---|---|---|
| Period calendar | Effective timezone/week-start policy and close-completion rule | DST, non-default week-start, and period-boundary tests |
| Snapshot coverage | Product, ingredient, and supply snapshot grain and valuation policy | Ledger-to-snapshot reconciliation for all stock classes |
| Closed-period correction | Restatement, downstream rebuild, and alert re-arm rule | Late sale/refund/purchase/production correction tests |

## MVP 7 Analytics Measures

Before MVP 7 production, approve the ranking-score ownership and the forecast observation-completion rule. Dashboards may publish only coherent successful refresh runs with source watermarks, accepted restatement versions, and drill-through lineage. A failed or partial refresh must remain visibly stale and cannot publish mixed-state KPIs.

| Measure | Required approval value | Acceptance evidence |
|---|---|---|
| Metric contract | Ranking score source/scale/as-of behavior and forecast observation predicate | Boundary, missing-data, and restatement-selection tests |
| Refresh coherence | Required upstream runs, watermark lag, and stale/failed display policy | Successful, failed, and partial refresh publication tests |
| Regression traceability | Complete source-workbook mapping and approved expected results | Passing `analytics-mvp` result with all mapped behavioral cases |

## MVP 8 Tax & Full-System Measures

Before MVP 8 production, define and approve a tax-year provider-coverage certificate for every expected provider/account. The certificate must include covered business-date range, source statement or final import watermark, expected order/payment/refund counts and amounts, reconciliation outcome, gap/exception IDs, and owner/preparer approval. An absent, failed, or unresolved blocking certificate prevents package generation and production promotion.

The production deployment procedure must also prove write quiescence, worker drain, scheduler control, migration compatibility, in-flight workflow recovery, and failed-migration rollback. Production runs from an immutable Compose profile with pinned image digests, disabled reload/debug facilities, restricted public exposure, health checks, restart policies, and production-only secrets/configuration.

| Measure | Required approval value | Acceptance evidence |
|---|---|---|
| Tax coverage | Provider/account population, late-arrival cutoff, and blocking-exception policy | Signed tax-year coverage certificate and reconciliation report |
| Tax readiness | Supported-year mappings and tax-professional approval scope | Signed approval record and reproducible frozen package |
| Deployment recovery | Quiescence, backup/restore, migration, rollback, and in-flight-job recovery procedure | Timed restore and failed-migration drill on the promoted artifact |