# Capability 1: Receipt Capture & OCR Pipeline

- [ ] **Capability complete** (all features below checked)

Bounded context: `mbs/receipts/` (blueprint §3.1 #5, §6). Accepts uploaded receipt images/PDFs, runs OCR, extracts structured line items, deduplicates, classifies categories. Runs as an async Celery task so uploads don't block the API.

## Feature 1.1 — OCR Engine Selection & Setup
- [ ] Feature complete

**Current choice:** Use Google Document AI's prebuilt **Expense Parser** for the Receipt MVP. It reduces local OCR tuning and produces receipt-oriented structured fields. The source image/PDF is sent to Google and usage may be billed by page/processor; the app stores the complete returned extraction in Postgres so normal viewing and reuse never incur another OCR request.

Keep the provider-neutral `OCREngine` interface. **Tesseract + OpenCV** may be retained as an optional local provider for offline/privacy-sensitive processing, with a likely accuracy/tuning trade-off; it is not the MVP default.

- [ ] 🧑‍💻 Create/configure a Google Cloud project and Document AI Expense Parser, enable the API, review current [pricing](https://cloud.google.com/document-ai/pricing) and regional data-handling terms, and set an agreed monthly budget alert.
- [ ] Store Google credentials and processor/region IDs only in deployment secrets; never commit them or store tokens in `tbl_settings`.
- [ ] Implement `OCREngine` and `DocumentAIEngine` as the configured MVP provider; keep Tesseract/OpenCV optional behind the same interface.
- [ ] Capture the provider response, OCR schema/provider version, confidence, and page count on the first successful processing; persist them before marking the job complete.

## Feature 1.2 — Upload & Async Processing
- [ ] Feature complete
- [ ] `POST /api/v1/receipts/upload` accepts image(s) or PDF, validates file type/size, stores to upload staging area, enqueues a Celery task (role: MANAGER+).
- [ ] Enforce configurable maximum file bytes, PDF page count, image dimensions, upload rate, and allowed media types; verify file signatures (not only extensions), reject malformed/encrypted files, and scan uploads before processing.
- [ ] Compute a source-file SHA-256 and check it against `tbl_receipt_uploads` before enqueuing OCR. Reject/return the existing upload for an exact duplicate and do not call Google again; enforce a database unique constraint to handle concurrent duplicate requests.
- [ ] Compute a local perceptual fingerprint for each image/PDF page before OCR. If it closely matches a stored source, mark the upload `POSSIBLE_DUPLICATE`, block the Google call, and require a manager to confirm “already imported” or “process as a new receipt”; never silently override a possible duplicate.
- [ ] Submit one OCR request for each newly accepted upload and persist the complete response before completing the job. Retry automatically only when the request is known not to have reached/been accepted by Google; if submission outcome is uncertain, mark `OCR_OUTCOME_UNKNOWN`, reconcile provider operation status where possible, and require an ADMIN-confirmed retry with a cost warning rather than resubmitting blindly.
- [ ] Viewing, searching, correcting, exporting, or reloading a receipt must read saved database data and never call OCR. Rerun OCR only through an explicit ADMIN action that warns about external data transfer and possible charge, records the reason, and saves a new extraction version without overwriting the original.
- [ ] Log engine/version, attempt, duration, failure reason, idempotent job key, and provider page count when applicable. Apply the configurable retention policy in Capability 2; if no period is configured, do not automatically purge source files or OCR payloads.
- [ ] Celery task orchestration per blueprint §6.3: (1) extract via configured OCR engine, (2) count existing `tbl_receipts` rows as pre-import baseline, (3) compute `Receipt_ID` per extracted receipt and check duplicates, (4) classify each line item's category, (5) report existing/new/duplicate/added counts, (6) append only non-duplicate receipts + line items, (7) stamp `import_timestamp`.
- [ ] Task status/result endpoint so the UI can poll and show progress on the upload page.

## Feature 1.3 — Duplicate Detection
- [ ] Feature complete
- [ ] Define composite `Receipt_ID` key exactly as specified in blueprint §6.2/§4.2 (store + date + time + TC#/Receipt# derived key).
- [ ] Enforce `Receipt_ID` uniqueness in Postgres after OCR; if a different image resolves to an existing Receipt_ID, reject/skip insert without overwriting existing header, JSONB document, or items and log the duplicate upload in the audit trail (Governance Rule 5).

## Feature 1.4 — OCR Data Field Extraction
- [ ] Feature complete
- [ ] Extract required header fields: Store, Date (MM/DD/YYYY), Time (HH:MM:SS), TC#/Receipt#, Total.
- [ ] Extract optional header fields: Subtotal, Tax, Payment Method.
- [ ] Extract line items: Item Description (required), Line Total (required), UPC, Qty, Weight (lb), Unit Price (all optional per source formatting).
- [ ] Validate extracted totals against sum of line totals; flag mismatches for manual review rather than silently accepting bad data.

## Feature 1.5 — Category Classification
- [ ] Feature complete
- [ ] Implement keyword-based classifier covering all categories from blueprint §6.5: Beverages, Produce, Household, Frozen Meals, Lawn & Garden, Dairy, Meat, Bakery, Snacks, Personal Care, Other.
- [ ] Keep merchandise Category classification separate from receipt business disposition (Personal / Non-business, Ordinary Business Purchase, Recipe Ingredient, Capital Asset / Equipment), which is selected and remembered in Capability 2.
- [ ] Keep classification rules in a configurable/editable rules table (not hardcoded) so keywords can be tuned without a deploy.
- [ ] Optional stretch: allow a small local model/rules-engine upgrade path later without changing the classifier's public interface.

## Feature 1.6 — Early Receipt MVP Release
- [ ] Feature complete
- [ ] Phase 1 independently delivers secure upload, Google Document AI extraction, manual review/correction, duplicate handling, and persisted receipt headers/line items in Postgres; it does not wait for Square, recipes, inventory, dashboards, tax, or WhatsApp.
- [ ] Persist required/available OCR fields from Feature 1.4 and preserve the complete raw response and normalized receipt document per Capability 2.1. Store the original image/PDF in protected persistent file storage.
- [ ] Receipt review in MVP 1 supports all four business dispositions. Uncertain lines may remain Unclassified drafts without blocking receipt persistence; do not post them until reviewed.
- [ ] Implement thin receipt-linked ingredient-purchase, ordinary-expense, and asset records plus minimal Ingredient/Recipe records in MVP 1. Full product setup, costing, depreciation, weekly operations, and inventory valuation remain later work.
- [ ] MVP acceptance: a manager can upload a receipt, see OCR/task status, correct extracted header/items, save, and retrieve the record after app restart from Postgres; duplicate uploads are detected and audited.
