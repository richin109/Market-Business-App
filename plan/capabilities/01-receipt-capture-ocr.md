# Capability 1: Receipt Capture & OCR Pipeline

- [ ] **Capability complete** (all features below checked)

Bounded context: `mbs/receipts/` (blueprint §3.1 #5, §6). Accepts uploaded receipt images/PDFs, runs OCR, extracts structured line items, deduplicates, classifies categories. Runs as an async Celery task so uploads don't block the API.

## Feature 1.1 — OCR Engine Selection & Setup
- [ ] Feature complete

**Current choice:** Use local **Tesseract + OpenCV** processing for the Receipt MVP release. During local S1-S8 development, the provider-neutral boundary may use deterministic mocked extraction; receipt images/PDFs stay on the app's host during real local OCR. Persist the raw extraction and normalized data in Postgres so normal viewing and reuse never rerun OCR. Validate the configured local adapter against synthetic receipt fixtures and route uncertain fields to manual review.

Keep the provider-neutral `OCREngine` interface. **Google Document AI Expense Parser** is a future optional provider, not an MVP dependency; enabling it requires separate privacy, region, cost, and retry-policy approvals.

- [ ] Implement `OCREngine` with Tesseract + OpenCV as the configured local MVP provider; test extraction against synthetic image/PDF fixtures and flag uncertain fields for review.
- [ ] Capture the local engine/version, raw extraction, confidence when available, and page count on the first successful processing; persist them before marking the job complete.

## Feature 1.2 — Upload & Async Processing
- [ ] Feature complete
- [ ] Define receipt PostgreSQL tables with SQLAlchemy 2 models and create or alter them only through reviewed, version-controlled Alembic migrations; do not apply manual DDL or use `Base.metadata.create_all()` to manage the schema. Test migrations against a fresh database and the prior schema.
- [ ] `POST /api/v1/receipts/upload` accepts image(s) or PDF, validates file type/size, stores to upload staging area, and creates the upload/outbox records (role: MANAGER+); a retrying publisher enqueues committed work to Celery.
- [ ] Support directory-selected batches through the same upload service, with independent validation, malware scanning, duplicate detection, protected storage, and job status for each file. An invalid, duplicate, or failed file must not discard successful files or prevent other valid files from processing; retries must not duplicate uploads or receipts.
- [ ] Bound batch file count, total bytes, and concurrent submissions with configurable limits enforced server-side as well as in the browser. Report limit failures explicitly; never silently truncate a directory selection. Treat browser-provided relative paths as untrusted display metadata, never as server filesystem paths or storage keys; identical filenames in different subfolders must not overwrite each other.
- [ ] Persist each staged file's upload row and an outbox/task event in one database transaction; a retrying dispatcher publishes committed jobs to Redis/Celery. Workers claim jobs with a lease/lock and idempotency key so a broker outage or worker crash cannot lose work or process one upload concurrently.
- [ ] Promote staged files to their immutable protected-store keys only after the upload record commits; clean abandoned staging files through an audited age-based janitor without deleting files referenced by live database rows.
- [ ] Enforce configurable maximum file bytes, PDF page count, image dimensions, upload rate, and allowed media types; verify file signatures (not only extensions), reject malformed/encrypted files, and scan uploads before processing.
- [ ] Compute a source-file SHA-256 and check it against `tbl_receipt_uploads` before enqueuing OCR. Reject/return the existing upload for an exact duplicate and do not rerun OCR; enforce a database unique constraint to handle concurrent duplicate requests.
- [ ] Compute a local perceptual fingerprint for each image/PDF page before OCR. If it closely matches a stored source, mark the upload `POSSIBLE_DUPLICATE`, block OCR, and require a manager to confirm “already imported” or “process as a new receipt”; never silently override a possible duplicate.
- [ ] Process each newly accepted upload locally and persist the complete extraction before completing the job. Retry failed local jobs idempotently without creating duplicate receipt records; retain failure details and require manual review when extraction remains uncertain.
- [ ] Viewing, searching, correcting, exporting, or reloading a receipt must read saved database data and never call OCR. Rerun OCR only through an explicit audited ADMIN action that records the reason and saves a new extraction version without overwriting the original.
- [ ] Log engine/version, attempt, duration, failure reason, idempotent job key, and provider page count when applicable. Apply the configurable retention policy in Capability 2; if no period is configured, do not automatically purge source files or OCR payloads.
- [ ] Celery task orchestration per blueprint §6.3: (1) extract via configured OCR engine, (2) count existing `tbl_receipts` rows as pre-import baseline, (3) compute `Receipt_ID` per extracted receipt and check duplicates, (4) classify each line item's category, (5) report existing/new/duplicate/added counts, (6) append only non-duplicate receipts + line items, (7) stamp `import_timestamp`.
- [ ] Task status/result endpoint so the UI can poll and show progress on the upload page.

## Feature 1.3 — Duplicate Detection
- [ ] Feature complete
- [ ] Define composite `Receipt_ID` key exactly as specified in blueprint §6.2/§4.2 (store + date + time + TC#/Receipt# derived key).
- [ ] Enforce `Receipt_ID` uniqueness in Postgres after OCR; if a different image resolves to an existing Receipt_ID, reject/skip insert without overwriting existing header, JSONB document, or items and log the duplicate upload in the audit trail (Governance Rule 5).

## Feature 1.4 — OCR Data Field Extraction
- [ ] Feature complete
- [ ] Preserve the provider's raw Date and Time values in the OCR payload, then normalize the canonical receipt date to ISO 8601 `YYYY-MM-DD` and the canonical receipt time to `HH:MM:SS`. Ambiguous, incomplete, or invalid source values require manual review and cannot be posted as business dates.
- [x] Extract required header fields: Store, Date, Time, TC#/Receipt#, Total.
- [x] Extract optional header fields: Subtotal, Tax, Payment Method.
- [x] Extract line items: Item Description (required), Line Total (required), UPC, Qty, Weight (lb), Unit Price (all optional per source formatting).
- [ ] Extract printed pack size and unit text when present (for example `1 PT`, `2 LB`, `16 OZ`) into raw line fields, separate from the purchased-package quantity. Never guess a missing size; leave it blank for reviewer entry (Capability 2.5; RM-021).
- [x] Validate extracted totals against sum of line totals; flag mismatches for manual review rather than silently accepting bad data.

## Feature 1.5 — Category Classification
- [ ] Feature complete
- [x] Implement keyword-based classifier covering all categories from blueprint §6.5: Beverages, Produce, Household, Frozen Meals, Lawn & Garden, Dairy, Meat, Bakery, Snacks, Personal Care, Other.
- [x] Keep merchandise Category classification separate from receipt business disposition (Personal / Non-business, Ordinary Business Purchase, Recipe Ingredient, Capital Asset / Equipment), which is selected and remembered in Capability 2.
- [ ] Keep classification rules in a configurable/editable rules table (not hardcoded) so keywords can be tuned without a deploy.
- [ ] Optional stretch: allow a small local model/rules-engine upgrade path later without changing the classifier's public interface.

## Feature 1.6 — Early Receipt MVP Release
- [ ] Feature complete
- [ ] Phase 1 independently delivers secure upload, the configured local Tesseract + OpenCV extraction, manual review/correction, duplicate handling, and persisted receipt headers/line items in Postgres. Mocked OCR is sufficient for development slices but not for the release profile; it does not wait for Google, Square, recipes, inventory, dashboards, tax, or WhatsApp.
- [ ] Persist required/available OCR fields from Feature 1.4 and preserve the complete raw response and normalized receipt document per Capability 2.1. Store the original image/PDF in protected persistent file storage.
- [ ] Receipt review in MVP 1 supports all four business dispositions. Uncertain lines may remain Unclassified drafts without blocking receipt persistence; do not post them until reviewed.
- [ ] Implement thin receipt-linked ingredient-purchase, ordinary-expense, and asset records plus minimal Ingredient/Recipe records in MVP 1. Full product setup, costing, depreciation, weekly operations, and inventory valuation remain later work.
- [ ] MVP acceptance: a manager can upload a receipt, see OCR/task status, correct extracted header/items, save, and retrieve the record after app restart from Postgres; duplicate uploads are detected and audited.

## Future Enhancement — Optional Google Document AI (outside MVP 1 completion)
- [ ] 🧑‍💻 Before enabling Document AI, create/configure a Google Cloud project and Expense Parser, review current [pricing](https://cloud.google.com/document-ai/pricing) and regional data-handling terms, and approve a monthly budget alert.
- [ ] Complete the real-data privacy, retention, malware-scanning, and provider-approval items in [the implementation-readiness gate](../02-implementation-readiness.md) before sending real receipts to Google; store credentials and processor/region IDs only in deployment secrets, never in source or `tbl_settings`.
- [ ] Implement and separately test `DocumentAIEngine` behind the same `OCREngine` boundary, including uncertain-submission reconciliation and cost-aware retries.
