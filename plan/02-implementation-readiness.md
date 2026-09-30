# Implementation Readiness Gate

Status: **conditional go for local MVP 1 foundations only**. Do not ingest real receipts, enable live providers, or promote a release until every applicable item below is complete and approved by the business owner.

## Requirements Baseline & Change Control

- [ ] Record the approving owner, approval date, repository commit, and SHA-256 checksum for each governing source: `plan/00-overview.md`, `plan/01-mvp-roadmap.md`, all MVP 1 capability files, `plan/Python MBS v3.3 + Receipt OCR Blueprint.docx`, `support/Market_Business_System_v3_3_Testing_Dashboard.xlsx`, and `support/Walmart_Receipt_Complete_With_AI.xlsx`.
- [ ] Record each source artifact's title, path, version/date when available, and status (governing, reference-only, or superseded). The Devin MBS prompt is historical/reference-only for business requirements; its Java/Spring/React/Kubernetes stack is superseded by `plan/00-overview.md`.
- [ ] Classify `support/WDS_v2_1_Reconstruction_Grade_Specification 1.docx` and `support/Devin_MBS_v3_3_Prompt.docx` / `.txt` as reference-only or superseded, and record the approving owner and rationale; they are not independent authority for implementation choices.
- [ ] Resolve conflicting requirements before implementation. Precedence is: approved signed readiness decision, then `00-overview.md`, then `01-mvp-roadmap.md`, then capability files, then source documents/workbooks. A lower-precedence source must not silently override a higher-precedence requirement.
- [ ] Log a requirement change with its rationale, approving owner, affected capability, migration impact, and regression-test impact before implementing it.
- [ ] Complete `plan/test-case-manifest.csv`, mapping every MVP 1 acceptance criterion and each of the 110 source-workbook cases to source artifact/tab/cell or scenario, fixture, expected result, structural/behavioral test type, automated test ID, validation command, and release profile. An empty or partially mapped manifest does not satisfy this gate.

## Real-Data Privacy & Provider Approval

- [ ] 🧑‍💻 Approve a data classification for receipt scans, OCR payloads, receipt records, audit data, and backups; record the data owner and permitted users.
- [ ] 🧑‍💻 Approve Google Document AI processor region, data-transfer terms, monthly spend limit, budget alerts, and the process for an OCR provider outage or uncertain submission.
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