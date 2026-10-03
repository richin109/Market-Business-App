from __future__ import annotations

from collections.abc import Sequence
from datetime import date, time
from decimal import Decimal
from typing import Any

from mbs.domain.receipt_corrections import _receipt_id
from mbs.domain.receipt_documents import _decimal_string
from mbs.models import Receipt, ReceiptItem


def _apply_header(receipt: Receipt, values: dict[str, Any], receipt_id: str) -> None:
    receipt.store = values["store"]
    receipt.receipt_date = values["receipt_date"]
    receipt.receipt_time = values["receipt_time"]
    receipt.transaction_number = values["transaction_number"]
    receipt.subtotal = values["subtotal"]
    receipt.tax = values["tax"]
    receipt.total = values["total"]
    receipt.payment_method = values["payment_method"]
    receipt.receipt_id = receipt_id


def _proposed_values(receipt: Receipt, updates: dict[str, Any]) -> dict[str, Any]:
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


def _document(
    values: dict[str, Any],
    items: Sequence[ReceiptItem],
    item_updates: dict[int, dict[str, Any]],
    excluded_ids: set[int] | None = None,
    item_additions: Sequence[dict[str, Any]] = (),
    exclusion_reason: str | None = None,
) -> dict[str, object]:
    excluded_ids = excluded_ids or set()
    item_documents = []
    for index, item in enumerate(items):
        item_fields = (
            "description",
            "upc",
            "quantity",
            "weight_lb",
            "package_count",
            "pack_size",
            "pack_unit",
            "unit_price",
            "line_total",
            "category",
            "business_disposition",
            "disposition_subtype",
            "source_id",
            "source_page",
            "source_line_number",
        )
        item_values = {field: getattr(item, field) for field in item_fields}
        item_values.update(item_updates.get(index, {}))
        item_values["is_excluded"] = item.is_excluded or item.id in excluded_ids
        item_values["exclusion_reason"] = (
            exclusion_reason if item.id in excluded_ids else item.exclusion_reason
        )
        item_documents.append(
            {
                field: _decimal_string(value) if isinstance(value, Decimal) else value
                for field, value in item_values.items()
            }
        )
    item_documents.extend(
        {
            field: _decimal_string(value) if isinstance(value, Decimal) else value
            for field, value in {
                **{
                    field: value
                    for field, value in addition.items()
                    if field
                    not in {
                        "confirm_repeated_occurrence",
                        "remember_package_as_default",
                    }
                },
                "quantity": None,
                "weight_lb": None,
                "business_disposition": "UNCLASSIFIED",
                "disposition_subtype": "NONE",
                "is_excluded": False,
                "exclusion_reason": None,
            }.items()
        }
        for addition in item_additions
    )
    line_subtotal = sum(
        (
            Decimal(str(item_document["line_total"]))
            for item_document in item_documents
            if item_document["line_total"] is not None and not item_document["is_excluded"]
        ),
        Decimal("0"),
    )
    expected_subtotal = values["subtotal"]
    if expected_subtotal is None:
        expected_subtotal = values["total"] - (values["tax"] or Decimal("0"))
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
        "total_mismatch": (
            line_subtotal.quantize(Decimal("0.01")) != expected_subtotal.quantize(Decimal("0.01"))
        ),
        "items": item_documents,
    }
