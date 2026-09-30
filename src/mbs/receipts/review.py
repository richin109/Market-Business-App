from __future__ import annotations

from dataclasses import replace

from mbs.receipts.ocr import BusinessDisposition, ExtractedReceipt


def assign_business_disposition(
    receipt: ExtractedReceipt,
    item_index: int,
    disposition: BusinessDisposition,
) -> ExtractedReceipt:
    if not 0 <= item_index < len(receipt.items):
        raise IndexError(f"Receipt item index out of range: {item_index}")

    reviewed_item = replace(receipt.items[item_index], business_disposition=disposition)
    reviewed_items = (*receipt.items[:item_index], reviewed_item, *receipt.items[item_index + 1 :])
    return replace(receipt, items=reviewed_items)
