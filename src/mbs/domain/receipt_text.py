from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from mbs.domain.pdf_extraction import PDFExtractionMethod, PDFTextExtraction
from mbs.domain.receipt_amazon import _amazon_total, _parse_amazon_items
from mbs.domain.receipt_text_values import (
    _confidence,
    _field_source,
    _label_amount,
    _normalize_date,
    _normalize_time,
    _overall_confidence,
    _payment_method,
    _summary_amounts,
)
from mbs.domain.receipt_walmart import _parse_walmart_header, _parse_walmart_items

_ITEM_PRICE = re.compile(
    r"Qty\s*\(Weight\)\s*:\s*([\d.]*)\s+Qty\s+Total\s+Price\s*:\s*\$([\d,]+\.\d{2})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedReceiptText:
    document: dict[str, Any]
    field_confidence: dict[str, Decimal]
    field_sources: dict[str, str]
    missing_fields: tuple[str, ...]
    issues: tuple[str, ...]

    @property
    def review_required(self) -> bool:
        return bool(self.missing_fields or self.issues)


def parse_receipt_text(
    text: str,
    extraction: PDFTextExtraction,
    source_hint: str | None = None,
) -> ParsedReceiptText:
    raw_text = text
    folded = text.casefold()
    order_match = re.search(r"\bOrder\s*#\s*([A-Z0-9-]+)", text, re.IGNORECASE)
    if order_match is None:
        order_match = re.search(
            r"\b(?:Transaction|Receipt|Reference)\s*(?:No\.?|#)\s*([A-Z0-9-]+)",
            text,
            re.IGNORECASE,
        )
    date_match = re.search(
        r"\b(?:Order\s+Date|Purchase\s+Date|Date)\b\s*:?\s*"
        r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{1,2}-\d{1,2}-\d{4})",
        text,
        re.IGNORECASE,
    )
    if date_match is None:
        date_match = re.search(
            r"\bOrder\s+placed\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
            text,
            re.IGNORECASE,
        )
    date_value = _normalize_date(date_match[1]) if date_match else None
    time_match = re.search(
        r"\b(?:Time|Purchase\s+Time)\s*:?\s*(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?)",
        text,
        re.IGNORECASE,
    )
    time_value = _normalize_time(time_match[1]) if time_match else None

    subtotal = _label_amount(text, r"(?:item(?:s)?\s*\(\s*\d+\s*\)\s*)?sub\s*total")
    tax = _label_amount(text, r"(?:(?:estimated|sales)\s+)?tax")
    store = _merchant(folded, text)
    walmart_header: dict[str, Any] = {}
    walmart_issues: list[str] = []
    if store == "Walmart":
        walmart_header, walmart_issues = _parse_walmart_header(text)
        date_value = date_value or walmart_header["date"]
        time_value = time_value or walmart_header["time"]
    total = (
        _amazon_total(text)
        if store == "Amazon"
        else _label_amount(text, r"(?:order\s+)?total(?!\s+tax)")
    )
    summary_values = _summary_amounts(raw_text)
    if summary_values is not None:
        subtotal = subtotal or summary_values[0]
        tax = tax or summary_values[1]
        total = total or summary_values[-1]

    if store == "Walmart":
        tax = walmart_header["tax"] or tax
    payment_method = _payment_method(text)
    item_issues: list[str] = []
    if store == "Amazon":
        items = _parse_amazon_items(raw_text)
    elif store == "Walmart":
        items, item_issues = _parse_walmart_items(raw_text)
    else:
        items = _parse_items(raw_text)
    confidences = {
        "store": _confidence(store, extraction, source_hint),
        "date": _confidence(date_value, extraction, source_hint),
        "time": _confidence(time_value, extraction, source_hint),
        "transaction_number": _confidence(
            order_match[1] if order_match else None, extraction, source_hint
        ),
        "subtotal": _confidence(subtotal, extraction, source_hint),
        "tax": _confidence(tax, extraction, source_hint),
        "total": _confidence(total, extraction, source_hint),
        "payment_method": _confidence(payment_method, extraction, source_hint),
        "items": min(
            (_confidence(item["description"], extraction, source_hint) for item in items),
            default=Decimal("0"),
        ),
    }
    for field in (
        "description",
        "store_product_id",
        "quantity",
        "weight_lb",
        "printed_size",
        "upc",
        "unit_price",
        "line_total",
    ):
        confidences[field] = min(
            (_confidence(item.get(field), extraction, source_hint) for item in items),
            default=Decimal("0"),
        )
    missing = tuple(
        field
        for field, value in (
            ("store", store),
            ("date", date_value),
            ("time", time_value),
            ("transaction_number", order_match[1] if order_match else None),
            ("total", total),
            ("items", items),
        )
        if not value
    )
    issues = [*walmart_issues, *item_issues]
    incomplete_items = [
        index
        for index, item in enumerate(items)
        if not item.get("description") or not item.get("line_total")
    ]
    if incomplete_items:
        issues.append(
            "INCOMPLETE_LINE_ITEMS:" + ",".join(str(index + 1) for index in incomplete_items)
        )
    low_confidence_fields = tuple(
        field
        for field in ("store", "date", "transaction_number", "total", "items")
        if confidences[field] < Decimal("0.62")
    )
    if low_confidence_fields:
        issues.append("LOW_CONFIDENCE_FIELDS:" + ",".join(low_confidence_fields))
    if not items:
        issues.append("NO_LINE_ITEMS_PARSED")
    if extraction.method.value == "OCR_FALLBACK" and not extraction.selected_text.strip():
        issues.append("OCR_RETURNED_NO_TEXT")
    receipt: dict[str, Any] = {
        "store": store,
        "date": date_value,
        "time": time_value,
        "transaction_number": order_match[1] if order_match else None,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "payment_method": payment_method,
    }
    if store == "Walmart":
        receipt["card_last_four"] = walmart_header["card_last_four"]
        receipt["reference_candidates"] = walmart_header["reference_candidates"]
    document = {
        "receipt": receipt,
        "items": items,
        "metadata": {
            "provider": (
                "local-tesseract" if extraction.method.value != "NATIVE_TEXT" else "pymupdf"
            ),
            "schema_version": "receipt-pdf-v1",
            "confidence": str(_overall_confidence(confidences)),
            "page_count": len(extraction.pages),
        },
        "extraction": {
            "content_kind": extraction.classification.content_kind.value,
            "method": extraction.method.value,
            "field_candidates": {
                field: {
                    "native": receipt.get(field) if source_hint != "OCR" else None,
                    "ocr": receipt.get(field) if source_hint == "OCR" else None,
                    "selected": receipt.get(field),
                    "selected_source": _field_source(field, extraction, source_hint),
                    "confidence": str(confidences[field]),
                }
                for field in confidences
            },
            "item_candidates": {
                "native": items if source_hint != "OCR" else [],
                "ocr": items if source_hint == "OCR" else [],
            },
            "field_confidence": {key: str(value) for key, value in confidences.items()},
            "field_source": {
                field: _field_source(field, extraction, source_hint) for field in confidences
            },
            "missing_fields": list(missing),
            "issues": issues,
            "pages": [
                {
                    "page_number": page.page_number,
                    "native_text_chars": len(page.native_text.strip()),
                    "native_confidence": str(page.native_confidence),
                    "ocr_confidence": (
                        str(page.ocr_confidence) if page.ocr_confidence is not None else None
                    ),
                    "selected_source": page.selected_source,
                }
                for page in extraction.pages
            ],
        },
        "review_required": bool(missing or issues),
    }
    field_sources = {field: _field_source(field, extraction, source_hint) for field in confidences}
    return ParsedReceiptText(document, confidences, field_sources, missing, tuple(issues))


def _parse_items(text: str) -> list[dict[str, Any]]:
    matches = list(_ITEM_PRICE.finditer(text))
    items: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        segment = text[match.end() : end]
        description_match = re.search(r"\n([^\n]+)\nItem:\s*([A-Z0-9-]+)", segment, re.I)
        if description_match is None:
            continue
        description = description_match[1].strip()
        item_number = description_match[2].strip()
        size_match = re.search(
            r"(?:^|\s)(\d+(?:\.\d+)?\s*(?:OZ|LB|PT|QT|GAL|CT))$", description, re.I
        )
        weight_text = match[1].strip()
        items.append(
            {
                "description": description,
                "store_product_id": item_number,
                "upc": None,
                "quantity": None,
                "weight_lb": weight_text or None,
                "unit_price": None,
                "line_total": match[2].replace(",", ""),
                "printed_size": size_match[1].strip() if size_match else None,
                "raw_line_text": segment.strip(),
            }
        )
    return items


def _merchant(text: str, source_text: str) -> str | None:
    merchants = (
        ("bj's wholesale club", "BJ's Wholesale Club"),
        ("walmart", "Walmart"),
        ("sam's club", "Sam's Club"),
        ("amazon", "Amazon"),
    )
    found = [display for token, display in merchants if token in text]
    if len(found) == 1:
        return found[0]
    return None


def _parse_completeness(parsed: ParsedReceiptText) -> int:
    receipt = parsed.document["receipt"]
    return sum(value is not None for value in receipt.values()) + len(parsed.document["items"])


def _image_text_extraction(text: str, confidence: Decimal) -> PDFTextExtraction:
    from mbs.domain.pdf_extraction import (
        ExtractedPDFPage,
        PDFClassification,
        PDFContentKind,
    )

    classification = PDFClassification(
        PDFContentKind.IMAGE_ONLY,
        False,
        True,
        True,
        True,
        (),
    )
    page = ExtractedPDFPage(1, "", Decimal("0"), text, confidence, text, "OCR")
    return PDFTextExtraction(classification, PDFExtractionMethod.OCR_FALLBACK, (page,))
