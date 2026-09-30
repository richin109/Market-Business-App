# Capability 2: Receipts Management

- [ ] **Capability complete** (all features below checked)

Covers storage and lifecycle of receipts once captured by Capability 1 — listing, retrieval, line-item detail, soft-delete, and the audit trail. Data model: `tbl_receipts` (summary) and `tbl_receipt_items` (line items), per blueprint §4.2. **Early Receipt MVP:** Features 2.1–2.6 are in scope, including dispositions and remembered item rules; they use thin receipt-linked business records and minimal ingredient/recipe records, not the full later costing, inventory, or asset-depreciation modules.

## Feature 2.1 — Data Model
- [ ] Feature complete
- [ ] Create `tbl_receipt_uploads` as the file/job-level record: unique source SHA-256, protected file-store key, media type/size, uploaded_by/time, processing status, exact/perceptual duplicate status, OCR attempt/version/page count, and audit fields. A PDF containing multiple receipts may link to multiple `tbl_receipts` rows.
- [ ] Give each receipt an immutable UUID `receipt_pk` primary key for all relationships and API routes. Store the source-derived composite `Receipt_ID` as a separate unique deduplication key; corrections to OCR header fields never change the primary key or silently re-key an accepted receipt.
- [ ] If a corrected header would produce a `Receipt_ID` already owned by another receipt, hold the correction for explicit ADMIN duplicate/merge resolution; never overwrite either receipt or reassign child rows automatically.
- [ ] Create `tbl_receipts` with canonical queryable header columns (Store, Date, Time, TC#/Receipt#, Subtotal, Tax, Total, Payment Method), upload FK/page reference, import/review state, OCR provider/schema version, immutable full original OCR response as PostgreSQL JSONB (`raw_ocr_document`), versioned canonical receipt JSONB (`receipt_document`) containing accepted header plus line items/provenance/review state, reviewed_by/reviewed_at, and deleted_at (nullable, soft-delete).
- [ ] Create normalized `tbl_receipt_items` rows FK'd to `receipt_pk` as the canonical queryable line items, with Item Description, UPC, Qty, Weight, Unit Price, Line Total, merchandise Category, business disposition, OCR confidence, remembered-rule reference, and links to approved business records. Preserve unmodeled provider fields per line in a JSONB column (`raw_ocr_item`).
- [ ] Do not store the receipt image/PDF as a base64 string or large database blob. Store the original file in protected persistent file/object storage and retain its key, checksum, media type, size, and retention status in Postgres. The complete OCR document and extracted structured data remain in the database as JSONB plus normalized rows.
- [ ] Keep normalized header/item records authoritative for edits and business queries; update the canonical `receipt_document` snapshot transactionally with those rows, persist corrections/reviewer identity, and retain `raw_ocr_document` unchanged for audit and reprocessing.
- [ ] Alembic migration(s) for both tables with appropriate indexes (Store+Date for filtering, Receipt_ID for dedup lookups).

## Feature 2.2 — Read APIs
- [ ] Feature complete
- [ ] `GET /api/v1/receipts` — paginated list, filterable by store and date range (VIEWER+).
- [ ] `GET /api/v1/receipts/{receipt_pk}` — header + all line items (VIEWER+).
- [ ] `GET /api/v1/receipts/{receipt_pk}/items` — line items only (VIEWER+).
- [ ] All read/list/detail/search/export operations use the persisted normalized records and JSONB documents; they must never call the OCR provider.

## Feature 2.3 — Deletion & Audit
- [ ] Feature complete
- [ ] `DELETE /api/v1/receipts/{receipt_pk}` — soft delete only (sets `deleted_at`); no immediate hard-delete endpoint exists (ADMIN only). A separate audited purge service applies the configured retention policy; if no retention period is configured, no automatic purge occurs.
- [ ] Configure the approved retention periods from [the implementation-readiness gate](../02-implementation-readiness.md) separately for source files, raw OCR payloads, canonical receipt records, messaging content, and audit metadata. Purge is ADMIN-only, logged, honors legal/operational holds, and removes eligible data from primary storage; backup copies expire under the documented backup-retention schedule.
- [ ] Import audit log table capturing every upload attempt: timestamp, files submitted, existing count, new count, duplicates skipped, receipts added, errors — feeds the Governance/Testing release gate (Capability 9 & 10).

## Feature 2.4 — Web UI (Jinja2/HTMX)
- [ ] Feature complete
- [ ] The initial Receipt MVP UI must work without Square, the full Products/Recipes module, full inventory, tax, or WhatsApp capabilities being deployed; its minimal receipt-linked ingredient/recipe records are part of the receipt MVP itself.
- [ ] Render receipt details and corrected fields from the database snapshot; opening or refreshing a receipt must not incur another OCR API call.
- [ ] Receipts list page: server-rendered table with store/date-range filters, pagination via HTMX partial swaps (no full page reload).
- [ ] Receipt detail page: header summary + line items table, category badges.
- [ ] Upload page: drag-and-drop file input, HTMX polling against the Celery task status endpoint from Capability 1, live "existing / new / duplicates / added" result summary.
- [ ] Role-gated delete action (ADMIN only) with confirmation prompt.

## Feature 2.5 — OCR Review & Transaction Routing
- [ ] Feature complete
- [ ] OCR creates reviewable draft receipt/header/item data; it must not silently post uncertain or mismatched values into purchases, expenses, or ingredient costs.
- [ ] For every receipt line, let the reviewer choose one business disposition: Personal / Non-business; Ordinary Business Purchase; Recipe Ingredient; or Capital Asset / Equipment (CapEx). Keep this separate from the merchandise Category (Produce, Dairy, etc.); use both consistently in OCR review and manual receipt entry.
- [ ] For Ordinary Business Purchase lines, allow an additional reviewed choice between a stocked operating supply (for example, cups) and a direct expense; stocked supplies require quantity/unit and use Capability 4.8 inventory records.
- [ ] Recipe Ingredient classification must link the item to one or more existing recipes and its ingredient record; allow recipe search/multi-select and creation of a missing ingredient or recipe without losing the receipt review.
- [ ] Route Ordinary Business Purchase lines to either a stocked-supply record or a direct expense, never both; route Recipe Ingredient lines to ingredient purchase/cost records, Capital Asset / Equipment lines to asset tracking, and Personal / Non-business lines to no business ledger. Preserve receipt-to-record links and approval audit.
- [ ] Approve and post through the same domain services and validation rules used by manual entry (Capabilities 4 and 5); make approval idempotent so retries cannot create duplicate transactions.
- [ ] Support marking non-business lines or receipts as archive-only without forcing them into a purchase/expense record.
- [ ] If OCR is unavailable or incorrect, allow a MANAGER to enter receipt header and line-item fields manually or attach the source image and key the data; route these entries through the same review, purchase/expense, and audit services.

## Feature 2.6 — Remembered Item Classifications
- [ ] Feature complete
- [ ] Persist reviewer decisions in a reusable item-rule table, including normalized item signature, vendor, UPC when available, classification, ingredient, linked recipe IDs, asset category when applicable, last confirmation, and audit fields.
- [ ] Match future receipt lines first by vendor + UPC; when UPC is absent, use normalized vendor + item description. Reuse a previously confirmed exact match as the default without making the user re-enter its classification or recipe links.
- [ ] Allow the reviewer to change the suggested classification or recipe links for an individual line; ask whether the change should update the saved rule. Do not auto-apply ambiguous description-only matches; show them as suggestions for confirmation.
- [ ] Keep Personal / Non-business decisions out of business purchases, expenses, ingredient costs, and capital assets; provide a way to review and correct remembered rules.
