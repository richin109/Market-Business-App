from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs.models import Receipt, ReceiptCorrectionHold, ReceiptItem
from mbs.receipts.persistence import _decimal_string


class CorrectionStatus(StrEnum):
    UPDATED = "UPDATED"
    HELD_FOR_ADMIN = "HELD_FOR_ADMIN"


class ReceiptIdCollision(ValueError):
    pass


@dataclass(frozen=True)
class CorrectionResult:
    status: CorrectionStatus
    receipt: Receipt
    hold: ReceiptCorrectionHold | None = None


def review_receipt(
    session: Session,
    receipt_pk: str,
    reviewer_id: int,
    header_updates: dict[str, Any] | None = None,
    item_updates: dict[int, dict[str, Any]] | None = None,
) -> CorrectionResult:
    receipt = session.scalar(
        select(Receipt).where(Receipt.receipt_pk == receipt_pk, Receipt.deleted_at.is_(None))
    )
    if receipt is None:
        raise ValueError("Receipt not found")
    items = session.scalars(
        select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt_pk).order_by(ReceiptItem.id)
    ).all()
    proposed = _proposed_values(receipt, header_updates or {})
    proposed_receipt_id = _receipt_id(
        proposed["store"],
        proposed["receipt_date"],
        proposed["receipt_time"],
        proposed["transaction_number"],
    )
    collision = session.scalar(
        select(Receipt).where(
            Receipt.receipt_id == proposed_receipt_id,
            Receipt.receipt_pk != receipt_pk,
        )
    )
    if collision is not None:
        hold = ReceiptCorrectionHold(
            receipt_pk=receipt_pk,
            proposed_receipt_id=proposed_receipt_id,
            proposed_document=_document(proposed, items, item_updates or {}),
            reviewer_id=reviewer_id,
        )
        session.add(hold)
        session.flush()
        return CorrectionResult(CorrectionStatus.HELD_FOR_ADMIN, receipt, hold)

    receipt.store = proposed["store"]
    receipt.receipt_date = proposed["receipt_date"]
    receipt.receipt_time = proposed["receipt_time"]
    receipt.transaction_number = proposed["transaction_number"]
    receipt.subtotal = proposed["subtotal"]
    receipt.tax = proposed["tax"]
    receipt.total = proposed["total"]
    receipt.payment_method = proposed["payment_method"]
    for index, updates in (item_updates or {}).items():
        if not 0 <= index < len(items):
            raise IndexError(f"Receipt item index out of range: {index}")
        for field, value in updates.items():
            if field not in {
                "description",
                "upc",
                "quantity",
                "weight_lb",
                "unit_price",
                "line_total",
                "category",
                "business_disposition",
            }:
                raise ValueError(f"Unsupported receipt item field: {field}")
            setattr(items[index], field, value)
    receipt.receipt_id = proposed_receipt_id
    receipt.reviewed_by = reviewer_id
    receipt.reviewed_at = datetime.now(UTC)
    receipt.receipt_document = _document(proposed, items, {})
    session.flush()
    return CorrectionResult(CorrectionStatus.UPDATED, receipt)


def _proposed_values(
    receipt: Receipt, updates: dict[str, Any]
) -> dict[str, Any]:
    values = {
        "store": receipt.store,
        "receipt_date": receipt.receipt_date,
        "receipt_time": receipt.receipt_time,
        "transaction_number": receipt.transaction_number,
        "subtotal": receipt.subtotal,
        "tax": receipt.tax,
        "total": receipt.total,
        "payment_method": receipt.payment_method,
    }
    for field, value in updates.items():
        if field not in values:
            raise ValueError(f"Unsupported receipt header field: {field}")
        if field == "receipt_date" and isinstance(value, str):
            value = date.fromisoformat(value)
        if field == "receipt_time" and isinstance(value, str):
            value = time.fromisoformat(value)
        if field in {"subtotal", "tax", "total"} and value is not None:
            value = Decimal(str(value))
        values[field] = value
    return values


def _receipt_id(store: str, receipt_date: date, receipt_time: time, transaction_number: str) -> str:
    return f"{store}|{receipt_date.isoformat()}|{receipt_time.isoformat()}|{transaction_number}"


def _document(
    values: dict[str, Any], items: Sequence[ReceiptItem], item_updates: dict[int, dict[str, Any]]
) -> dict[str, object]:
    item_documents = []
    for index, item in enumerate(items):
        item_fields = (
            "description",
            "upc",
            "quantity",
            "weight_lb",
            "unit_price",
            "line_total",
            "category",
            "business_disposition",
        )
        item_values = {field: getattr(item, field) for field in item_fields}
        item_values.update(item_updates.get(index, {}))
        item_documents.append(
            {
                field: _decimal_string(value) if isinstance(value, Decimal) else value
                for field, value in item_values.items()
            }
        )
    return {
        "receipt_id": _receipt_id(
            values["store"],
            values["receipt_date"],
            values["receipt_time"],
            values["transaction_number"],
        ),
        "store": values["store"],
        "date": values["receipt_date"].isoformat(),
        "time": values["receipt_time"].isoformat(),
        "transaction_number": values["transaction_number"],
        "subtotal": _decimal_string(values["subtotal"]),
        "tax": _decimal_string(values["tax"]),
        "total": _decimal_string(values["total"]),
        "payment_method": values["payment_method"],
        "items": item_documents,
    }
