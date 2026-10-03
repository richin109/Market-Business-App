from __future__ import annotations

from sqlalchemy.orm import Session

from mbs.domain.receipt_documents import _canonical_document, _positive_position
from mbs.items import item_id_for_date, register_store_item
from mbs.models import AuditLog, Receipt, ReceiptItem, ReceiptSource, ReceiptUpload
from mbs.receipts.ocr import ExtractedReceipt
from mbs.repositories.receipts import ReceiptRepository
from mbs.stores import resolve_store

repository = ReceiptRepository()


def create_upload(
    session: Session,
    source_sha256: str,
    file_key: str,
    media_type: str,
    size_bytes: int,
    uploaded_by: int | None = None,
) -> ReceiptUpload:
    upload = ReceiptUpload(
        source_sha256=source_sha256,
        file_key=file_key,
        media_type=media_type,
        size_bytes=size_bytes,
        uploaded_by=uploaded_by,
        processing_status="QUEUED",
    )
    repository.add(session, upload)
    repository.flush(session)
    return upload


def persist_extracted_receipt(
    session: Session,
    extracted: ExtractedReceipt,
    upload: ReceiptUpload | None = None,
    page_number: int | None = None,
    increment_ocr_attempts: bool = True,
) -> Receipt:
    receipt_document = _canonical_document(extracted)
    store, store_alias_key = resolve_store(session, extracted.store, extracted.raw_ocr_document)
    receipt = Receipt(
        receipt_id=extracted.receipt_id,
        store_id=store.store_id,
        store_alias_key=store_alias_key,
        store=extracted.store,
        receipt_date=extracted.receipt_date,
        receipt_time=extracted.receipt_time,
        transaction_number=extracted.transaction_number,
        source_type="OCR",
        subtotal=extracted.subtotal,
        tax=extracted.tax,
        total=extracted.total,
        payment_method=extracted.payment_method,
        upload_pk=upload.upload_pk if upload is not None else None,
        page_number=page_number if page_number is not None else (1 if upload is not None else None),
        ocr_provider=extracted.ocr_metadata.provider,
        ocr_schema_version=extracted.ocr_metadata.schema_version,
        raw_ocr_document=extracted.raw_ocr_document,
        receipt_document=receipt_document,
    )
    repository.add(session, receipt)
    repository.flush(session)
    source = None
    if upload is not None:
        source = ReceiptSource(
            receipt_pk=receipt.receipt_pk,
            upload_pk=upload.upload_pk,
            source_sha256=upload.source_sha256,
            association_kind="PRIMARY",
            raw_ocr_document=extracted.raw_ocr_document,
            extracted_document=receipt_document,
        )
        repository.add(session, source)
        repository.flush(session)
        receipt_document = _canonical_document(
            extracted, source_id=source.id, source_page=receipt.page_number or 1
        )
        source.extracted_document = receipt_document
        receipt.receipt_document = receipt_document
    source_items = receipt_document.get("items", [])
    for line_number, item in enumerate(extracted.items, start=1):
        source_item: object = None
        if source is not None:
            if not isinstance(source_items, list) or len(source_items) < line_number:
                raise ValueError("Canonical source extraction has an invalid item list")
            source_item = source_items[line_number - 1]
        source_metadata: dict[str, object] | None = None
        if source is not None:
            if not isinstance(source_item, dict):
                raise ValueError("Canonical source extraction line is invalid")
            source_metadata = source_item
        store_item = (
            register_store_item(
                session,
                receipt.store_id,
                item.store_product_id,
                item.description,
                item.upc,
                effective_from=receipt.receipt_date,
            )
            if item.store_product_id is not None
            else None
        )
        repository.add(
            session,
            ReceiptItem(
                receipt_pk=receipt.receipt_pk,
                description=item.description,
                upc=item.upc,
                quantity=item.quantity,
                weight_lb=item.weight_lb,
                unit_price=item.unit_price,
                line_total=item.line_total,
                category=item.category,
                business_disposition=item.business_disposition.value,
                raw_ocr_item=item.raw_ocr_item,
                source_id=source.id if source is not None else None,
                source_page=(
                    _positive_position(source_metadata.get("source_page"), receipt.page_number or 1)
                    if source_metadata is not None
                    else None
                ),
                source_line_number=(
                    _positive_position(source_metadata.get("source_line_number"), line_number)
                    if source_metadata is not None
                    else None
                ),
                store_item_id=store_item.store_item_id if store_item is not None else None,
                item_id=(
                    item_id_for_date(session, store_item.store_item_id, receipt.receipt_date)
                    if store_item is not None
                    else None
                ),
            ),
        )
    if upload is not None:
        upload.processing_status = "SUCCEEDED"
        if increment_ocr_attempts:
            upload.ocr_attempts += 1
        upload.ocr_provider = extracted.ocr_metadata.provider
        upload.ocr_schema_version = extracted.ocr_metadata.schema_version
        if extracted.ocr_metadata.page_count is not None:
            upload.page_count = extracted.ocr_metadata.page_count
    repository.add(
        session,
        AuditLog(
            event_type="RECEIPT_IMPORTED",
            actor=str(upload.uploaded_by) if upload is not None and upload.uploaded_by else None,
            entity_type="Receipt",
            entity_id=receipt.receipt_pk,
            details=(
                f"receipt_id={receipt.receipt_id}; lines={len(extracted.items)}; "
                f"upload_pk={upload.upload_pk if upload is not None else None}"
            ),
        ),
    )
    return receipt


def persist_source_candidate(
    session: Session,
    extracted: ExtractedReceipt,
    upload: ReceiptUpload,
    matched_receipt: Receipt,
) -> ReceiptSource:
    source = ReceiptSource(
        receipt_pk=matched_receipt.receipt_pk,
        upload_pk=upload.upload_pk,
        source_sha256=upload.source_sha256,
        association_kind="PENDING",
        raw_ocr_document=extracted.raw_ocr_document,
        extracted_document=_canonical_document(extracted),
    )
    repository.add(session, source)
    repository.flush(session)
    source.extracted_document = _canonical_document(extracted, source_id=source.id, source_page=1)
    upload.processing_status = "REVIEW"
    upload.duplicate_status = "SOURCE_ASSOCIATION_REVIEW"
    upload.processing_lease_token = None
    upload.processing_lease_until = None
    upload.ocr_provider = extracted.ocr_metadata.provider
    upload.ocr_schema_version = extracted.ocr_metadata.schema_version
    if extracted.ocr_metadata.page_count is not None:
        upload.page_count = extracted.ocr_metadata.page_count
    repository.add(
        session,
        AuditLog(
            event_type="RECEIPT_SOURCE_MATCH_HELD",
            actor=str(upload.uploaded_by) if upload.uploaded_by is not None else None,
            entity_type="ReceiptSource",
            entity_id=str(source.id),
            details=f"receipt_pk={matched_receipt.receipt_pk}; receipt_id={extracted.receipt_id}",
        ),
    )
    return source
