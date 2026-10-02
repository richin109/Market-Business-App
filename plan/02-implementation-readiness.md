# Implementation Readiness Gate

Status: **conditional go for local MVP 1 development, including private-data tests**. Owner authorization for local private receipts is recorded below; live providers and production promotion remain subject to their separate gates.

## Requirements Baseline & Change Control

- [x] Record D-77 (2026-10-02): PostgreSQL sole runtime/dev/test DB for MVP 1–8; retain generic SQLAlchemy/Alembic/services. Migration impact: revision capacity and forward JSONB parity; tests: disposable PostgreSQL and required migrations. Evidence belongs in `03-current-slice.md`.
- [ ] Before production, pass PostgreSQL stage matrix, least-privilege review, coordinated DB/file backup and timed restore, restart drill, immutable candidate gate. Other SQLAlchemy backends require separate compatibility review.

- [ ] Record approving owner/date, repository commit, and SHA-256 for governing sources: `00-overview.md`, `01-mvp-roadmap.md`, MVP 1 capabilities, approved decisions/slices. Track Blueprint/workbook checksums as reference inputs only.
- [ ] Catalog each source's title, path, version/date, and authority status. Devin prompt is historical/reference-only; its stack is superseded by `00-overview.md`. Blueprint/workbooks are reference-only.
- [ ] Classify WDS and Devin DOCX/TXT as reference-only or superseded; record owner/rationale. They are not implementation authority.
- [ ] Resolve conflicts before work using precedence: approved decision → overview → roadmap → capability → reference artifacts. Workbooks/docs/formulas are not business rules.
- [ ] Before a requirement change, record rationale, approver, affected capability, migration impact, and regression-test impact.
- [ ] Obtain named-owner RM-022 production-policy approval. One order may span overlapping/supplementary PDFs, but owns one `Receipt_ID`; implement source/line provenance migration, copy/supplement review, synthetic/browser tests (Capabilities 1.2–1.4, 2.1/2.5). This is not real-data approval.
- [ ] Before production OCR, approve RM-023 authority for vendor refs, transaction vs print time, payment suffix, item number, package size, and weighed quantity. Preserve alternatives; ambiguity requires review. Private examples are not OCR ground truth or commit permission.
- [ ] Before production, approve RM-025 stable per-order identity, near-match resolution, changed bytes at one path, and holds for insufficient list images. Never infer identity from count/name or post unresolved snapshots. Synthetic 5/10/15 and private-directory tests may run locally under the authorization below; production ingestion stays gated.
- [x] Record the owner-approved store-identity policy (D-37) before implementing automatic store creation: alias normalization, review holds, display-name editing, merge/split and unchanged raw identity are recorded in [04-go-no-go.md §5](04-go-no-go.md). This approves the policy only; ST-001/ST-002 implementation and tests remain unchecked. A branch-number collision must hold for review rather than silently join distinct source locations.
- [x] Record the owner-approved purchased-item identity policy (D-38/D-39/D-40) before implementing item mapping: store product identifier, missing-ID hold, last-store-item constraint, common-name fallback, suggestion confirmation, and historical remap policy are recorded in [04-go-no-go.md §5](04-go-no-go.md). This approves the policy only; IT-001/IT-002 implementation and tests remain unchecked.
- [ ] If distinct branches collide under D-37 normalization, obtain approval for versioned location-aware identity/migration before auto-resolution. Until then hold imports/postings; prove with synthetic S14/ST-001 cases. Same-location alias grouping remains approved.
- [ ] Complete manifest traceability for every MVP 1 criterion/source intent: source location, fixture/expected result, applicability+rationale, test type/ID, command, profile. At 2026-10-02: 169 rows, 145 PLANNED/24 VERIFIED; 115 lack commands. Future IDs are not coverage without file, command, applicability, and result. Document out-of-scope cases; written plan overrides source documents.

## Real-Data Privacy & Provider Approval

- [ ] 🧑‍💻 Classify receipt/OCR/record/audit/backup data; name owner and permitted users.
- [x] **Owner-authorized 2026-10-02: local private-data development and tests, including RM-024.** The owner explicitly permits agents to use private receipt PDFs/images in this local workspace and local containers for development and testing. Keep inputs, extracted data, reviewed expectations, renderings, and identifiable outputs in gitignored or external locations; verify none are tracked before use. Run relevant tests when inputs are available rather than skipping because they are private. No private files or contents may be committed or pushed to GitLab/another remote, included in CI or published images, or uploaded to external providers. Shared evidence contains redacted aggregates only. This authorization does not approve production promotion, external transfers, or a retention/deletion policy.
- [ ] 🧑‍💻 Approve OCR accuracy/review thresholds and failure recovery before MVP 1 production.
- [x] **Owner-authorized 2026-10-02: private information in local development logs.** Local application/container console logs, test diagnostics, OCR output, filenames, extracted fields, and identifiable mismatch reports may contain private receipt information for debugging. Store persistent logs/reports in gitignored locations such as `.local/`, `receipts/`, or `data/receipts/`, or outside the repository; verify none are tracked. Keep console/log access local to authorized users and disable external log forwarding. Never commit/push these logs to GitLab or another remote, include them in CI/published images, or paste/upload their private contents into chat or external services. Shared plan/release evidence remains redacted aggregates only. This permission does not authorize logging credentials, secrets, or tokens, or change production logging/retention rules.
- Reading ignored `receipts/` for fixture design and running local OCR/accuracy tests are authorized above. Private outputs stay gitignored or external; committed fixtures must reproduce only layout and edge cases with invented values. Local exploratory runs may use inputs without reviewed expectations or checksum sidecars: report missing/stale ground truth locally and do not claim measured accuracy for those cases. Human-reviewed, checksum-matched expectations and approved accuracy thresholds are required for RM-024 acceptance/release claims, not permission to investigate locally.
- **Local versus shared evidence:** Detailed logs, screenshots, extracted JSON, per-file results, and diagnostic reports kept locally in gitignored/external locations do not require redaction. Redact private information before copying evidence into tracked plans, commits, shared reports/artifacts, CI, chat, or external services; shared release summaries use anonymous counts/aggregates. No separate operator, production retention/backup, scanner-certification, or accuracy-threshold approval is required merely to run authorized local private-data tests. Keep runtime security, role checks, and unresolved business-data holds intact; this permission does not bypass them or authorize live-provider use.
- Future Google Document AI separately needs region, transfer terms, spend/budget alerts, and uncertain-submission approvals (Capability 1); it is not MVP 1.
- [ ] 🧑‍💻 Approve retention/legal holds for source, OCR, canonical, audit, backup data; name deletion/restore verifier.
- [ ] Before MVP 1 PDF promotion, validate approved fail-closed scanning in candidate: clean, malicious, unavailable, retry. Block production real-PDF ingestion until then; isolated local private-PDF development/tests are authorized above without changing runtime scanner behavior. Synthetic PDFs may mock scanning. D-09's JPEG/PNG exception does not waive production data/retention/backup/release gates.
- [ ] Verify production CSS is version-pinned, locally served, CSP-covered, and CDN-free; Tailwind CDN is prototype-only.

## MVP 1 Release Measures

The owner must approve values before MVP 1 production promotion. Measure them in the production-like environment using the release candidate and retain results in `tblTesting`.

| Measure | Required approval value | Acceptance evidence |
|---|---|---|
| Upload acknowledgement | Confirm receipt within 3 seconds for at least 95 of 100 supported files up to 10 MB; this excludes OCR completion | Timed upload test excluding OCR processing |
| OCR status visibility | Show queued/running/complete/review/failed status within 10 seconds; completion may take longer | Worker outage and normal-processing test |
| Failed-job recovery | Recover within 15 minutes after service recovery with no lost file and no duplicate receipt/business record | Broker/worker restart test with idempotency verification |
| Backup recovery | RPO <= 24 hours and RTO <= 8 hours | Timed restore of Postgres and protected receipt files |
| Security verification | Zero unresolved critical authentication/upload findings | Release security test report |

## MVP 2 Costing & Catalog Measures

Before MVP 2 production, approve and record the product/ingredient/supply unit catalog, package composition, conversion authority, quantity precision, and rounding policy. Global conversions apply only within one dimension (count, mass, or volume). Any count/mass/volume crossing requires an owner-entered effective-dated per-item conversion/expected piece count marked as an estimate (D-50, CO-001). Define expected-inventory dates and late/backdated purchase holds; no physical counts. The `costing-mvp` profile must prove MVP 1 ingredient, recipe, receipt-item, expense, and asset links migrate without loss or duplicate posting, and that approved receipt purchases, not market targets, drive the currently active expected-inventory sources (D-53/D-74). Made events begin in MVP 3; closed-period restatement and FEFO consumption/valuation remain MVP 6. Under D-63 no sale is accepted and no provisional product cost exists in this MVP.

- [ ] If one canonical purchased item must feed multiple active Direct Sell variations, obtain owner approval for the allocation identity, conserved per-variation quantities, correction/replay behavior, and migration before enabling that mapping. Until then slice 2.2a holds the conflicting mapping and posts no stock; DS-001 proves the hold. This conditional decision does not block the unambiguous one-item/one-variation path.

- [ ] Before connecting any live Square account, verify the granted Square credential permissions are read-only and restricted to required Catalog, Orders, Payments, and Location reads; broad/write-capable credentials fail activation. U-4 remains optional for now; mocks and recorded fixtures are sufficient for planning and unit tests. If U-4 is used for a sandbox smoke/profile test, run the Capability 3 adapter allowlist tests, including approved read-only POST searches and attempted create/update/delete/cancel/refund calls from sync, retries, and admin routes; prove forbidden calls are rejected locally with zero outbound provider requests. Record the credential scope review and test results with the release candidate.

| Measure | Required approval value | Acceptance evidence |
|---|---|---|
| Unit conversion authority | Approved catalog and receipt aliases, same-dimension-only global rule, and per-item cross-dimension conversion policy | Versioned conversion registry, per-item conversion history, and CO-001 validation tests |
| Shelf-life capture | Required per-item duration/`never`, remembered-default reuse, recipe output shelf life, and legacy `is_perishable` migration mapping | Item-creation blocking tests, remembered-default reuse tests, and recipe-override tests (SL-001, SL-002) |
| Expected-inventory dates | Reviewed receipt purchase/acquisition instant, unknown-date hold, target excluded, future source types labelled inactive | Approved receipt lot and differing plan target through the single reader; unknown-time hold and source-coverage test (`tests/test_stock_balance.py::test_as_of_expiry`) |
| Date-effective costing (D-57) | Receipt-backed as-of-date input costs, carried-forward labelling, and typed blocking when no earlier cost exists; retain dated provenance for later restatement | CS-001 receipt-to-cost-history entry-point test and BL-001; CS-002 closed-period restatement and CS-003 FEFO lot valuation gate `inventory-mvp`, not `costing-mvp` |
| Balance authority (D-59) | One `StockBalanceReader` is the only balance path in the application; no interim or session-specific reader exists | No second balance calculation anywhere in integration tests |
| Historical migration | Approved source-to-target mapping for all MVP 1 thin records | Replay, rollback, and source-lineage test results |

## MVP 3 Sales & Market-Day Measures

Before MVP 3 production, test Square as the source of record for every actual sale, the first Square sync 30 minutes after market end, the 24-hour repeat sync while late/unresolved data remains, manual `Sync Now`, provider-state visibility, browser/device recovery, and settlement exception handling. No MBS sale-response SLA or cash-counting target applies. The documented decision must also state whether offline sale queueing is supported; if not, the UI must prevent offline sale submission and make that limitation explicit. Promoting `sales-mvp` requires the MVP 2 read-only credential review above to have passed.

| Measure | Required approval value | Acceptance evidence |
|---|---|---|
| Cost on accepted lines (D-63) | Every accepted Square line resolves an MVP 2 recipe-derived or direct-item effective cost; no provisional estimate is accepted | Acceptance tests rejecting a line whose product has no effective cost for the sale date |
| Production consumption (D-63) | A confirmed made quantity posts finished units and consumes its effective recipe's inputs in one transaction | Atomic production tests showing ingredient and supply movements alongside finished stock |
| Attribution and late data | D-16/D-19 provider attribution, late acceptance, and permanent `Order ID + Line Item UID` deduplication | Late-order, duplicate-identity, refund, and cursor-replay tests |

## MVP 4 Prep & Messaging Measures

Before MVP 4 production, confirm that shopping and prep read balances only through the MVP 2 `StockBalanceReader` (D-59) and that the MVP 3 production service is active before any confirmation can post a stock effect. Production WhatsApp activation additionally requires the approved WABA, consent/privacy treatment, spend threshold, webhook verification, and a controlled opted-in-recipient smoke test.

| Measure | Required approval value | Acceptance evidence |
|---|---|---|
| Balance authority | Shopping and prep use the single MVP 2 reader; no new balance path is introduced | No parallel balance calculation in integration tests |
| Prep atomicity | Shared production-event identity, persisted waste remainder, and correction policy | Retry, concurrency, rollback, and correction tests (PC-001) |
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