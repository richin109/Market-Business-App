from decimal import Decimal
from typing import Any

import pytest

from mbs.receipts.ocr import BusinessDisposition, normalize_receipt


def test_normalize_mocked_receipt_preserves_raw_dates_and_classifies_items() -> None:
    document: dict[str, Any] = {
        "receipt": {
            "store": "Synthetic Market",
            "date": "2026-09-30",
            "time": "14:05:06",
            "transaction_number": "TC-42",
            "subtotal": "5.00",
            "tax": "0.35",
            "total": "5.35",
            "payment_method": "CARD",
        },
        "items": [
            {"description": "Milk", "line_total": "2.90", "quantity": "1"},
            {"description": "Mystery item", "line_total": "2.10"},
        ],
    }
    receipt = normalize_receipt(document)
    document["receipt"]["store"] = "Changed after OCR"

    assert receipt.receipt_id == "Synthetic Market|2026-09-30|14:05:06|TC-42"
    assert receipt.raw_ocr_document["receipt"]["store"] == "Synthetic Market"
    assert receipt.raw_date == "2026-09-30"
    assert receipt.raw_time == "14:05:06"
    assert receipt.items[0].category == "Dairy"
    assert receipt.items[1].category == "Other"
    assert receipt.items[0].business_disposition is BusinessDisposition.UNCLASSIFIED
    assert receipt.total == Decimal("5.35")
    assert receipt.total_mismatch is False


def test_normalize_receipt_flags_line_total_mismatch() -> None:
    receipt = normalize_receipt(
        {
            "receipt": {
                "store": "Synthetic Market",
                "date": "2026-09-30",
                "time": "14:05:06",
                "transaction_number": "TC-43",
                "total": "5.00",
            },
            "items": [{"description": "Milk", "line_total": "4.99"}],
        }
    )

    assert receipt.total_mismatch is True


def test_normalize_receipt_reconciles_lines_to_subtotal_separately_from_tax() -> None:
    receipt = normalize_receipt(
        {
            "receipt": {
                "store": "Synthetic Market",
                "date": "2026-09-30",
                "time": "14:05:06",
                "transaction_number": "TC-44",
                "subtotal": "5.00",
                "tax": "0.35",
                "total": "5.35",
            },
            "items": [{"description": "Milk", "line_total": "5.00"}],
        }
    )

    assert receipt.total_mismatch is False


def test_normalize_receipt_captures_ocr_metadata() -> None:
    receipt = normalize_receipt(
        {
            "metadata": {
                "provider": "mock-document-ai",
                "schema_version": "expense-v1",
                "confidence": "0.97",
                "page_count": 2,
            },
            "receipt": {
                "store": "Synthetic Market",
                "date": "2026-09-30",
                "time": "14:05:06",
                "transaction_number": "TC-45",
                "total": "1.00",
            },
            "items": [{"description": "Milk", "line_total": "1.00"}],
        }
    )

    assert receipt.ocr_metadata.provider == "mock-document-ai"
    assert receipt.ocr_metadata.schema_version == "expense-v1"
    assert receipt.ocr_metadata.confidence == Decimal("0.97")
    assert receipt.ocr_metadata.page_count == 2


def test_blank_store_product_id_is_unmapped_without_changing_raw_evidence() -> None:
    document: dict[str, Any] = {
        "receipt": {
            "store": "Synthetic Market",
            "date": "2026-09-30",
            "time": "14:05:06",
            "transaction_number": "TC-46",
            "total": "1.00",
        },
        "items": [
            {
                "description": "Milk",
                "line_total": "1.00",
                "store_product_id": "  ",
            }
        ],
    }

    receipt = normalize_receipt(document)

    assert receipt.items[0].store_product_id is None
    assert receipt.items[0].raw_ocr_item == document["items"][0]
    assert receipt.raw_ocr_document["items"][0]["store_product_id"] == "  "


def test_normalize_receipt_rejects_non_iso_dates() -> None:
    with pytest.raises(ValueError):
        normalize_receipt(
            {
                "receipt": {
                    "store": "Synthetic Market",
                    "date": "09/30/2026",
                    "time": "14:05:06",
                    "transaction_number": "TC-44",
                    "total": "1.00",
                }
            }
        )
