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
| `plan/test-case-manifest.csv` | Contains 146 rows: 137 `PLANNED` and 9 `VERIFIED`. Planned rows may reference future tests, but most still lack runnable commands and do not count as coverage. RM-022/RM-023/RM-025 add synthetic split-source, OCR-evidence, and repeat-directory cases; RM-024 is a separate approval-gated private-corpus evaluation. SL-001–SL-004 add the D-20/D-35/D-36 shelf-life, expiry-job, and alert-eligibility cases. ST-001/ST-002 and IT-001/IT-002 add the D-37–D-40 store-registry and purchased-item identity/mapping cases. |
| `Market_Business_System_v3_3_Testing_Dashboard.xlsx` (42 sheets) | Contains the fixtures and 110 regression cases. 46 are behavioral, 46 are formula-existence checks (`ISFORMULA`/`FORMULATEXT`), 14 are row-count/meta checks, 3 check configuration, and 1 is a tautology (RT041 is always 0). |
| `Walmart_Receipt_Complete_With_AI.xlsx` | Reference-only receipt examples for deriving synthetic OCR fixtures and expected reconciliations; do not use customer purchase data or full original files as committed CI fixtures without the real-data gate and owner approval. |
| Blueprint DOCX | Formulas and schemas are useful. It has stale stack choices (React, K8s, CSV import) that the plan supersedes. |
| `WDS_v2_1_Reconstruction_Grade_Specification 1.docx` | **No usable content.** It has 373 lines, and 275 of them repeat three boilerplate sentences. Classify it as superseded (D-34). |
| `Devin_MBS_v3_3_Prompt.*` | Historical Java stack. Already marked superseded. |

## 3. Cross-Cutting Findings

| # | Severity | Finding | Resolution |
|---|---|---|---|
| F1 | ~~Blocker~~ Resolved 2026-09-30 | Docker Desktop was not installed; the current slice needs `docker compose`. Now installed (Docker Desktop 29.8.1, Compose v5.5.1, WSL 2 + Ubuntu 26.04 LTS) and the Compose stack passes its acceptance checks. | U-1 done |
| F2 | ~~Blocker (vibe)~~ Resolved 2026-09-30 | [mvp-slice-specifications.md](mvp-slice-specifications.md) now defines bounded MVP 2-8 slices with dependencies, acceptance assertions, traceability, validation commands, and stop conditions. The agent still stops at an unapproved decision, missing evidence, or user-only action under D-00. | Copy one approved row into [03-current-slice.md](03-current-slice.md) before implementation |
| F3 | Blocker (MVP 7) | 61 workbook cases are structural/meta/tautological, and three additional cases are configuration checks. "All 110 pass" has no executable meaning in Python yet. | D-23 translation rules and executable manifest evidence |
| F4 | High | Workbook fixtures conflict with each other. RT043 values TEST-VAR002 at cost 3.80, but RT056 requires VAR002 to have no cost. The `Sales_Data` Square Fee fixture is 4.50, but the formula gives 150 × 0.026 + 0.10 = 4.00. | D-26 |
| F5 | High | Time-dependent cases (REVIEW COST, Market Active) use `TODAY()`, so they are non-deterministic. | D-27 fixed as-of date |
| F6 | High | Workbook, blueprint, and plan use different vocabulary: Shelf Stable/Spoils If Unsold vs the item Shelf Life duration that replaced `is_perishable`, "Inventory Variance" vs count variance, round-trip miles vs directed legs, attendance statuses, health-status labels. | D-18, D-20–D-22, D-25 |
| F7 | Medium | Numeric limits are left unspecified: upload size, pHash threshold, rate limits, session lifetime, sync interval, market-day targets. | D-05–D-08, D-13, D-14 |
| F8 | Medium | Some pieces are undefined: a HELPER role (Capability 16), password reset without an email provider, market ranking Business/Personal Score sources, and health-score "open issue" counting. | D-11, D-12, D-24, D-25 |
| F9 | Low | Capability 16 features use plain `-` bullets, not `- [ ]` checkboxes, so progress can't be tracked like other capabilities. | Convert when that capability becomes active |
| F10 | Low | Capability 9.2 lists Governance Rules 1–5, 7, and 8. Rule 6 (Release Gate) lives only in Capability 10.3. | Informational; no change needed |
| F11 | Info | The blueprint `Receipt_ID` example uses `MM/DD/YYYY`, but the plan's date policy requires ISO dates. | D-10 |

## 4. Per-MVP Assessment

### MVP 1 — Receipts
- **Ready:** local receipt foundations and mocked extraction/review. Synthetic fixture design exists; production-like local OCR accuracy still needs validation.
- **Gaps:** D-06–D-09 release/upload controls, approved canonical reference/time policy (D-10), split-order source/line association and image-only PDF review (RM-022/RM-023), password reset path (D-11), and real-data privacy approvals.
- **Agent can do without user:** synthetic and mocked local development only; release promotion still needs the owner decisions and readiness evidence.
- **Prod needs:** U-3 real-data classification/retention/backup approval, an authorized RM-024 local receipt-directory evaluation meeting approved OCR accuracy/review thresholds, and a timed restore. U-2 applies only to the future Google enhancement; no real files belong in CI.

### MVP 2 — Square, Sales Ledger, Market-Day POS
- **Blocked by three owner decisions already listed in 03-current-slice.md** (timezone authority, session price/availability, sale/close state table), plus the offline-mode decision and the quantitative targets.
- **Also undefined:** HELPER role (D-12), attendance vocabulary (D-18), and market Import Status derivation for API sync (D-19). The workbook's RT077–RT079 depend on D-19.
- **Agent can do after approval:** execute the bounded rows 2.1-2.5 in [mvp-slice-specifications.md](mvp-slice-specifications.md) against a Square sandbox or recorded fixtures. Payments, Orders, and Catalog are mockable.

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
- Needs the shelf-life mapping (D-20), the lot expiry derivation (D-35), the expiry job/alert eligibility rule (D-36), a rename for "Inventory Variance" (D-21), and the period calendar (D-33).

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
| D-10 | `Receipt_ID` and reference authority | **Proposed, owner approval pending:** keep one immutable canonical receipt identity with reviewed normalized store, full ISO purchase date, verified transaction time when present, and a reviewed vendor-specific order/receipt reference (a printed REF may be authoritative rather than TR#). The store component of `Receipt_ID` is the normalized **printed store text** captured at import, never the canonical `store_id`: renaming, grouping, or splitting a store under D-37 must not change the identity of an accepted receipt. The resolved `store_id` is a separate mutable attribute used for filtering and reporting. Preserve all printed alternatives and register versus footer times as raw evidence. A partial PDF with no time uses store/date/order reference plus location when available only to propose a same-order review hold; never create or merge an accepted identity from that partial key without confirmation. Specify the migration and collision policy from the existing store/date/time/transaction key before implementation. | MVP 1 |
| D-11 🔒 | Password reset | No email provider in MVP 1. An ADMIN starts the reset, which issues a one-time token shown once. A local CLI recovery command covers the last admin. | MVP 1 |
| D-12 🔒 | Roles | ADMIN, MANAGER, VIEWER, plus HELPER in MVP 2. HELPER can only open/sell/close market-day sessions for the assigned visit. | MVP 1/2 |
| D-13 🔒 | Login throttling | 5 failures per minute per IP. The account locks for 15 min after 10 consecutive failures. | MVP 1 |
| D-14 🔒 | Sessions | 2 h idle timeout, 12 h absolute. Bearer JWT API stays disabled until a machine client needs it. | MVP 1 |
| D-15 🔒 | Data classification | Receipts, OCR payloads, audit data, and backups are *Confidential – internal*. Data owner: business owner. Permitted users: named ADMIN/MANAGER accounts. No automatic purge until retention periods are set (current plan default). | MVP 1 prod |
| D-16 | Square capture/correlation | Square POS is the only Square payment capture surface in MVP 2; MBS must not present a Square checkout button or claim it initiated a Square payment. Import Orders/Payments by provider IDs and correlate to a market session using an explicit Square session reference if available; otherwise require an authorized match against Location ID, full local business date, visit, and operating hours. Ambiguous or unmatched Orders remain visible exceptions, not invented pending sales. Show `PROVIDER_PENDING` only for a locally registered provider identity that can later be matched unambiguously; otherwise show sync watermark/staleness, not an estimated Square tender. Test late Orders and multiple same-location sessions. | MVP 2 |
| D-17 | Shared stock allocation | Establish one stock-item identity and source-event key for session loads, transfers, accepted sales, returns, and dispositions. Atomically prevent allocation of the same known units to concurrent sessions; reconcile each committed allocation once to the stock movements introduced in MVP 3 and extended in MVP 6. At MVP 2, where opening stock is not yet counted, label session availability as operator-entered and require a counted/transfer reconciliation before claiming global sold-out protection; unresolved differences block a reliable stock claim. | MVP 2–4 |
| D-18 | Attendance vocabulary | Attended = {Attended, Partial Day}. Excluded = {Vacation, Cancelled, Family, Personal, Illness, Emergency}. Not Attended = anything else. This follows the plan and blueprint (Cancelled is Excluded) and adds the workbook's extra statuses. | MVP 2/5 |
| D-19 | Market Import Status (API sync) | `IMPORTED` if at least one accepted line falls in the visit window. `SALES DATA NOT IMPORTED` if Attended, zero lines, and the sync watermark has passed close + 24 h. `NOT EXPECTED` if Not Attended. `EXCLUDED` if Excluded. | MVP 2 |
| D-20 | Shelf life and perishability | **Owner-directed 2026-09-30, replaces the `is_perishable` checkbox.** Every stocked product, ingredient, and supply stores a required Shelf Life as value + unit (`days`, `weeks`, `months`, `never`), asked when the item is first added and remembered as that item's default for all future lots. Perishable means unit ≠ `never`; there is no system default duration, so an item without an answer cannot hold stock. Workbook mapping: *Spoils If Unsold* items require an owner-entered duration, *Shelf Stable* remains informational, and legacy `is_perishable` FALSE maps to `never`. VAR001 is perishable with an entered duration; VAR002 is `never` and carries forward. Seed the workbook spoilage fixtures (RT026–RT034) with a VAR001 duration that expires inside the fixture week so their expected values stay unchanged. | MVP 3/6 |
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
| D-32 | MVP 4 balance interface | A single `StockBalanceReader.on_hand(item, as_of)` over the audited opening count plus approved post-count purchases/restocks, confirmed prep, accepted Square/manual sales, samples, count corrections, and market-session allocation dispositions. Deduplicate by source event; reconcile session allocations to sale movements rather than subtracting both. Exclude lots whose `Perishable By` is at or before the as-of instant from available stock even before MVP 6 automates waste posting, and surface items missing a Shelf Life for review; unexpired perishable stock stays available across a weekly boundary. MVP 6 extends the same movement source and read contract with versioned closes and waste postings, not a replacement balance ledger. | MVP 4 |
| D-33 | Period calendar | Week = half-open local interval `[Monday 00:00, next Monday 00:00)` in `business_timezone`, converted to UTC instants for queries; close runs Monday 03:00 local. A period counts as closed when the close job succeeds. Test subsecond boundary events and DST weeks. | MVP 6/7 |
| D-34 | Source classification | The WDS v2.1 DOCX is **superseded** because it has no specific content. The Devin prompt is **reference-only/superseded**. The blueprint and both workbooks are **governing references** below the plan. | Gate |
| D-35 | Lot expiry derivation | **Owner-directed 2026-09-30.** `Perishable By` = acquisition instant + item Shelf Life, where acquisition is the approved receipt/purchase date and falls back to the stock-record/list-item creation instant. Evaluate `weeks`/`months` as calendar arithmetic in `business_timezone` with month-end clamping, then store UTC. Recipe-produced lots always use the recipe's mandatory output shelf life (which may be `never`) from the production timestamp, overriding the finished product's own shelf life. Changing an item's or recipe's shelf life recomputes open lots from their acquisition/production instant; already-posted waste and closed periods change only through an audited restatement. | MVP 3/4/6 |
| D-36 | Expiry job and alert eligibility | **Owner-directed 2026-09-30.** An expiry job runs at worker/beat startup and every `expiry_scan_interval_minutes` (default 240, every four hours), posting exactly one idempotent waste movement per lot at or after its `Perishable By`, including lots that expired while the system was stopped. Weekly close no longer wastes remaining perishables as a class; it reconciles and flags any expired-but-unwasted lot. Each waste movement is dated at the lot's `Perishable By`, not at scan time, so a detection lag of up to one interval never shifts a period total. Low-stock alerts cover items whose shelf life is `never` or at least `low_stock_alert_min_shelf_life_days` (default 30), using `low_stock_threshold_pct` (20%). | MVP 6 |
| D-37 | Store registry and grouping | **Owner-directed 2026-09-30.** Every purchase source is a canonical store created automatically from the store value read on an imported order/receipt; no purchase path accepts free-text store entry. Each distinct source spelling is stored as a normalized alias resolving to exactly one canonical store. Alias matching is **exact on the normalized key only** (Unicode casefold, trim, collapse internal whitespace, strip punctuation and trailing store/unit numbers), governed by `store_alias_normalization_version`; similarity scoring may only propose a grouping for confirmation and never auto-resolves. A user may edit the display name and group aliases or stores into one canonical store; display names are not unique keys, and saving a name already used by another active store requires an explicit confirmation warning. Merge re-points aliases, existing receipts, and future resolution, records actor/reason/timestamp, and retains the merged store as superseded. Split re-points the selected aliases forward only: already-posted receipts, purchases, costs, expenses, and stock keep the `store_id` resolved at posting time, and moving history requires an audited restatement. Raw printed store text on a source document is never rewritten. A missing, unreadable, or multiply-matching store value is held for review instead of auto-created. Backfill of pre-existing receipts is a reviewed one-time migration: add nullable `store_id`, create canonical stores/aliases from existing normalized store text, then enforce non-null. | MVP 1 |
| D-38 | Item common name | **Owner-directed 2026-09-30.** Canonical items and store items may carry a user-entered common name because receipt descriptions are abbreviated. The displayed name defaults to the description read from the order until a common name exists. A common name is display/search metadata only: it never becomes identity, a dedup or match key, and never overwrites the stored raw description. | MVP 1 |
| D-39 | Purchased-item identity | **Owner-directed 2026-09-30.** A purchased line's identity is canonical store + the store's own product identifier (merchant item number/SKU, or provider variation ID), never the description or common name. Each store item resolves to exactly one application-wide canonical `item_id`. A canonical item owns zero or more store items: an item **observed from a store** always retains at least one store item and its last store item may not be moved away (use an audited merge instead), while an item created during master-data setup before any purchase may legitimately have none until its first purchase. Costs, stock, recipes, analytics, and tax facts key by `item_id`. A line without a usable store product identifier is held for reviewer entry, and an unmapped store item blocks posting rather than creating a duplicate item. Pre-existing receipt lines are backfilled by a reviewed one-time migration: create store items where an identifier exists, and flag lines without one as mapping holds rather than inventing identifiers. | MVP 1 |
| D-40 | Item mapping and suggestions | **Owner-directed 2026-09-30.** A mapping screen maps store items to canonical items, moves a store item between items, and splits a store item into its own canonical item, subject to D-39's one-item-per-store-item rule and the last-store-item constraint on store-observed items. Suggestions ranked from common names, receipt descriptions, shared UPC, and confirmed rules are proposals only, bounded by `item_mapping_suggestion_limit`, and require explicit confirmation; description similarity never auto-merges. Remapping is effective-dated and audited: already-posted records keep the `item_id` resolved at posting time and change only through a linked restatement. Each sellable product's Square Variation ID resolves to exactly one `item_id`, so inventory snapshots keyed by Variation ID and movement ledgers keyed by `item_id` reconcile through that single link. | MVP 1 |

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
| S4 | `OCREngine` interface; local Tesseract + OpenCV adapter tested with selectable-text and image-only synthetic PDFs; Celery task with lease/idempotency and failed-job retry/review | RM-002, RM-006, RM-023 |
| S5 | Receipt upload/header/items models, ISO normalization, `Receipt_ID` (D-10), unique constraint, totals check | RM-005, RM-009, RM-017 |
| S6 | pHash near-duplicate hold and manager resolution (D-08) | RM-004 |
| S7 | Editable category rules table seeded from blueprint §6.5 | RM-018 |
| S8 | Read APIs; list/detail/upload pages (Jinja2/HTMX, pinned Tailwind asset); zero-OCR reads | RM-007 |
| S9 | Review/correction, `receipt_document` snapshot, `Receipt_ID` collision hold | RM-008, RM-013 |
| S10 | Four dispositions, thin ingredient-purchase/expense/asset records, minimal Ingredient/Recipe, idempotent approval, manual entry | RM-011 |
| S10a | Reviewed source-PDF association for one or many orders per source, supplemental line occurrences, changed-source versions and conflict holds, migration from single upload FK, subtotal reconciliation, repeated-directory idempotency, browser review, and cross-posting idempotency | RM-022, RM-023, RM-025 |
| S11 | Remembered item rules | RM-012 |
| S12 | Soft delete, import audit, retention settings (no auto-purge) | RM-015 |
| S13 | Backup/restore scripts including all linked source PDFs, restart-survival smoke, `receipt-mvp` profile and separately approved private-corpus summary recorded with redacted evidence | RM-010, RM-016, RM-022, RM-024 |
| S14 | Canonical store registry (minimum): `tbl_stores`/`tbl_store_aliases`, auto-created stores and aliases from imported order data, exact normalized-key matching with ambiguity holds, store list plus display-name editing, canonical `store_id` receipt filtering, and a reviewed nullable-then-non-null backfill migration from the existing `tbl_receipts.store` text (D-37) | ST-001 |
| S15 | Purchased-item identity (minimum): `tbl_store_items` unique on `store_id` + `store_product_id`, `tbl_items` canonical identity, many-to-one mapping with the D-39 last-store-item rule, common-name capture defaulting to the order description, posting blocked for unmapped store items, remembered rules re-keyed to the store item, and a reviewed backfill migration that flags identifier-less legacy lines as holds (D-38, D-39) | IT-001 |
| S16 | Store and item administration: audited store merge/split with forward-only alias re-pointing, item mapping screen with ranked confirmation-required suggestions, move/split operations, and effective-dated remap restatement (D-37, D-40) | ST-002, IT-002 |
| Future (outside MVP 1) | *(Needs U-2, U-3 and provider approvals)* Optional Document AI adapter behind a feature flag; one controlled live-provider smoke test | — |

### MVP 2-8 bounded slices

The former MVP outlines are now executable slice specifications in [mvp-slice-specifications.md](mvp-slice-specifications.md). Each MVP has named slices, prerequisites, owner decisions, acceptance assertions, manifest/test traceability, release-profile requirements, and stop conditions. Before implementation, copy exactly one approved row into `03-current-slice.md`.

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
| 2026-09-30 | MVP 2-8 vibe-readiness contract added; F2 resolved. | `plan/mvp-slice-specifications.md` defines 23 bounded rows across MVP 2-8 with prerequisites, owner gates, focused acceptance, release profiles, and stop conditions. |
