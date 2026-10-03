from __future__ import annotations

from decimal import Decimal
from typing import Any

from mbs.domain.pdf_extraction import OCRPageReader, merge_field_candidates
from mbs.domain.receipt_segmentation import _multi_order_document
from mbs.domain.receipt_text import _image_text_extraction, _parse_completeness, parse_receipt_text
from mbs.domain.receipt_text_values import _merge_item, _same_item_occurrences
from mbs.infrastructure.pdf_ocr import LocalTesseractReader
from mbs.infrastructure.pdf_text import extract_pdf_text


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
