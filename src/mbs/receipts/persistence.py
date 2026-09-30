from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from mbs.models import Receipt, ReceiptItem, ReceiptUpload
from mbs.receipts.ocr import ExtractedReceipt


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
) -> Receipt:
    receipt_document = _canonical_document(extracted)
    receipt = Receipt(
        receipt_id=extracted.receipt_id,
        store=extracted.store,
        receipt_date=extracted.receipt_date,
        receipt_time=extracted.receipt_time,
        transaction_number=extracted.transaction_number,
        subtotal=extracted.subtotal,
        tax=extracted.tax,
        total=extracted.total,
        payment_method=extracted.payment_method,
        upload_pk=upload.upload_pk if upload is not None else None,
        page_number=page_number,
        ocr_provider=extracted.ocr_metadata.provider,
        ocr_schema_version=extracted.ocr_metadata.schema_version,
        raw_ocr_document=extracted.raw_ocr_document,
        receipt_document=receipt_document,
    )
    session.add(receipt)
    session.flush()
    for item in extracted.items:
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
                raw_ocr_item=None,
            )
        )
    if upload is not None:
        upload.processing_status = "SUCCEEDED"
        upload.ocr_attempts += 1
        upload.ocr_provider = extracted.ocr_metadata.provider
        upload.ocr_schema_version = extracted.ocr_metadata.schema_version
        upload.page_count = extracted.ocr_metadata.page_count
    return receipt


def _canonical_document(extracted: ExtractedReceipt) -> dict[str, object]:
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
                "upc": item.upc,
                "quantity": _decimal_string(item.quantity),
                "weight_lb": _decimal_string(item.weight_lb),
                "unit_price": _decimal_string(item.unit_price),
                "line_total": _decimal_string(item.line_total),
                "category": item.category,
                "business_disposition": item.business_disposition.value,
            }
            for item in extracted.items
        ],
    }


def _decimal_string(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
