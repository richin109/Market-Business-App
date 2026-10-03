from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlalchemy.orm import Session

from mbs.errors import NotFoundError
from mbs.models import Receipt, ReceiptItem, ReceiptSource, Store, StoreItem
from mbs.repositories.receipt_reads import ReceiptReadRepository

repository = ReceiptReadRepository()


def _receipt_response(
    receipt: Receipt,
    items: Sequence[ReceiptItem],
    store_items: dict[str, StoreItem],
    sources: Sequence[ReceiptSource] = (),
) -> dict[str, object]:
    return {
        "receipt_pk": receipt.receipt_pk,
        "receipt_id": receipt.receipt_id,
        "source_type": receipt.source_type,
        "store_id": receipt.store_id,
        "store": receipt.store,
        "purchase_date": receipt.receipt_date.isoformat(),
        "purchase_time": receipt.receipt_time.isoformat(),
        "transaction_number": receipt.transaction_number,
        "subtotal": str(receipt.subtotal) if receipt.subtotal is not None else None,
        "tax": str(receipt.tax) if receipt.tax is not None else None,
        "total": str(receipt.total),
        "payment_method": receipt.payment_method,
        "sources": [
            {
                "source_id": source.id,
                "source_sha256": source.source_sha256,
                "association_kind": source.association_kind,
                "confirmed_repeated_line_indexes": (source.confirmed_repeated_line_indexes or []),
            }
            for source in sources
        ],
        "items": [
            _item_response(
                item,
                store_items.get(item.store_item_id) if item.store_item_id is not None else None,
                receipt.source_type,
            )
            for item in items
        ],
    }


def _item_response(
    item: ReceiptItem,
    store_item: StoreItem | None = None,
    receipt_source_type: str = "OCR",
) -> dict[str, object]:
    return {
        "description": item.description,
        "upc": item.upc,
        "quantity": str(item.quantity) if item.quantity is not None else None,
        "weight_lb": str(item.weight_lb) if item.weight_lb is not None else None,
        "package_count": str(item.package_count) if item.package_count is not None else None,
        "pack_size": str(item.pack_size) if item.pack_size is not None else None,
        "pack_unit": item.pack_unit,
        "unit_price": str(item.unit_price) if item.unit_price is not None else None,
        "line_total": str(item.line_total),
        "category": item.category,
        "business_disposition": item.business_disposition,
        "disposition_subtype": item.disposition_subtype,
        "source_id": item.source_id,
        "source_page": item.source_page,
        "source_line_number": item.source_line_number,
        "is_excluded": item.is_excluded,
        "exclusion_reason": item.exclusion_reason,
        "store_product_id": store_item.store_product_id if store_item is not None else None,
        "identifier_source": (
            "MANUAL"
            if store_item is not None and store_item.identifier_source == "MANUAL"
            else "USER_ENTERED"
            if store_item is not None and receipt_source_type == "MANUAL"
            else "OCR"
            if store_item is not None
            else None
        ),
        "common_name": store_item.common_name if store_item is not None else None,
    }


def _store_items_for_lines(session: Session, items: Sequence[ReceiptItem]) -> dict[str, StoreItem]:
    store_item_ids = {item.store_item_id for item in items if item.store_item_id is not None}
    if not store_item_ids:
        return {}
    return {
        store_item.store_item_id: store_item
        for store_item in repository.store_items(session, store_item_ids)
    }


def _manual_item_responses(
    items: Sequence[ReceiptItem], store_items: dict[str, StoreItem]
) -> list[dict[str, str]]:
    responses: list[dict[str, str]] = []
    for item in items:
        if item.store_item_id is None:
            continue
        store_item = store_items.get(item.store_item_id)
        if store_item is None:
            continue
        responses.append(
            {
                "description": item.description,
                "store_product_id": store_item.store_product_id,
                "identifier_source": (
                    "MANUAL" if store_item.identifier_source == "MANUAL" else "USER_ENTERED"
                ),
            }
        )
    return responses


def list_receipt_responses(
    session: Session,
    store: str | None,
    store_id: str | None,
    date_from: date | None,
    date_to: date | None,
    page: int,
    page_size: int,
) -> list[dict[str, object]]:
    return [
        {
            "receipt_pk": receipt.receipt_pk,
            "receipt_id": receipt.receipt_id,
            "store": receipt.store,
            "store_id": receipt.store_id,
            "purchase_date": receipt.receipt_date.isoformat(),
            "item_count": count,
        }
        for receipt, count in repository.directory_rows(
            session, store, store_id, date_from, date_to, page, page_size
        )
    ]


def receipt_response(session: Session, receipt_pk: str) -> dict[str, object]:
    receipt = repository.get_receipt(session, receipt_pk, active_only=True)
    if receipt is None:
        raise NotFoundError("Receipt not found")
    lines = repository.lines(session, receipt_pk)
    return _receipt_response(
        receipt,
        lines,
        _store_items_for_lines(session, lines),
        repository.sources(session, receipt_pk),
    )


def receipt_items_response(session: Session, receipt_pk: str) -> list[dict[str, object]]:
    receipt = repository.get_receipt(session, receipt_pk, active_only=True)
    if receipt is None:
        raise NotFoundError("Receipt not found")
    lines = repository.lines(session, receipt_pk)
    store_items = _store_items_for_lines(session, lines)
    responses = []
    for line in lines:
        store_item = store_items.get(line.store_item_id) if line.store_item_id is not None else None
        responses.append(
            {
                **_item_response(line, store_item, receipt.source_type),
                "remembered_disposition": store_item.last_disposition if store_item else None,
                "remembered_disposition_subtype": store_item.last_disposition_subtype
                if store_item
                else None,
            }
        )
    return responses


def receipt_upload_status_response(session: Session, upload_pk: str) -> dict[str, object]:
    upload = repository.get_upload(session, upload_pk)
    if upload is None:
        raise NotFoundError("Receipt upload not found")

    extraction = upload.ocr_extraction_result or {}
    raw_results = extraction.get("order_results", [])
    order_results = (
        [
            {
                "order_index": result["order_index"],
                "status": result["status"],
                "receipt_pk": result.get("receipt_pk"),
                "issue_codes": result.get("issue_codes", []),
            }
            for result in raw_results
            if isinstance(result, dict)
            and isinstance(result.get("order_index"), int)
            and isinstance(result.get("status"), str)
        ]
        if isinstance(raw_results, list)
        else []
    )
    raw_summary = extraction.get("order_summary", {})
    order_summary = (
        {
            key: value
            for key, value in raw_summary.items()
            if key in {"added", "source_review", "held", "already_associated"}
            and isinstance(value, int)
        }
        if isinstance(raw_summary, dict)
        else {}
    )
    return {
        "upload_pk": upload.upload_pk,
        "status": upload.processing_status,
        "ocr_attempts": upload.ocr_attempts,
        "order_summary": order_summary,
        "orders": order_results,
    }


def manual_receipt_stores(session: Session) -> list[Store]:
    return repository.manual_stores(session)
