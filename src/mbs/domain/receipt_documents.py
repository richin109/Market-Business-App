from __future__ import annotations

from decimal import Decimal

from mbs.domain.receipt_normalization import ExtractedReceipt


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
