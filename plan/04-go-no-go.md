# MVP Go / No-Go Assessment (Vibe-Coding Readiness)

Assessment date: 2026-09-30. Reviewer role: senior QA, AI-agent ("vibe") delivery.
Scope: MVP 1–8 in [01-mvp-roadmap.md](01-mvp-roadmap.md), judged against [00-overview.md](00-overview.md), [02-implementation-readiness.md](02-implementation-readiness.md), [03-current-slice.md](03-current-slice.md), all 16 capability files, [test-case-manifest.csv](test-case-manifest.csv), the blueprint DOCX, and every file in `support/`.

This document does not override the precedence in the readiness gate. Every "recommended default" below is a **proposal**; it becomes binding only when the owner approves it in §5 and the governing capability/roadmap text is reconciled. Approval does not certify unimplemented tests, expand an outline into a runnable slice, or waive a production gate.

Independent of the optional defaults below, Square API access has a mandatory no-write gate in Capability 3 and the MVP 2 readiness profile. MBS never attempts a provider-side mutation, even with owner approval of a session workflow. SQ-001 must pass and credential read scopes must be verified before live Square activation.

Two definitions:
- **Build GO**: an agent can implement and test the MVP locally with synthetic data and mocked providers, without stopping for a decision.
- **Prod GO**: the MVP can be promoted with real data and live providers.

## 1. Verdict Summary

| MVP | Build verdict (today) | Build verdict after §5 approval | Prod verdict | Blocking items |
|---|---|---|---|---|
| Foundation slice | **GO** | GO | n/a | None. Docker Desktop 29.8.1 + Compose v5.5.1 installed and verified 2026-09-30 (U-1 done) |
| 1 Receipts | CONDITIONAL | **GO** | NO-GO | D-00, D-06–D-15; user actions U-2, U-3 |
| 2 Square + Sales + Market-Day | **NO-GO** | CONDITIONAL (expand/test slices) | NO-GO | D-01–D-05, D-12, D-16–D-19; U-4 |
| 3 Products/Recipes/Costing | CONDITIONAL | GO | NO-GO | D-20, D-26–D-31 |
| 4 Shopping + WhatsApp | CONDITIONAL | CONDITIONAL (balance contract tests; Meta calls mocked) | NO-GO | D-17, D-32; U-5 |
| 5 Markets & Weekly Ops | CONDITIONAL | GO | NO-GO | D-18, D-22 |
| 6 Inventory & Reorder | CONDITIONAL | GO | NO-GO | D-20, D-21, D-33 |
| 7 Dashboards/Rankings/Forecast | **NO-GO** | CONDITIONAL (translate and implement cases) | NO-GO | D-23–D-25, D-27, D-34; 61 structural/tautological cases need application equivalents |
| 8 Tax + Full Release | **NO-GO** | CONDITIONAL (draft workpapers only) | **NO-GO by design** | Needs signed tax-professional approval and a coverage certificate (U-7). The agent cannot close this gate. |

Bottom line: local receipt work may continue with mocks; the Docker Compose foundation is installed and validated (U-1 done 2026-09-30). Owner approval of §5 removes decision blockers, not missing slice specifications, executable tests, or production evidence. MVP 8 production always needs a human tax professional.

## 2. Evidence Reviewed

| Artifact | Finding |
|---|---|
| `plan/*.md`, 16 capability files | Detailed and mostly internally consistent. Plan precedence resolves most source conflicts. |
| `plan/test-case-manifest.csv` | Had a header only (0 rows). Now contains 110 workbook cases + 18 MVP 1 criteria + SQ-001, all `PLANNED`. It records no coverage. |
| `Market_Business_System_v3_3_Testing_Dashboard.xlsx` (42 sheets) | Contains the fixtures and 110 regression cases. 46 are behavioral, 46 are formula-existence checks (`ISFORMULA`/`FORMULATEXT`), 14 are row-count/meta checks, 3 check configuration, and 1 is a tautology (RT041 is always 0). |
| `Walmart_Receipt_Complete_With_AI.xlsx` | Three receipts and 32 lines. Line totals reconcile exactly to the subtotals (55.82, 29.50, 29.81). Good golden OCR fixture. |
| Blueprint DOCX | Formulas and schemas are useful. It has stale stack choices (React, K8s, CSV import) that the plan supersedes. |
| `WDS_v2_1_Reconstruction_Grade_Specification 1.docx` | **No usable content.** It has 373 lines, and 275 of them repeat three boilerplate sentences. Classify it as superseded (D-34). |
| `Devin_MBS_v3_3_Prompt.*` | Historical Java stack. Already marked superseded. |

## 3. Cross-Cutting Findings

| # | Severity | Finding | Resolution |
|---|---|---|---|
| F1 | ~~Blocker~~ Resolved 2026-09-30 | Docker Desktop was not installed; the current slice needs `docker compose`. Now installed (Docker Desktop 29.8.1, Compose v5.5.1, WSL 2 + Ubuntu 26.04 LTS) and the Compose stack passes its acceptance checks. | U-1 done |
| F2 | Blocker (vibe) | [03-current-slice.md](03-current-slice.md) defines only the foundation slice and forbids the agent from choosing the next one. The agent stops after every slice. | Approve the slice queue in §7 and the auto-advance rule (D-00) |
| F3 | Blocker (MVP 7) | 61 workbook cases are structural/meta/tautological, and three additional cases are configuration checks. "All 110 pass" has no executable meaning in Python yet. | D-23 translation rules and executable manifest evidence |
| F4 | High | Workbook fixtures conflict with each other. RT043 values TEST-VAR002 at cost 3.80, but RT056 requires VAR002 to have no cost. The `Sales_Data` Square Fee fixture is 4.50, but the formula gives 150 × 0.026 + 0.10 = 4.00. | D-26 |
| F5 | High | Time-dependent cases (REVIEW COST, Market Active) use `TODAY()`, so they are non-deterministic. | D-27 fixed as-of date |
| F6 | High | Workbook, blueprint, and plan use different vocabulary: Shelf Stable/Spoils If Unsold vs `is_perishable`, "Inventory Variance" vs count variance, round-trip miles vs directed legs, attendance statuses, health-status labels. | D-18, D-20–D-22, D-25 |
| F7 | Medium | Numeric limits are left unspecified: upload size, pHash threshold, rate limits, session lifetime, sync interval, market-day targets. | D-05–D-08, D-13, D-14 |
| F8 | Medium | Some pieces are undefined: a HELPER role (Capability 16), password reset without an email provider, market ranking Business/Personal Score sources, and health-score "open issue" counting. | D-11, D-12, D-24, D-25 |
| F9 | Low | Capability 16 features use plain `-` bullets, not `- [ ]` checkboxes, so progress can't be tracked like other capabilities. | Convert when that capability becomes active |
| F10 | Low | Capability 9.2 lists Governance Rules 1–5, 7, and 8. Rule 6 (Release Gate) lives only in Capability 10.3. | Informational; no change needed |
| F11 | Info | The blueprint `Receipt_ID` example uses `MM/DD/YYYY`, but the plan's date policy requires ISO dates. | D-10 |

## 4. Per-MVP Assessment

### MVP 1 — Receipts
- **Ready:** requirements, data model, duplicate logic, dispositions, and test profile. Golden fixture data exists for mocked local OCR; production-like local accuracy still needs validation.
- **Gaps:** no numeric limits (D-06–D-08), no malware scanner choice (D-09), `Receipt_ID` canonical format (D-10), password reset path (D-11), release measure values (D-06).
- **Agent can do without user:** everything through the `receipt-mvp` profile with the mocked OCR engine.
- **Prod needs:** local OCR accuracy/review approval, U-3 (data classification, retention, backup destination), and a timed restore. U-2 applies only to the future Google enhancement.

### MVP 2 — Square, Sales Ledger, Market-Day POS
- **Blocked by three owner decisions already listed in 03-current-slice.md** (timezone authority, session price/availability, sale/close state table), plus the offline-mode decision and the quantitative targets.
- **Also undefined:** HELPER role (D-12), attendance vocabulary (D-18), and market Import Status derivation for API sync (D-19). The workbook's RT077–RT079 depend on D-19.
- **Agent can do after approval:** all of it against a Square sandbox or recorded fixtures. Payments, Orders, and Catalog are mockable.

### MVP 3 — Products, Recipes, Costing
- The readiness gate requires owner approval of the unit catalog, precision/rounding, and opening-count cutoff. The recommended defaults are D-28–D-31.
- The product status rule and product→recipe cardinality are implied by workbook fixtures but not written in the plan (D-28, D-29).

### MVP 4 — Shopping & WhatsApp
- Build is GO with Meta test resources or mocks. Production needs a WABA, a display name, consent wording, and a spend threshold (U-5).
- The lightweight stock-balance interface must exist from MVP 3. D-32 defines it.

### MVP 5 — Markets & Weekly Ops
- Well specified. Needs the attendance enum (D-18) and a rule for mapping the workbook's round-trip-miles fixtures to directed legs (D-22).

### MVP 6 — Inventory & Reorder
- The reorder formula is correctly locked to the workbook: RT048 gives ROUNDUP(1.5 × 7 + 5) = 16.
- Needs the perishability mapping (D-20), a rename for "Inventory Variance" (D-21), and the period calendar (D-33).

### MVP 7 — Analytics
- NO-GO until D-23 (structural-case translation), D-24 (ranking score inputs), D-25 (health score issue definitions), D-26 (fixture conflicts), and D-27 (as-of date) are approved.
- After approval, translate the 61 structural/meta/tautological cases into application assertions and implement the suite; approval alone does not make the 110 cases executable.

### MVP 8 — Tax & Full Release
- An agent can build draft Schedule C-aligned and Florida workpaper generators after the owner supplies tax-year mappings.
- Production promotion needs a signed tax-professional approval record and a provider coverage certificate. **This is a permanent human gate, not a plan defect.**

## 5. Owner Decision Sheet (approve in one pass)

Mark each row `Approved`, or write an override. One signature at the bottom approves every row not overridden. Rows marked 💲/🔒 touch money, tax, or security; review them individually.

| ID | Decision | Recommended default | Blocks |
|---|---|---|---|
| D-00 | Agent autonomy | Advance only to a prewritten, approved, unblocked current slice with acceptance criteria, manifest IDs or focused tests, validation commands, and recorded passing evidence. Never auto-expand an MVP outline, approve a decision, or promote production; stop at missing evidence, a failing gate, or a user-only action. | All |
| D-01 | Timezone authority | One `business_timezone = America/New_York` governs all MVP 2 market operating hours and business dates; no per-market timezone setting is active. Resolve overnight visits with an explicit visit business-date rule; reject nonexistent local times and disambiguate repeated DST times using the source UTC instant. Cross-timezone markets require a later approved migration. | MVP 2 |
| D-02 💲 | Session price & availability | The customer price is the Square Catalog price. Session overrides apply to manual tenders only. Enter a per-session load at open, but validate transfers and concurrent sessions against one source-stock allocation contract (D-17). Reserve on draft, commit on accepted sale, release on void/cancel; refunds do not restock without an audited physical-return event. Record unsold/damaged/donated dispositions at close. | MVP 2 |
| D-03 | Sale/close state table | Square line: `PROVIDER_PENDING → STAGED → ACCEPTED \| IMPORT_EXCEPTION`, with exception retry to `ACCEPTED`; manual line: `DRAFT → ACCEPTED` with corrections as linked reversal/replacement events. Session: `OPEN ⇄ PAUSED → CLOSE_EXCEPTION \| OPERATIONALLY_CLOSED`; approved/resolved close exceptions may transition to `OPERATIONALLY_CLOSED`, then to `SETTLEMENT_RECONCILED` only after payout/import reconciliation. No separate `CLOSED` state. Only accepted lines affect sales/inventory/tax; pending provider totals remain separately labelled at close. Reopening requires an audited MANAGER action. | MVP 2 |
| D-04 | Offline mode | The MBS browser does not queue or submit sales offline in MVP 2; disable its sale form and show a connectivity warning. A separate Square POS may still accept transactions under Square's own operating rules; these enter MBS only through an identified staged Order under D-16, never as a local offline sale. | MVP 2 |
| D-05 | MVP 2 targets | Online sale acknowledgement p95 ≤ 2 s. Square sync polls every 5 min, with delay ≤ 15 min. Pending state visible ≤ 10 s. Outage recovery ≤ 30 min. Browser refresh loses no completed sale. Cash over/short review threshold is $5.00 💲. | MVP 2 |
| D-06 | MVP 1 measures | Upload acknowledgement p95 ≤ 3 s for files ≤ 10 MB. OCR state visible ≤ 10 s. Failed-job recovery ≤ 15 min with zero loss. RPO ≤ 24 h, RTO ≤ 8 h. Zero critical findings. | MVP 1 |
| D-07 🔒 | Upload limits | JPEG, PNG, and PDF only. ≤ 20 MB, ≤ 10 PDF pages, ≤ 10,000 px on each side. 30 uploads per hour per user. | MVP 1 |
| D-08 | Near-duplicate threshold | 64-bit pHash per page. Hamming distance ≤ 6 marks the upload `POSSIBLE_DUPLICATE`. | MVP 1 |
| D-09 🔒 | Malware scanning | Add a ClamAV (`clamd`) container to Compose. Fail closed: if the scanner is unavailable, the file waits in `SCAN_PENDING`. CI uses a mocked scanner. | MVP 1 |
| D-10 | `Receipt_ID` format | `normalized_store\|YYYY-MM-DD\|HH:MM:SS\|TC# digits with spaces removed`. The TC# is shown to users as printed. | MVP 1 |
| D-11 🔒 | Password reset | No email provider in MVP 1. An ADMIN starts the reset, which issues a one-time token shown once. A local CLI recovery command covers the last admin. | MVP 1 |
| D-12 🔒 | Roles | ADMIN, MANAGER, VIEWER, plus HELPER in MVP 2. HELPER can only open/sell/close market-day sessions for the assigned visit. | MVP 1/2 |
| D-13 🔒 | Login throttling | 5 failures per minute per IP. The account locks for 15 min after 10 consecutive failures. | MVP 1 |
| D-14 🔒 | Sessions | 2 h idle timeout, 12 h absolute. Bearer JWT API stays disabled until a machine client needs it. | MVP 1 |
| D-15 🔒 | Data classification | Receipts, OCR payloads, audit data, and backups are *Confidential – internal*. Data owner: business owner. Permitted users: named ADMIN/MANAGER accounts. No automatic purge until retention periods are set (current plan default). | MVP 1 prod |
| D-16 | Square capture/correlation | Square POS is the only Square payment capture surface in MVP 2; MBS must not present a Square checkout button or claim it initiated a Square payment. Import Orders/Payments by provider IDs and correlate to a market session using an explicit Square session reference if available; otherwise require an authorized match against Location ID, full local business date, visit, and operating hours. Ambiguous or unmatched Orders remain visible exceptions, not invented pending sales. Show `PROVIDER_PENDING` only for a locally registered provider identity that can later be matched unambiguously; otherwise show sync watermark/staleness, not an estimated Square tender. Test late Orders and multiple same-location sessions. | MVP 2 |
| D-17 | Shared stock allocation | Establish one stock-item identity and source-event key for session loads, transfers, accepted sales, returns, and dispositions. Atomically prevent allocation of the same known units to concurrent sessions; reconcile each committed allocation once to the stock movements introduced in MVP 3 and extended in MVP 6. At MVP 2, where opening stock is not yet counted, label session availability as operator-entered and require a counted/transfer reconciliation before claiming global sold-out protection; unresolved differences block a reliable stock claim. | MVP 2–4 |
| D-18 | Attendance vocabulary | Attended = {Attended, Partial Day}. Excluded = {Vacation, Cancelled, Family, Personal, Illness, Emergency}. Not Attended = anything else. This follows the plan and blueprint (Cancelled is Excluded) and adds the workbook's extra statuses. | MVP 2/5 |
| D-19 | Market Import Status (API sync) | `IMPORTED` if at least one accepted line falls in the visit window. `SALES DATA NOT IMPORTED` if Attended, zero lines, and the sync watermark has passed close + 24 h. `NOT EXPECTED` if Not Attended. `EXCLUDED` if Excluded. | MVP 2 |
| D-20 | Perishability mapping | `is_perishable` = workbook *Spoils If Unsold*. *Shelf Stable* is informational only. VAR001 is perishable; VAR002 carries forward. | MVP 3/6 |
| D-21 | "Inventory Variance" | The workbook value (Available − Sold − Samples) is stored as `unsold_remainder`. `count_variance` means a physical-count adjustment only. RT027/RT031 assert `unsold_remainder = 3`. | MVP 6 |
| D-22 | Travel fixture translation | Workbook *Default Round Trip Miles* N becomes two directed legs of N/2 (Home → Market, Market → Home). *Override Miles* becomes a leg override. RT075 = 84 and RT076 = 56.28 stay unchanged. | MVP 5 |
| D-23 | Structural-case translation | `ISFORMULA`/`FORMULATEXT` cases (46) turn into behavioral assertions that the named KPI computes the correct value from fixtures; for RT022–RT024, the assertion is that the KPI excludes test records. Row-count/meta cases (14) turn into schema, seed, or config assertions on the application equivalent (settings seeded ≥ 6, 6 release controls, 4 data-quality areas, and so on). RT110 checks a recorded application release version. RT041 becomes a test-record leak test. The mapping is kept in the manifest. | MVP 7 |
| D-24 | Ranking score inputs | Business Score and Personal Score are manager-entered 0–100 inputs per market per as-of date, like the opportunity components. Lifetime Avg Profit = mean net profit per Attended visit. | MVP 7 |
| D-25 | Health score | Open issues: Imports = open import exceptions + missing imports. Product Setup = active products not READY. Inventory = inventory validation errors. Testing = failed cases in the latest run. Status labels follow the workbook: Excellent ≥ 95, Good ≥ 85, Needs Review ≥ 70, else Action Required. | MVP 7 |
| D-26 | Fixture conflicts | Seed each workbook case group in its own isolated scenario, so RT043 valuation uses its own 3.80 cost and does not contradict RT056. Square fees always come from the formula; the 4.50 fixture value is not seeded. | MVP 7 |
| D-27 | Deterministic as-of date | Workbook regression cases run with `as_of = 2026-01-05`, the fixture week. That makes VAR003 (2025-01-01) REVIEW COST and VAR001 (2026-01-01) OK. | MVP 3/7 |
| D-28 | Product status rule | READY if recipe and cost are both complete. CONFIGURE PRODUCT if both are missing. SETUP REQUIRED otherwise. Missing Items is `Recipe`, `Cost`, or `Recipe, Cost`. | MVP 3 |
| D-29 | Product→recipe cardinality | Each Variation ID maps to exactly one recipe. One recipe may serve many variations (RT058 = 2). | MVP 3 |
| D-30 💲 | Units & precision | Units: each, g, kg, oz, lb, ml, l, tsp, tbsp, fl oz, cup, pt, qt, gal. Convert only within the same dimension. Mass↔volume needs a per-ingredient density. Quantities use NUMERIC(14,4). Money uses NUMERIC(14,4) internally and rounds to 2 dp, ROUND_HALF_UP, at display and export. | MVP 3 |
| D-31 | Opening-count cutoff | Balance = the count at `counted_at` plus approved movements with `occurred_at > counted_at`. A movement with `occurred_at ≤ counted_at` that arrives later needs an audited restatement. | MVP 3 |
| D-32 | MVP 4 balance interface | A single `StockBalanceReader.on_hand(item, as_of)` over the audited opening count plus approved post-count purchases/restocks, confirmed prep, accepted Square/manual sales, samples, count corrections, and market-session allocation dispositions. Deduplicate by source event; reconcile session allocations to sale movements rather than subtracting both. Exclude expired lots and, after each local weekly boundary, remaining perishables from available stock even before MVP 6 automates waste posting; surface missing dates/unknown expiry for review. MVP 6 extends the same movement source and read contract with versioned closes and waste postings, not a replacement balance ledger. | MVP 4 |
| D-33 | Period calendar | Week = half-open local interval `[Monday 00:00, next Monday 00:00)` in `business_timezone`, converted to UTC instants for queries; close runs Monday 03:00 local. A period counts as closed when the close job succeeds. Test subsecond boundary events and DST weeks. | MVP 6/7 |
| D-34 | Source classification | The WDS v2.1 DOCX is **superseded** because it has no specific content. The Devin prompt is **reference-only/superseded**. The blueprint and both workbooks are **governing references** below the plan. | Gate |

Approved by: ____________________  Date: ____________  Commit: ____________

## 6. User-Only Actions (just in time)

| ID | Action | Needed before | Link/Detail |
|---|---|---|---|
| U-1 | ✅ Done 2026-09-30 — Install WSL 2 with Ubuntu 26.04 LTS (`wsl --install -d Ubuntu-26.04`), then Docker Desktop (WSL 2 backend) | Foundation slice | Capability 11.1; [Windows Docker guide](../user-docs/Docker_Windows11_Installation_Guide.md); https://docs.docker.com/desktop/setup/install/windows-install/ |
| U-2 💲 | Create a Google Cloud project with a Document AI Expense Parser, then pick a region and a monthly budget alert amount | Future optional Google provider activation only; not MVP 1 | See Capability 1 future enhancement |
| U-3 🔒 | Choose an encrypted backup destination and a key owner; approve D-15 | MVP 1 real data | Capability 11.2 |
| U-4 | Create a Square Developer sandbox app and add its token to `.env` (never to chat) | MVP 2 integration tests against sandbox; unit tests are mocked | Capability 3.1 |
| U-5 💲 | Set up the Meta WABA, phone number, display name, consent wording, and spend threshold | MVP 4 production | Capability 13.1 |
| U-6 | Provision the Proxmox VM, network exposure, and GitHub deploy secrets | First production promotion | Capability 11.2–11.3 |
| U-7 💲 | Tax professional signs off on the per-year mapping; owner supplies the provider coverage certificate | MVP 8 production | Capability 12.4 |

Credentials must be typed directly into `.env` files or secret stores. Never paste them into chat.

## 7. Vibe-Coding Slice Queue

Every slice follows the same template:
- **Scope:** the steps listed.
- **Evidence:** named focused tests and applicable manifest IDs pass, then `ruff`, `mypy`, and `pytest` on the host; run the same checks and migration tests in the web container. Record actual commands, environment, and outcomes, never infer coverage from a planned test ID.
- **Stop conditions:** a decision not covered by §5, a user-only action, or a failure the agent cannot fix after diagnosis.

Only after D-00 is approved can the agent move to the next **fully specified, approved and unblocked** row without asking. The active task and next step remain in `03-current-slice.md`; a passing host suite does not clear a Docker-dependent gate.

- [ ] Before activating an MVP 2–8 outline, write its next bounded slice in `03-current-slice.md` with prerequisites, exclusions, acceptance assertions, linked manifest IDs or focused test names, commands, and owner-approved decisions; validate the slice specification against the governing capability and roadmap. No outline is an automatic implementation instruction.
- [ ] Before promoting a release profile, replace applicable `PLANNED` manifest rows with verified scenario fixtures, application expected results, real test IDs, runnable validation commands, and recorded artifact-specific results; run the profile against the pinned candidate image and migrations.

### MVP 1 (Receipts)
| Slice | Scope | Manifest IDs |
|---|---|---|
| S0 | Foundation scaffold: pyproject + lock, `src/mbs`, health endpoint; Compose container validation passed 2026-09-30 (all five services up, `/health` ok, in-container pytest/ruff/mypy pass). The in-memory receipt domain work in `03-current-slice.md` also precedes S1. | Focused receipt tests named in `03-current-slice.md` |
| S1 | SQLAlchemy/Alembic baseline, `tbl_settings` with seeded catalog, audit log, error log, test DB fixture | RT093 (app equivalent) |
| S2 | Users, Argon2id, server sessions, CSRF, roles, first-admin bootstrap CLI, admin reset (D-11–D-14) | RM-014 |
| S3 | Protected file store, upload endpoint, signature/size validation, SHA-256 unique, outbox, ClamAV adapter (D-07, D-09) | RM-001, RM-003 |
| S4 | `OCREngine` interface; local Tesseract + OpenCV adapter tested with synthetic fixtures; Celery task with lease/idempotency and failed-job retry/review | RM-002, RM-006 |
| S5 | Receipt upload/header/items models, ISO normalization, `Receipt_ID` (D-10), unique constraint, totals check | RM-005, RM-009, RM-017 |
| S6 | pHash near-duplicate hold and manager resolution (D-08) | RM-004 |
| S7 | Editable category rules table seeded from blueprint §6.5 | RM-018 |
| S8 | Read APIs; list/detail/upload pages (Jinja2/HTMX, pinned Tailwind asset); zero-OCR reads | RM-007 |
| S9 | Review/correction, `receipt_document` snapshot, `Receipt_ID` collision hold | RM-008, RM-013 |
| S10 | Four dispositions, thin ingredient-purchase/expense/asset records, minimal Ingredient/Recipe, idempotent approval, manual entry | RM-011 |
| S11 | Remembered item rules | RM-012 |
| S12 | Soft delete, import audit, retention settings (no auto-purge) | RM-015 |
| S13 | Backup/restore scripts, restart-survival smoke, `receipt-mvp` profile run recorded in `tblTesting` | RM-010, RM-016 |
| Future (outside MVP 1) | *(Needs U-2, U-3 and provider approvals)* Optional Document AI adapter behind a feature flag; one controlled live-provider smoke test | — |

### MVP 2–8 (outlines only; create and approve bounded slices before any implementation)
- **MVP 2:** read-only Square adapter and SQ-001 gate → Square POS/session correlation (D-16) and stock source-event contract (D-17) → Catalog staging → minimal product + effective cost → market directory, location map, dated visits, operating hours (D-01, D-18) → Orders staging with cursor → line acceptance and exceptions (D-03) → manual sales → Payments/fees reconciliation → HELPER role and market-day session → session allocation (D-02) → tender closeout → `sales-mvp`.
- **MVP 3:** Unit registry (D-30) → full product master and status (D-28) → recipes, supplies, waste % → ingredient cost history → purchases → MVP 1 migration replay/rollback → opening counts (D-31) → `costing-mvp` plus RT051–RT064 and RT070.
- **MVP 4:** `StockBalanceReader` (D-32) → shared production service → load lists → store-grouped shopping → WhatsApp adapter (mocked) → prep confirmation → `prep-mvp`.
- **MVP 5:** Market cost periods → weekly visits (D-18) → route legs and allocation (D-22) → production UI and corrections → expenses → assets → `markets-mvp` plus RT071–RT082.
- **MVP 6:** Movement ledgers → weekly snapshots (D-20, D-21, D-33) → expiry/close jobs → restatements → valuation → reorder → low-stock alerts → `inventory-mvp` plus RT026–RT050.
- **MVP 7:** Refresh runs/watermarks → scorecards → rankings (D-24) → opportunity → forecasts → Ops/Exec dashboards → health score (D-25) → structural-case translations (D-23) → `analytics-mvp` with all 110 cases.
- **MVP 8:** Tax profile → Schedule C-aligned draft → Florida sales-tax workpaper → close checklist → snapshots/exports → release certification controls → `full-mbs`. Production waits on U-6 and U-7.

## 8. Re-assessment Triggers

Re-run this assessment when:
- §5 is signed.
- Docker is installed. *(Triggered 2026-09-30; see log below.)*
- Any MVP profile passes or fails.
- A governing plan file changes.

Record each change to a verdict here, with its date and the evidence behind it.

| Date | Change | Evidence |
|---|---|---|
| 2026-09-30 | Foundation slice scaffold built; host checks pass. Build verdict stays NO-GO until the Docker acceptance commands run (U-1). Capability 16 converted to checkboxes (F9). | pytest 1 passed, ruff and mypy strict clean on Python 3.12.10; `/health` returned 200 |
| 2026-09-30 | U-1 done: WSL 2 with Ubuntu 26.04 LTS and Docker Desktop installed. Foundation slice Build verdict NO-GO → **GO**; F1 resolved. | WSL 3.0.1.0, `wsl -l -v` → `* Ubuntu-26.04` v2; Docker Desktop 29.8.1 (Linux engine), Compose v5.5.1; `hello-world` ran; `docker compose config --quiet` OK; `docker compose up --build -d` started web, postgres (healthy), redis (healthy), celery-worker, celery-beat; `/health` → `{"status":"ok"}`; in-container pytest 24 passed, ruff and mypy clean |
