from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from mbs.items import item_id_for_date, register_store_item
from mbs.models import AuditLog, Receipt, ReceiptItem, ReceiptSource, ReceiptUpload
from mbs.receipts.ocr import ExtractedReceipt
from mbs.stores import resolve_store


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
    session.add(upload)
    session.flush()
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
    session.add(receipt)
    session.flush()
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
        session.add(source)
        session.flush()
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
        session.add(
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
            )
        )
    if upload is not None:
        upload.processing_status = "SUCCEEDED"
        if increment_ocr_attempts:
            upload.ocr_attempts += 1
        upload.ocr_provider = extracted.ocr_metadata.provider
        upload.ocr_schema_version = extracted.ocr_metadata.schema_version
        if extracted.ocr_metadata.page_count is not None:
            upload.page_count = extracted.ocr_metadata.page_count
    session.add(
        AuditLog(
            event_type="RECEIPT_IMPORTED",
            actor=str(upload.uploaded_by) if upload is not None and upload.uploaded_by else None,
            entity_type="Receipt",
            entity_id=receipt.receipt_pk,
            details=(
                f"receipt_id={receipt.receipt_id}; lines={len(extracted.items)}; "
                f"upload_pk={upload.upload_pk if upload is not None else None}"
            ),
        )
    )
    return receipt


def _canonical_document(
    extracted: ExtractedReceipt,
    source_id: int | None = None,
    source_page: int | None = None,
) -> dict[str, object]:
    return {
        "receipt_id": extracted.receipt_id,
        "store": extracted.store,
        "date": extracted.receipt_date.isoformat(),
        "time": extracted.receipt_time.isoformat(),
        "transaction_number": extracted.transaction_number,
        "subtotal": _decimal_string(extracted.subtotal),
        "tax": _decimal_string(extracted.tax),
        "total": _decimal_string(extracted.total),
        "payment_method": extracted.payment_method,
        "total_mismatch": extracted.total_mismatch,
        "items": [
            {
                "description": item.description,
                "store_product_id": item.store_product_id,
                "upc": item.upc,
                "quantity": _decimal_string(item.quantity),
                "weight_lb": _decimal_string(item.weight_lb),
                "unit_price": _decimal_string(item.unit_price),
                "line_total": _decimal_string(item.line_total),
                "category": item.category,
                "business_disposition": item.business_disposition.value,
                "disposition_subtype": "NONE",
                **(
                    {
                        "source_id": source_id,
                        "source_page": _positive_position(
                            (item.raw_ocr_item or {}).get("source_page")
                            or (item.raw_ocr_item or {}).get("page_number"),
                            source_page,
                        ),
                        "source_line_number": _positive_position(
                            (item.raw_ocr_item or {}).get("source_line_number")
                            or (item.raw_ocr_item or {}).get("line_number"),
                            line_number,
                        ),
                    }
                    if source_id is not None and source_page is not None
                    else {}
                ),
            }
            for line_number, item in enumerate(extracted.items, start=1)
        ],
    }


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
    session.add(source)
    session.flush()
    source.extracted_document = _canonical_document(extracted, source_id=source.id, source_page=1)
    upload.processing_status = "REVIEW"
    upload.duplicate_status = "SOURCE_ASSOCIATION_REVIEW"
    upload.processing_lease_token = None
    upload.processing_lease_until = None
    upload.ocr_provider = extracted.ocr_metadata.provider
    upload.ocr_schema_version = extracted.ocr_metadata.schema_version
    if extracted.ocr_metadata.page_count is not None:
        upload.page_count = extracted.ocr_metadata.page_count
    session.add(
        AuditLog(
            event_type="RECEIPT_SOURCE_MATCH_HELD",
            actor=str(upload.uploaded_by) if upload.uploaded_by is not None else None,
            entity_type="ReceiptSource",
            entity_id=str(source.id),
            details=f"receipt_pk={matched_receipt.receipt_pk}; receipt_id={extracted.receipt_id}",
        )
    )
    return source


def _positive_position(value: object, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError("Source page and line positions must be positive integers")
    if isinstance(value, int):
        position = value
    elif isinstance(value, str):
        try:
            position = int(value)
        except ValueError as error:
            raise ValueError("Source page and line positions must be positive integers") from error
    else:
        raise ValueError("Source page and line positions must be positive integers")
    if position < 1:
        raise ValueError("Source page and line positions must be positive integers")
    return position


def _decimal_string(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
