from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from mbs.domain.receipt_text_values import _normalize_date, _normalize_time

_WALMART_ITEM_ID = re.compile(r"\b(\d{8,14})\b")

_WALMART_MERCHANT_ITEM_ID = re.compile(
    r"\b(?:ITEM\s*(?:NO\.?|NUMBER|#)|SKU)\s*[:#]?\s*([A-Z0-9-]{3,32})\b",
    re.IGNORECASE,
)

_WALMART_EXPLICIT_UPC = re.compile(
    r"\b(?:UPC|EAN|GTIN)\s*[:#]?\s*(\d{8,14})\b",
    re.IGNORECASE,
)


def _parse_walmart_header(text: str) -> tuple[dict[str, Any], list[str]]:
    stamps = re.findall(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s+(\d{1,2}:\d{2}(?::\d{2})?)", text)
    dates = {_normalize_date(date_text) for date_text, _ in stamps} - {None}
    times = {_normalize_time(time_text) for _, time_text in stamps} - {None}
    issues = ["VENDOR_REFERENCE_REQUIRES_REVIEW"]
    if len(times) > 1:
        issues.append("AMBIGUOUS_PRINTED_TIMESTAMPS")
    references = {
        label: match[1]
        for label, pattern in (
            ("store_number", r"\bST\s*#\s*([A-Z0-9-]+)"),
            ("operator_number", r"\bOP\s*#\s*([A-Z0-9-]+)"),
            ("terminal_number", r"\bTE\s*#\s*([A-Z0-9-]+)"),
            ("transaction_reference", r"\bTR\s*#\s*([A-Z0-9-]+)"),
            ("printed_reference", r"\bREF\s*#\s*([A-Z0-9-]+)"),
        )
        if (match := re.search(pattern, text, re.IGNORECASE)) is not None
    }
    tax_values = [
        Decimal(value.replace(",", ""))
        for value in re.findall(
            r"(?im)^\s*TAX\s*\d?(?:\s+\d+(?:\.\d+)?\s*%)?\s+\$?([\d,]+\.\d{2})\b", text
        )
    ]
    card = re.search(
        r"\b(?:VISA|MASTERCARD|DISCOVER|AMEX)\b[^\n]*?(?:X{2,}|\*{2,})\s*(\d{4})\b",
        text,
        re.IGNORECASE,
    )
    return (
        {
            "date": next(iter(dates)) if len(dates) == 1 else None,
            "time": next(iter(times)) if len(times) == 1 else None,
            "tax": str(sum(tax_values, Decimal("0.00"))) if tax_values else None,
            "card_last_four": card[1] if card else None,
            "reference_candidates": references,
        },
        issues,
    )


def _parse_walmart_items(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    lines = text.splitlines()
    end = next(
        (index for index, line in enumerate(lines) if re.match(r"\s*SUBTOTAL\b", line, re.I)),
        len(lines),
    )
    body = lines[:end]
    starts = [
        index
        for index, line in enumerate(body)
        if (_WALMART_ITEM_ID.search(line) or _WALMART_MERCHANT_ITEM_ID.search(line))
        and re.search(r"[A-Za-z]{3,}", line)
    ]
    items: list[dict[str, Any]] = []
    issues: list[str] = []
    for occurrence, start in enumerate(starts):
        stop = starts[occurrence + 1] if occurrence + 1 < len(starts) else end
        block = "\n".join(body[start:stop])
        row = body[start]
        identifier = _WALMART_ITEM_ID.search(row)
        merchant_identifier = _WALMART_MERCHANT_ITEM_ID.search(row)
        explicit_upc = _WALMART_EXPLICIT_UPC.search(row)
        if identifier is None and merchant_identifier is None:
            continue
        if merchant_identifier is not None:
            identifier_candidate = merchant_identifier[1]
        elif identifier is not None:
            identifier_candidate = identifier[1]
        else:
            continue
        stripped = row
        if merchant_identifier is not None:
            stripped = _WALMART_MERCHANT_ITEM_ID.sub(" ", stripped, count=1)
        if explicit_upc is not None:
            stripped = _WALMART_EXPLICIT_UPC.sub(" ", stripped, count=1)
        elif identifier is not None and merchant_identifier is None:
            stripped = _WALMART_ITEM_ID.sub(" ", stripped, count=1)
        description = re.sub(r"\s+", " ", re.sub(r"\bF\b", " ", stripped))
        money = re.findall(r"\$?([\d,]+\.\d{2})\b", block)
        quantity = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:AT|@)\s*\d+(?:\.\d+)?\s+FOR\b", block, re.I)
        weight = re.search(r"\b(\d+(?:\.\d+)?)\s*LB\b", block, re.I)
        size = re.search(r"\b(\d+(?:\.\d+)?\s*(?:OZ|LB|CT))\b", body[start], re.I)
        if len(money) > 1:
            issues.append(f"AMBIGUOUS_ITEM_AMOUNTS:{occurrence + 1}")
        items.append(
            {
                "description": description.strip(" *-:") or None,
                "store_product_id": (
                    merchant_identifier[1] if merchant_identifier is not None else None
                ),
                "upc": (
                    explicit_upc[1]
                    if explicit_upc is not None
                    else (
                        identifier[1]
                        if merchant_identifier is None
                        and identifier is not None
                        and len(identifier[1]) in {12, 13, 14}
                        else None
                    )
                ),
                "identifier_candidate": identifier_candidate,
                "quantity": quantity[1] if quantity else None,
                "weight_lb": weight[1] if weight else None,
                "unit_price": None,
                "line_total": money[-1].replace(",", "") if len(money) == 1 else None,
                "printed_size": size[1] if size else None,
                "raw_line_text": block.strip(),
            }
        )
    if not items:
        issues.append("NO_WALMART_ITEM_ROWS_PARSED")
    return items, issues
