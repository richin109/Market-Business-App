from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from mbs.domain.pdf_extraction import PDFTextExtraction, merge_field_candidates

_MONEY = re.compile(r"\$?\s*([\d,]+\.\d{2})")

_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y")


def _label_amount(text: str, label_pattern: str) -> str | None:
    pattern = re.compile(
        rf"^\s*{label_pattern}\b[^\n]*?{_MONEY.pattern}", re.IGNORECASE | re.MULTILINE
    )
    match = pattern.search(text)
    return match[1].replace(",", "") if match else None


def _summary_amounts(text: str) -> list[str] | None:
    match = re.search(r"((?:^\$[\d,]+\.\d{2}\n){4,5})Order Summary", text, re.M)
    if match is None:
        return None
    values = [amount.replace(",", "") for amount in re.findall(_MONEY, match[1])]
    if len(values) < 4:
        return None
    cents = [int(Decimal(value) * 100) for value in values]
    if sum(cents[:-1]) != cents[-1]:
        return None
    return values


def _normalize_date(value: str) -> str | None:
    for date_format in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%B %d %Y",
        "%b %d %Y",
    ):
        try:
            return datetime.strptime(value, date_format).date().isoformat()
        except ValueError:
            continue
    return None


def _normalize_time(value: str) -> str | None:
    cleaned = value.strip().upper()
    for time_format in ("%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p"):
        try:
            return datetime.strptime(cleaned, time_format).time().isoformat()
        except ValueError:
            continue
    return None


def _payment_method(text: str) -> str | None:
    patterns = (
        (r"\b(Visa|Mastercard|American Express|Discover)\b", "CARD"),
        (r"\bCash\b", "CASH"),
    )
    for pattern, result in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return result
    return None


def _confidence(
    value: Any,
    extraction: PDFTextExtraction,
    source_hint: str | None = None,
) -> Decimal:
    if value is None or value == "" or value == []:
        return Decimal("0")
    candidates = []
    for page in extraction.pages:
        if source_hint == "OCR" and page.ocr_confidence is not None:
            candidates.append(page.ocr_confidence)
        else:
            candidates.append(page.native_confidence)
    return min(candidates, default=Decimal("0"))


def _overall_confidence(fields: dict[str, Decimal]) -> Decimal:
    values = [value for key, value in fields.items() if key != "payment_method" and value > 0]
    return sum(values, Decimal("0")) / Decimal(len(values)) if values else Decimal("0")


def _field_source(
    field: str,
    extraction: PDFTextExtraction,
    source_hint: str | None = None,
) -> str:
    if source_hint is not None:
        return source_hint
    if field == "items" and any(page.selected_source == "OCR" for page in extraction.pages):
        return "OCR"
    return extraction.method.value


def _same_item_occurrences(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
    return all(
        (a.get("store_product_id"), a.get("description"))
        == (b.get("store_product_id"), b.get("description"))
        for a, b in zip(left, right, strict=True)
    )


def _merge_item(
    native: dict[str, Any],
    ocr: dict[str, Any],
    native_confidence: dict[str, Decimal],
    ocr_confidence: dict[str, Decimal],
) -> tuple[dict[str, Any], dict[str, str]]:
    return merge_field_candidates(native, native_confidence, ocr, ocr_confidence)
