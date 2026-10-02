from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from mbs.receipts.pdf_extraction import (
    LocalTesseractReader,
    OCRPageReader,
    PDFExtractionMethod,
    PDFTextExtraction,
    extract_pdf_text,
    merge_field_candidates,
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


_MONEY = re.compile(r"\$?\s*([\d,]+\.\d{2})")
_ITEM_PRICE = re.compile(
    r"Qty\s*\(Weight\)\s*:\s*([\d.]*)\s+Qty\s+Total\s+Price\s*:\s*\$([\d,]+\.\d{2})",
    re.IGNORECASE,
)
_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y")
_WALMART_ITEM_ID = re.compile(r"\b(\d{8,14})\b")
_WALMART_MERCHANT_ITEM_ID = re.compile(
    r"\b(?:ITEM\s*(?:NO\.?|NUMBER|#)|SKU)\s*[:#]?\s*([A-Z0-9-]{3,32})\b",
    re.IGNORECASE,
)
_WALMART_EXPLICIT_UPC = re.compile(
    r"\b(?:UPC|EAN|GTIN)\s*[:#]?\s*(\d{8,14})\b",
    re.IGNORECASE,
)


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


def _multi_order_document(
    text: str,
    extraction: PDFTextExtraction,
    source_hint: str,
) -> dict[str, Any] | None:
    header_pattern = re.compile(
        r"(?im)^\s*(?:Amazon|Walmart|BJ'S WHOLESALE CLUB|SAM'S CLUB)\s*$"
    )
    starts = [match.start() for match in header_pattern.finditer(text)]
    if len(starts) < 2:
        return None
    segments = [
        text[start : starts[index + 1] if index + 1 < len(starts) else len(text)].strip()
        for index, start in enumerate(starts)
    ]
    parsed_orders = [parse_receipt_text(segment, extraction, source_hint) for segment in segments]
    orders = [parsed.document for parsed in parsed_orders]
    identities = [order["receipt"].get("transaction_number") for order in orders]
    duplicate_identity = len(set(identity for identity in identities if identity)) != len(
        [identity for identity in identities if identity]
    )
    if duplicate_identity:
        for order in orders:
            order["review_required"] = True
            order["extraction"]["issues"] = [
                *order["extraction"].get("issues", []),
                "DUPLICATE_ORDER_IDENTITIES_IN_SOURCE",
            ]
    metadata = orders[0].get("metadata", {}) if orders else {}
    issue_codes = sorted(
        {
            issue
            for order in orders
            for issue in order.get("extraction", {}).get("issues", [])
            if isinstance(issue, str)
        }
    )
    return {
        "orders": orders,
        "metadata": metadata,
        "extraction": {
            "content_kind": extraction.classification.content_kind.value,
            "method": extraction.method.value,
            "order_count": len(orders),
            "issues": issue_codes,
            "pages": [
                {
                    "page_number": page.page_number,
                    "native_text_chars": len(page.native_text.strip()),
                    "ocr_confidence": (
                        str(page.ocr_confidence) if page.ocr_confidence is not None else None
                    ),
                    "selected_source": page.selected_source,
                }
                for page in extraction.pages
            ],
        },
        "review_required": any(order.get("review_required") is True for order in orders),
    }


def extract_receipt_document(
    source: bytes,
    media_type: str,
    ocr_reader: OCRPageReader | None = None,
) -> dict[str, Any]:
    reader = ocr_reader or LocalTesseractReader()
    if media_type == "application/pdf":
        native_extraction = extract_pdf_text(source)
        native_text = "\n".join(page.native_text for page in native_extraction.pages)
        native = parse_receipt_text(native_text, native_extraction, "NATIVE_TEXT")
        if native_extraction.classification.requires_ocr or native.review_required:
            extraction = extract_pdf_text(source, reader, force_ocr=True)
        else:
            extraction = native_extraction
    elif media_type in {"image/png", "image/jpeg"}:
        text, confidence = reader(source, 1)
        extraction = _image_text_extraction(text, confidence)
    else:
        raise ValueError(f"Unsupported receipt media type: {media_type}")

    native_text = "\n".join(page.native_text for page in extraction.pages)
    native = parse_receipt_text(native_text, extraction, "NATIVE_TEXT")
    ocr_pages = [page for page in extraction.pages if page.ocr_text is not None]
    if not ocr_pages:
        segmented = _multi_order_document(native_text, extraction, "NATIVE_TEXT")
        if segmented is not None:
            return segmented
        return native.document

    ocr_text = "\n".join(
        page.ocr_text if page.ocr_text is not None else page.native_text
        for page in extraction.pages
    )
    segmented = _multi_order_document(ocr_text, extraction, "OCR")
    if segmented is not None:
        if any(
            native.document["receipt"].get(field) is not None
            for field in ("date", "time", "transaction_number", "subtotal", "tax", "total")
        ):
            segmented["native_candidate"] = native.document
            segmented["review_required"] = True
            segmented["extraction"]["issues"].append("SEGMENTED_NATIVE_OCR_REQUIRES_REVIEW")
            for order in segmented["orders"]:
                order["review_required"] = True
                order["extraction"]["issues"].append("SEGMENTED_NATIVE_OCR_REQUIRES_REVIEW")
        return segmented
    ocr = parse_receipt_text(ocr_text, extraction, "OCR")
    native_header = native.document["receipt"]
    ocr_header = ocr.document["receipt"]
    merged_header, header_sources = merge_field_candidates(
        native_header,
        native.field_confidence,
        ocr_header,
        ocr.field_confidence,
    )
    issues: list[str] = list(ocr.issues)
    header_reconciliations = []
    for field in dict.fromkeys((*native_header, *ocr_header)):
        native_value = native_header.get(field)
        ocr_value = ocr_header.get(field)
        if (
            native_value not in (None, "")
            and ocr_value not in (None, "")
            and native_value != ocr_value
        ):
            native_score = native.field_confidence.get(field, Decimal("0"))
            ocr_score = ocr.field_confidence.get(field, Decimal("0"))
            header_reconciliations.append(
                {
                    "field": field,
                    "selected_source": header_sources[field],
                    "native_confidence": str(native_score),
                    "ocr_confidence": str(ocr_score),
                }
            )
            if abs(native_score - ocr_score) < Decimal("0.12"):
                issues.append(f"LOW_CONFIDENCE_HEADER_CONFLICT:{field}")
    native_items = native.document["items"]
    ocr_items = ocr.document["items"]
    item_sources: list[dict[str, str]] = []
    if len(native_items) == len(ocr_items) and _same_item_occurrences(native_items, ocr_items):
        merged_pairs = [
            _merge_item(native_item, ocr_item, native.field_confidence, ocr.field_confidence)
            for native_item, ocr_item in zip(native_items, ocr_items, strict=True)
        ]
        merged_items = [pair[0] for pair in merged_pairs]
        item_sources = [pair[1] for pair in merged_pairs]
        for index, (native_item, ocr_item) in enumerate(zip(native_items, ocr_items, strict=True)):
            for field in native_item:
                if (
                    native_item.get(field) not in (None, "")
                    and ocr_item.get(field) not in (None, "")
                    and native_item[field] != ocr_item[field]
                    and abs(
                        native.field_confidence.get(field, Decimal("0"))
                        - ocr.field_confidence.get(field, Decimal("0"))
                    )
                    < Decimal("0.12")
                ):
                    issues.append(f"LOW_CONFIDENCE_ITEM_CONFLICT:{index}:{field}")
    elif not native_items or not ocr_items:
        chosen_items = ocr_items if ocr_items else native_items
        chosen_parse = ocr if ocr_items else native
        merged_items = chosen_items
        item_sources = [dict(chosen_parse.field_sources) for _ in chosen_items]
    else:
        chosen = ocr if _parse_completeness(ocr) > _parse_completeness(native) else native
        merged_items = chosen.document["items"]
        item_sources = [dict(chosen.field_sources) for _ in merged_items]
        issues.append("NATIVE_OCR_LINE_OCCURRENCE_CONFLICT")
    chosen_parse = ocr if _parse_completeness(ocr) >= _parse_completeness(native) else native
    document = dict(chosen_parse.document)
    document["receipt"] = merged_header
    document["items"] = merged_items
    missing = [
        field
        for field in ("store", "date", "time", "transaction_number", "total")
        if not merged_header.get(field)
    ]
    if not merged_items:
        missing.append("items")
        issues.append("NO_LINE_ITEMS_PARSED")
    if missing:
        issues.append("MISSING_FIELDS:" + ",".join(missing))
    low_confidence_fields = [
        field
        for field in ("store", "date", "transaction_number", "total")
        if merged_header.get(field)
        and max(
            native.field_confidence.get(field, Decimal("0")),
            ocr.field_confidence.get(field, Decimal("0")),
        )
        < Decimal("0.62")
    ]
    if low_confidence_fields:
        issues.append("LOW_CONFIDENCE_FIELDS:" + ",".join(low_confidence_fields))
    document["review_required"] = bool(issues)
    document["extraction"] = {
        **document.get("extraction", {}),
        "method": extraction.method.value,
        "field_candidates": {
            field: {
                "native": native_header.get(field),
                "ocr": ocr_header.get(field),
                "selected": merged_header.get(field),
                "selected_source": header_sources.get(field),
                "native_confidence": str(native.field_confidence.get(field, Decimal("0"))),
                "ocr_confidence": str(ocr.field_confidence.get(field, Decimal("0"))),
            }
            for field in dict.fromkeys((*native_header, *ocr_header))
        },
        "item_candidates": {
            "native": native_items,
            "ocr": ocr_items,
            "selected": merged_items,
            "selected_sources": item_sources,
        },
        "field_sources": {
            **header_sources,
            "items": item_sources,
        },
        "reconciliations": header_reconciliations,
        "issues": issues,
        "missing_fields": missing,
        "native_field_confidence": {
            field: str(value) for field, value in native.field_confidence.items()
        },
        "ocr_field_confidence": {
            field: str(value) for field, value in ocr.field_confidence.items()
        },
    }
    return document


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
        if (
            _WALMART_ITEM_ID.search(line) or _WALMART_MERCHANT_ITEM_ID.search(line)
        )
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


def _parse_completeness(parsed: ParsedReceiptText) -> int:
    receipt = parsed.document["receipt"]
    return sum(value is not None for value in receipt.values()) + len(parsed.document["items"])


def _image_text_extraction(text: str, confidence: Decimal) -> PDFTextExtraction:
    from mbs.receipts.pdf_extraction import (
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
