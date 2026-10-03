from __future__ import annotations

import re
from typing import Any

from mbs.domain.receipt_text_values import _MONEY, _label_amount, _normalize_date


def _parse_amazon_items(text: str) -> list[dict[str, Any]]:
    starts = [match.start() for match in re.finditer(r"(?im)^\s*Delivered\b", text)]
    items: list[dict[str, Any]] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        block = text[start:end]
        block_lines = [line.strip() for line in block.splitlines() if line.strip()]
        delivered_line = block_lines[0] if block_lines else ""
        delivery_match = re.search(
            r"\bDelivered\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})", delivered_line, re.I
        )
        delivery_date = _normalize_date(delivery_match[1]) if delivery_match else None
        size_match = re.search(r"\bSize\s*:\s*([^\n]+)", block, re.I)
        seller_match = re.search(r"\bSold\s+by\s*:\s*([^\n]+)", block, re.I)
        supplier_match = re.search(r"\bSupplied\s+by\s*:\s*([^\n]+)", block, re.I)
        item_number_match = re.search(
            r"\b(?:ASIN|Item\s*(?:No\.?|#)|Product\s*ID)\s*:?\s*([A-Z0-9-]{6,20})",
            block,
            re.I,
        )
        upc_match = re.search(r"\b(?:UPC|EAN|GTIN)\s*:?\s*(\d{8,14})\b", block, re.I)
        quantity_match = re.search(r"\b(?:Qty|Quantity)\s*:?\s*(\d+)\b", block, re.I)
        return_match = re.search(r"\b(Return[^\n]*)", block, re.I)

        title_lines: list[str] = []
        for line in block_lines[1:]:
            if re.search(
                r"\b(?:Size|Sold by|Supplied by|Return|ASIN|Item\s*#|UPC|EAN|GTIN)\b",
                line,
                re.I,
            ):
                break
            if _MONEY.search(line) or _is_amazon_metadata_line(line):
                continue
            title_lines.append(line)
        description = " ".join(title_lines).strip() or None
        prices = _MONEY.findall(block)
        unique_prices = list(dict.fromkeys(value.replace(",", "") for value in prices))
        line_total = unique_prices[0] if len(unique_prices) == 1 else None
        quantity = quantity_match[1] if quantity_match else None
        items.append(
            {
                "description": description,
                "store_product_id": item_number_match[1] if item_number_match else None,
                "upc": upc_match[1] if upc_match else None,
                "quantity": quantity,
                "weight_lb": None,
                "unit_price": None,
                "line_total": line_total,
                "printed_size": size_match[1].strip() if size_match else None,
                "delivery_date": delivery_date,
                "sold_by": seller_match[1].strip() if seller_match else None,
                "supplied_by": supplier_match[1].strip() if supplier_match else None,
                "return_status": return_match[1].strip() if return_match else None,
                "raw_line_text": block.strip(),
            }
        )
    return items


def _is_amazon_metadata_line(line: str) -> bool:
    return any(
        phrase in line.casefold()
        for phrase in (
            "order summary",
            "item subtotal",
            "shipping & handling",
            "sold by",
            "supplied by",
            "return",
            "quantity",
            "ship to",
            "payment method",
        )
    )


def _amazon_total(text: str) -> str | None:
    for pattern in (r"order\s+total", r"total\s+after\s+tax", r"grand\s+total"):
        value = _label_amount(text, pattern)
        if value is not None:
            return value
    return None
