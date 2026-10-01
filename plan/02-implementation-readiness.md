# Implementation Readiness Gate

Status: **conditional go for local MVP 1 foundations only**. Do not ingest real receipts, enable live providers, or promote a release until every applicable item below is complete and approved by the business owner.

## Requirements Baseline & Change Control

- [ ] Record the approving owner, approval date, repository commit, and SHA-256 checksum for each governing plan source: `plan/00-overview.md`, `plan/01-mvp-roadmap.md`, all MVP 1 capability files, and the applicable approved decision/slice files. Record the Blueprint DOCX and support workbooks separately as reference materials; their checksums document the inputs used, not authority over the plan.
- [ ] Record each source artifact's title, path, version/date when available, and status (plan authority, reference-only, or superseded). The Devin MBS prompt is historical/reference-only for business requirements; its Java/Spring/React/Kubernetes stack is superseded by `plan/00-overview.md`. The Blueprint DOCX and Excel workbooks are reference-only.
- [ ] Classify `support/WDS_v2_1_Reconstruction_Grade_Specification 1.docx` and `support/Devin_MBS_v3_3_Prompt.docx` / `.txt` as reference-only or superseded, and record the approving owner and rationale; they are not independent authority for implementation choices.
- [ ] Resolve conflicting requirements before implementation. Precedence is: approved owner decision, then `00-overview.md`, then `01-mvp-roadmap.md`, then capability files, then source documents/workbooks as reference guides. Workbooks, Word documents, and their formulas are evidence and examples, not business rules; a lower-precedence source must not silently override a higher-precedence requirement.
- [ ] Log a requirement change with its rationale, approving owner, affected capability, migration impact, and regression-test impact before implementing it.
- [ ] Obtain named owner approval for RM-022's split-order source policy before production implementation. Rationale: one order may have multiple overlapping PDFs and a distinct repeated-product line in a supplementary PDF; one `Receipt_ID` still owns one canonical receipt. Affects Capabilities 1.2-1.4 and 2.1/2.5, requires a reviewed multi-source association/line-provenance migration and copy-versus-supplement review flow, and adds synthetic RM-022 regression and browser tests. This plan proposal is not evidence of privacy approval to ingest real receipt files.
- [ ] Record the owner-approved RM-023 field-authority rules before production OCR: which vendor reference (for example order # versus printed REF or register/TR#) is canonical, how to select transaction versus print/footer time, and how visibly printed payment suffixes, merchant item numbers, package sizes, and weighed quantities differ from reviewer-provided knowledge. Preserve raw alternatives and require manual review for ambiguity; a private receipt example is evidence for design, not permission to commit it or to turn an inferred value into OCR ground truth.
- [ ] Approve RM-025's multi-order segmentation and growing-source policy before production: the required stable identity for each order inside a PDF/image, authorized resolution of near matches, handling of changed bytes at one display path, and hold behavior for list images lacking enough header/totals to establish independent receipts. Do not infer identities from order count or filename, and do not auto-post lines from an unresolved snapshot. Synthetic five-to-ten-to-fifteen tests may run locally before approval, but real-directory ingestion remains blocked by the real-data gate.
- [ ] Record the owner-approved store-identity policy (D-37) before implementing automatic store creation: the normalization used to match a printed/provider store value to an existing alias, what is held for review instead of auto-created, who may rename or group stores, and the audited merge/split behavior for aliases, receipts, and posted records. Display names and groupings must not re-key history.
- [ ] Record the owner-approved purchased-item identity policy (D-38/D-39) before implementing item mapping: the store product identifier used per source, handling for a line printed without one, the rule that many store items map to exactly one canonical item and each canonical item retains at least one, the common-name defaulting rule, and the confirmation requirement for description-based suggestions. Remapping after posting requires an audited restatement, never a silent rewrite.
- [ ] Complete `plan/test-case-manifest.csv`, mapping every MVP 1 acceptance criterion and each source-workbook test intent to source artifact/tab/cell or scenario, concrete application fixture and expected result, applicability classification (`APPLICABLE`, `TRANSFORMED`, or `NOT_APPLICABLE`) with rationale, test type, implemented automated test ID where applicable, runnable validation command, and release profile. It currently contains 162 rows: 156 `PLANNED` and 6 `VERIFIED`; 119 rows still lack validation commands. Planned rows may retain proposed future test IDs, but they do not count as coverage until the referenced file, command, applicability decision, and result exist. This does not satisfy the gate. The workbook and Word document are guides; the written plan wins, and nonsensical/out-of-scope cases must be documented rather than forced into code.

## Real-Data Privacy & Provider Approval

- [ ] 🧑‍💻 Approve a data classification for receipt scans, OCR payloads, receipt records, audit data, and backups; record the data owner and permitted users.
- [ ] 🧑‍💻 Separately authorize any RM-024 local evaluation using the real files under `receipts/`: approve the operator, isolated machine/store, permitted purpose, access controls, retention and deletion of originals/expected results/temporary renderings, and redacted aggregate evidence. Verify the source files and reviewed expectations are untracked/ignored or stored outside the repository; fail closed if any is tracked, missing, unreviewed, mismatched by checksum, or would be logged/uploaded to CI or an external OCR service. Real files are not approved test fixtures solely because they are present in the workspace.
- [ ] 🧑‍💻 Approve local OCR accuracy/review thresholds and recovery from failed processing before MVP 1 production.
- Reading the local `receipts/` files as a **design reference** when authoring synthetic fixtures is permitted local work by a permitted D-15 user and does not require the separate RM-024 evaluation approval, because it produces no measurement, no retained output, and no evidence claim. The boundary is absolute: real layouts and formats may inform invented fixtures, while real values, filenames, images, and reviewed expected results never leave the untracked directory — not into the repository, tests, CI, logs, screenshots, exports, or chat. Running the corpus through OCR to measure accuracy remains RM-024 and stays gated.
- Future optional Google Document AI activation separately requires approval of processor region, data-transfer terms, monthly spend limit, budget alerts, and uncertain-submission policy; see Capability 1's future enhancement. This is not part of the MVP 1 gate.
- [ ] 🧑‍💻 Approve retention periods and legal/operational hold rules for source files, raw OCR payloads, canonical receipts, audit data, and backups. Record the deletion and restoration verification owner.
- [ ] Before real PDF/source-file imports, select and validate an approved fail-closed malware-scanning service; keep those imports blocked until it works. D-09 already approves validated JPEG/PNG imports without a scanner; that exception does not waive the separate real-data classification, retention, backup, and release gates.
- [ ] Verify that the chosen production CSS asset is version-pinned, locally served, covered by the content-security policy, and available without a third-party CDN. The Tailwind CDN may be used only for local prototyping.

## MVP 1 Release Measures

The owner must approve values before MVP 1 production promotion. Measure them in the production-like environment using the release candidate and retain results in `tblTesting`.

| Measure | Required approval value | Acceptance evidence |
|---|---|---|
| Upload acknowledgement | Confirm receipt within 3 seconds for at least 95 of 100 supported files up to 10 MB; this excludes OCR completion | Timed upload test excluding OCR processing |
| OCR status visibility | Show queued/running/complete/review/failed status within 10 seconds; completion may take longer | Worker outage and normal-processing test |
| Failed-job recovery | Recover within 15 minutes after service recovery with no lost file and no duplicate receipt/business record | Broker/worker restart test with idempotency verification |
| Backup recovery | RPO <= 24 hours and RTO <= 8 hours | Timed restore of Postgres and protected receipt files |
| Security verification | Zero unresolved critical authentication/upload findings | Release security test report |

## MVP 2 Market-Day Measures

Before MVP 2 production, test Square as the source of record for every actual sale, the first Square sync 30 minutes after market end, the 24-hour repeat sync while late/unresolved data remains, manual `Sync Now`, provider-state visibility, browser/device recovery, and settlement exception handling. No MBS sale-response SLA or cash-counting target applies. The documented decision must also state whether offline sale queueing is supported; if not, the UI must prevent offline sale submission and make that limitation explicit.

- [ ] Before connecting any live Square account or promoting `sales-mvp`, verify the granted Square credential permissions are read-only and restricted to required Catalog, Orders, Payments, and Location reads; broad/write-capable credentials fail activation. U-4 remains optional for now; mocks and recorded fixtures are sufficient for planning and unit tests. If U-4 is used for a sandbox smoke/profile test, run the Capability 3 adapter allowlist tests, including approved read-only POST searches and attempted create/update/delete/cancel/refund calls from sync, retries, and admin routes; prove forbidden calls are rejected locally with zero outbound provider requests. Record the credential scope review and test results with the release candidate.

## MVP 3 Costing & Opening-Balance Measures

Before MVP 3 production, approve and record the product/ingredient/supply unit catalog, package composition, conversion authority, quantity precision, and rounding policy. Global conversions apply only within one dimension (count, mass, or volume). Any count/mass/volume crossing requires an owner-entered effective-dated per-item conversion/expected piece count marked as an estimate (D-50, CO-001). Define expected-inventory dates and late/backdated movements; no physical counts. The `costing-mvp` profile must prove MVP 1 ingredient, recipe, receipt-item, expense, and asset links migrate without loss or duplicate posting; approved receipt purchases and confirmed made events, not market targets, must reconcile through Square sales to expected inventory (D-53).

| Measure | Required approval value | Acceptance evidence |
|---|---|---|
| Unit conversion authority | Approved catalog and receipt aliases, same-dimension-only global rule, and per-item cross-dimension conversion policy | Versioned conversion registry, per-item conversion history, and CO-001 validation tests |
| Shelf-life capture | Required per-item duration/`never`, remembered-default reuse, recipe output shelf life, and legacy `is_perishable` migration mapping | Item-creation blocking tests, remembered-default reuse tests, and recipe-override tests |
| Expected-inventory dates | Approved receipt purchase and recorded made-event dates; late-event/restatement rule; target excluded | Seeded receipt/production/Square movement reconciliation with a differing shopping target |
| Date-effective costing (D-57) | As-of-date cost resolution for all financial output, carried-forward labelling, blocking when no earlier cost exists, receipt-dated late/backdated rows with open-period recompute and closed-period restatement, and FIFO lot-cost valuation with no revaluation of existing stock | CS-001–CS-003 fruit-cup two-week costing, backdated-receipt restatement, and 10c/12c cup lot tests |
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

Before MVP 6 production, approve the effective-dated calendar-period policy used for weekly close, expiry, reporting, and alerts, plus the shelf-life expiry policy: per-lot `Perishable By` from acquisition instant plus item shelf life, recipe output shelf life from the production timestamp, an expiry job that runs at startup and on an interval, and carry-forward of unexpired and `never` stock. Product, ingredient, and supply balances must each have reproducible versioned period snapshots. A late event affecting a closed period must produce a linked restatement rather than silently rewrite history.

| Measure | Required approval value | Acceptance evidence |
|---|---|---|
| Period calendar | D-33 Monday 00:00 start and Monday 03:00 close in the effective business timezone; non-Monday changes deferred pending approval | DST, Monday close/retry, non-Monday-setting rejection, and period-boundary tests |
| Expiry job | Startup plus `expiry_scan_interval_minutes` cadence and per-lot idempotency key | Restart, retry, overlapping-run, and stopped-system catch-up tests with exactly one waste movement per lot |
| Shelf-life change policy | Recompute open lots from acquisition; posted waste and closed periods change only by restatement | Shelf-life edit tests across open lots, posted waste, and a closed period |
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