import pytest

from mbs.receipts.ocr import BusinessDisposition, ExtractedReceipt, normalize_receipt
from mbs.receipts.review import assign_business_disposition


def _receipt() -> ExtractedReceipt:
    return normalize_receipt(
        {
            "receipt": {
                "store": "Synthetic Market",
                "date": "2026-09-30",
                "time": "14:05:06",
                "transaction_number": "TC-101",
                "total": "2.00",
            },
            "items": [
                {"description": "Milk", "line_total": "1.00"},
                {"description": "Bread", "line_total": "1.00"},
            ],
        }
    )


@pytest.mark.parametrize(
    "disposition",
    [
        BusinessDisposition.PERSONAL_NON_BUSINESS,
        BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
        BusinessDisposition.RECIPE_INGREDIENT,
        BusinessDisposition.CAPITAL_ASSET_EQUIPMENT,
    ],
)
def test_assign_business_disposition_updates_only_selected_item(
    disposition: BusinessDisposition,
) -> None:
    receipt = _receipt()

    reviewed = assign_business_disposition(receipt, 1, disposition)

    assert receipt.items[0].business_disposition is BusinessDisposition.UNCLASSIFIED
    assert receipt.items[1].business_disposition is BusinessDisposition.UNCLASSIFIED
    assert reviewed.items[0].business_disposition is BusinessDisposition.UNCLASSIFIED
    assert reviewed.items[1].business_disposition is disposition
    assert reviewed.receipt_id == receipt.receipt_id


def test_assign_business_disposition_rejects_invalid_item_index() -> None:
    with pytest.raises(IndexError):
        assign_business_disposition(_receipt(), 2, BusinessDisposition.RECIPE_INGREDIENT)
