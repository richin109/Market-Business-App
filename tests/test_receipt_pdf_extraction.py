from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont

from mbs.receipts.pdf_extraction import (
    LocalTesseractReader,
    PDFContentKind,
    PDFExtractionMethod,
    classify_pdf,
    extract_pdf_text,
    merge_field_candidates,
)
from mbs.receipts.pdf_parsing import extract_receipt_document, parse_receipt_text


def _text_pdf(text: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_textbox(pymupdf.Rect(48, 48, 564, 744), text, fontsize=12)
    result = cast(bytes, document.tobytes())
    document.close()
    return result


def _image_pdf(text: str) -> bytes:
    image = Image.new("RGB", (1200, 1600), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=44)
    for index, line in enumerate(text.splitlines()):
        draw.text((70, 100 + index * 100), line, fill="black", font=font)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_image(page.rect, stream=buffer.getvalue())
    result = cast(bytes, document.tobytes())
    document.close()
    return result


def _synthetic_receipt_text() -> str:
    return (
        "Amazon\n"
        "Order placed October 1, 2026\n"
        "Order # SYN-2048\n"
        "Time: 09:30 AM\n"
        "Payment method Visa\n"
        "Order Summary\n"
        "Item (1) Subtotal: $4.00\n"
        "Estimated tax: $0.32\n"
        "Order total: $4.32\n"
        "Delivered October 1, 2026\n"
        "SYNTHETIC APPLES\n"
        "Quantity: 2\n"
        "Size: 2 LB\n"
        "ASIN: SYN-ITEM-7\n"
        "UPC: 000123456789\n"
        "Sold by: Amazon\n"
        "Supplied by: Amazon\n"
        "Return window closes October 31, 2026\n"
        "$4.00"
    )


def _synthetic_order_sheet_text(order_count: int) -> str:
    orders = []
    for order_number in range(1, order_count + 1):
        orders.append(
            "\n".join(
                [
                    "Amazon",
                    "Order placed October 2, 2026",
                    f"Order # SYN-ORDER-{order_number:03d}",
                    f"Time: 09:{order_number:02d} AM",
                    "Payment method Visa",
                    "Item (1) Subtotal: $1.00",
                    "Estimated tax: $0.06",
                    "Order total: $1.06",
                    "Delivered October 2, 2026",
                    f"Synthetic item {order_number:03d}",
                    "Quantity: 1",
                    "Size: 1 CT",
                    f"ASIN: SYN-ITEM-{order_number:03d}",
                    f"UPC: {order_number:012d}",
                    "$1.00",
                ]
            )
        )
    return "\n".join(orders)


def test_selectable_text_pdf_uses_native_text_without_ocr() -> None:
    source = _text_pdf(_synthetic_receipt_text())

    classification = classify_pdf(source)
    extraction = extract_pdf_text(
        source,
        lambda _page, _number: pytest.fail("Complete native text must not trigger OCR"),
    )

    assert classification.content_kind is PDFContentKind.SELECTABLE_TEXT
    assert classification.has_selectable_text is True
    assert classification.has_embedded_images is False
    assert classification.requires_ocr is False
    assert extraction.method is PDFExtractionMethod.NATIVE_TEXT
    assert "SYN-ITEM-7" in extraction.selected_text
    assert extraction.pages[0].native_confidence >= Decimal("0.62")


def test_full_page_image_pdf_uses_ocr_fallback() -> None:
    source = _image_pdf(_synthetic_receipt_text())
    calls: list[int] = []

    def fake_ocr(_page: bytes, page_number: int) -> tuple[str, Decimal]:
        calls.append(page_number)
        return _synthetic_receipt_text(), Decimal("0.94")

    classification = classify_pdf(source)
    extraction = extract_pdf_text(source, fake_ocr)

    assert classification.content_kind is PDFContentKind.IMAGE_ONLY
    assert classification.has_selectable_text is False
    assert classification.has_embedded_images is True
    assert classification.has_single_full_page_image is True
    assert classification.requires_ocr is True
    assert calls == [1]
    assert extraction.method is PDFExtractionMethod.OCR_FALLBACK
    assert extraction.pages[0].selected_source == "OCR"
    assert "SYN-ITEM-7" in extraction.selected_text


def test_mixed_pdf_with_incomplete_text_runs_ocr_and_verifies_sources() -> None:
    source = _image_pdf(_synthetic_receipt_text())
    document = pymupdf.open(stream=source, filetype="pdf")
    page = document[0]
    page.insert_text((40, 30), "partial native header", fontsize=8)
    mixed_source = document.tobytes()
    document.close()
    ocr_calls = 0

    def fake_ocr(_page: bytes, _page_number: int) -> tuple[str, Decimal]:
        nonlocal ocr_calls
        ocr_calls += 1
        return _synthetic_receipt_text(), Decimal("0.96")

    classification = classify_pdf(mixed_source)
    extraction = extract_pdf_text(mixed_source, fake_ocr)

    assert classification.content_kind is PDFContentKind.MIXED
    assert classification.requires_ocr is True
    assert ocr_calls == 1
    assert extraction.method is PDFExtractionMethod.OCR_VERIFIED
    assert extraction.pages[0].selected_source == "OCR"


def test_native_text_wins_when_its_field_confidence_is_higher() -> None:
    merged, sources = merge_field_candidates(
        {"transaction_number": "SYN-NATIVE", "total": None},
        {"transaction_number": Decimal("0.98")},
        {"transaction_number": "SYN-OCR", "total": "4.32"},
        {"transaction_number": Decimal("0.83"), "total": Decimal("0.91")},
    )

    assert merged == {"transaction_number": "SYN-NATIVE", "total": "4.32"}
    assert sources == {"transaction_number": "NATIVE_TEXT", "total": "OCR"}


def test_structured_parser_returns_distinct_receipt_fields_and_review_confidence() -> None:
    source = _text_pdf(_synthetic_receipt_text())
    extraction = extract_pdf_text(source)

    parsed = parse_receipt_text(extraction.selected_text, extraction)
    document = parsed.document

    assert document["receipt"] == {
        "store": "Amazon",
        "date": "2026-10-01",
        "time": "09:30:00",
        "transaction_number": "SYN-2048",
        "subtotal": "4.00",
        "tax": "0.32",
        "total": "4.32",
        "payment_method": "CARD",
    }
    assert len(document["items"]) == 1
    assert document["items"][0]["description"] == "SYNTHETIC APPLES"
    assert document["items"][0]["store_product_id"] == "SYN-ITEM-7"
    assert document["items"][0]["upc"] == "000123456789"
    assert document["items"][0]["quantity"] == "2"
    assert document["items"][0]["weight_lb"] is None
    assert document["items"][0]["printed_size"] == "2 LB"
    assert document["items"][0]["delivery_date"] == "2026-10-01"
    assert document["items"][0]["line_total"] == "4.00"
    assert parsed.review_required is False
    assert document["extraction"]["field_source"]["total"] == "NATIVE_TEXT"
    assert Decimal(document["extraction"]["field_confidence"]["total"]) > Decimal("0.62")


def test_local_receipt_adapter_parses_complete_native_text_pdf() -> None:
    source = _text_pdf(_synthetic_receipt_text())

    document = extract_receipt_document(
        source,
        "application/pdf",
        lambda _page, _number: pytest.fail("High-confidence native text must not call OCR"),
    )

    assert document["review_required"] is False
    assert document["extraction"]["method"] == "NATIVE_TEXT"
    assert document["receipt"]["transaction_number"] == "SYN-2048"
    assert document["items"][0]["weight_lb"] is None
    assert document["items"][0]["quantity"] == "2"


def test_local_receipt_adapter_uses_ocr_for_image_only_and_weak_native_text() -> None:
    image_only_pdf = _image_pdf(_synthetic_receipt_text())
    calls = 0

    def fake_ocr(_page: bytes, _page_number: int) -> tuple[str, Decimal]:
        nonlocal calls
        calls += 1
        return _synthetic_receipt_text(), Decimal("0.94")

    image_document = extract_receipt_document(
        image_only_pdf,
        "application/pdf",
        fake_ocr,
    )
    assert image_document["review_required"] is False
    assert image_document["extraction"]["method"] == "OCR_FALLBACK"
    assert image_document["extraction"]["field_sources"]["total"] == "OCR"

    weak_text_pdf = _text_pdf("partial native text")
    weak_document = extract_receipt_document(weak_text_pdf, "application/pdf", fake_ocr)
    assert calls == 2
    assert weak_document["review_required"] is False
    assert weak_document["extraction"]["method"] == "OCR_VERIFIED"
    assert weak_document["extraction"]["field_sources"]["transaction_number"] == "OCR"


def test_native_ocr_conflict_prefers_more_confident_field_and_records_reconciliation() -> None:
    source = _image_pdf(_synthetic_receipt_text())
    pdf = pymupdf.open(stream=source, filetype="pdf")
    pdf[0].insert_textbox(
        pymupdf.Rect(36, 36, 300, 100),
        "Amazon\nTime: 09:30 AM\nOrder total: $9.99",
        fontsize=9,
    )
    mixed_source = pdf.tobytes()
    pdf.close()

    document = extract_receipt_document(
        mixed_source,
        "application/pdf",
        lambda _page, _number: (_synthetic_receipt_text(), Decimal("0.96")),
    )

    assert document["extraction"]["method"] == "OCR_VERIFIED"
    assert document["extraction"]["field_sources"]["total"] == "OCR"
    reconciliations = document["extraction"]["reconciliations"]
    assert len(reconciliations) == 1
    assert reconciliations[0]["field"] == "total"
    assert reconciliations[0]["selected_source"] == "OCR"
    assert Decimal(reconciliations[0]["native_confidence"]) < Decimal(
        reconciliations[0]["ocr_confidence"]
    )
    assert document["review_required"] is False


def test_low_confidence_native_ocr_conflict_requires_review() -> None:
    source = _image_pdf(_synthetic_receipt_text())
    pdf = pymupdf.open(stream=source, filetype="pdf")
    pdf[0].insert_textbox(
        pymupdf.Rect(36, 36, 300, 100),
        "Amazon\nTime: 09:30 AM\nOrder total: $9.99",
        fontsize=9,
    )
    mixed_source = pdf.tobytes()
    pdf.close()

    document = extract_receipt_document(
        mixed_source,
        "application/pdf",
        lambda _page, _number: (_synthetic_receipt_text(), Decimal("0.26")),
    )

    assert document["review_required"] is True
    assert "LOW_CONFIDENCE_HEADER_CONFLICT:total" in document["extraction"]["issues"]
    assert document["extraction"]["field_sources"]["total"] == "NATIVE_TEXT"


def test_image_only_document_uses_ocr_and_marks_missing_fields_for_review() -> None:
    source = _image_pdf("SYNTHETIC MARKET\nItem: SYN-ITEM-7\nQty 2")
    calls = 0

    def fake_ocr(_page: bytes, _page_number: int) -> tuple[str, Decimal]:
        nonlocal calls
        calls += 1
        return "SYNTHETIC MARKET\nItem: SYN-ITEM-7\nQty 2", Decimal("0.96")

    document = extract_receipt_document(source, "application/pdf", fake_ocr)

    assert calls == 1
    assert document["extraction"]["method"] == "OCR_FALLBACK"
    assert document["review_required"] is True
    assert "total" in document["extraction"]["missing_fields"]


def _synthetic_walmart_image_text() -> str:
    return "\n".join(
        [
            "WALMART",
            "ST# 0001 OP# 000001 TE# 01 TR# 0002",
            "SYN PRODUCT A 000000000001 F 3.50",
            "SYN PRODUCT B 000000000002 F 2.25",
            "1.50 LB @ 1.00 lb / 1.50",
            "SUBTOTAL 5.75",
            "TAX1 6.0000 % 0.30",
            "TAX2 1.0000 % 0.05",
            "TOTAL 6.10",
            "VISA CREDIT TEND 6.10",
            "VISA **** 0000",
            "REF # 000000000003",
            "01/02/2024 10:15:00",
            "01/02/2024 10:21:00",
        ]
    )


def test_walmart_image_page_parses_rows_taxes_and_holds_ambiguous_references() -> None:
    text = _synthetic_walmart_image_text()
    source = _image_pdf(text)

    document = extract_receipt_document(
        source, "application/pdf", lambda _page, _number: (text, Decimal("0.95"))
    )

    receipt = document["receipt"]
    assert document["extraction"]["content_kind"] == "IMAGE_ONLY"
    assert document["extraction"]["method"] == "OCR_FALLBACK"
    assert receipt["store"] == "Walmart"
    assert receipt["tax"] == "0.35"
    assert receipt["card_last_four"] == "0000"
    assert receipt["transaction_number"] is None
    assert receipt["time"] is None
    assert receipt["reference_candidates"]["store_number"] == "0001"
    assert receipt["reference_candidates"]["printed_reference"] == "000000000003"
    assert [item["identifier_candidate"] for item in document["items"]] == [
        "000000000001",
        "000000000002",
    ]
    assert all(item["upc"] == item["identifier_candidate"] for item in document["items"])
    assert all(item["store_product_id"] is None for item in document["items"])
    issues = document["extraction"]["issues"]
    assert "VENDOR_REFERENCE_REQUIRES_REVIEW" in issues
    assert "AMBIGUOUS_PRINTED_TIMESTAMPS" in issues
    assert document["review_required"] is True


def test_rm_023_image_pdf_keeps_merchant_id_upc_weight_and_header_evidence_distinct() -> None:
    text = "\n".join(
        [
            "WALMART",
            "ST# 0001 OP# 000001 TE# 01 TR# 0002",
            "SYN PACKAGED ITEM ITEM # 12345678 UPC: 000123456789 18 OZ F 4.50",
            "SYN REPEAT ITEM ITEM # 87654321 UPC: 000987654321 F 1.00",
            "SYN REPEAT ITEM ITEM # 87654321 UPC: 000987654321 F 1.00",
            "SYN REPEAT ITEM ITEM # 11223344 UPC: 000112233445 F 1.00",
            "SYN WEIGHED ITEM 223344556677 F 1.50",
            "WEIGHT 1.50 LB",
            "SUBTOTAL 8.00",
            "TAX 6.0000 % 0.48",
            "TOTAL 8.48",
            "VISA **** 4827",
            "REF # 000000000003",
            "01/02/2024 10:15:00",
            "01/02/2024 10:21:00",
        ]
    )

    document = extract_receipt_document(
        _image_pdf(text),
        "application/pdf",
        lambda _page, _number: (text, Decimal("0.95")),
    )

    receipt = document["receipt"]
    packaged, repeat_one, repeat_two, same_description, weighed = document["items"]
    assert packaged["store_product_id"] == "12345678"
    assert packaged["upc"] == "000123456789"
    assert packaged["identifier_candidate"] == "12345678"
    assert packaged["printed_size"] == "18 OZ"
    assert packaged["weight_lb"] is None
    assert "ITEM # 12345678 UPC: 000123456789" in packaged["raw_line_text"]
    assert repeat_one["store_product_id"] == repeat_two["store_product_id"] == "87654321"
    assert repeat_one["description"] == repeat_two["description"]
    assert repeat_one["line_total"] == repeat_two["line_total"] == "1.00"
    assert same_description["description"] == repeat_one["description"]
    assert same_description["store_product_id"] == "11223344"
    assert same_description["store_product_id"] != repeat_one["store_product_id"]
    assert weighed["weight_lb"] == "1.50"
    assert weighed["printed_size"] is None
    assert receipt["reference_candidates"]["transaction_reference"] == "0002"
    assert receipt["reference_candidates"]["printed_reference"] == "000000000003"
    assert receipt["time"] is None
    assert receipt["card_last_four"] == "4827"
    assert receipt["subtotal"] == "8.00"
    assert receipt["tax"] == "0.48"
    assert receipt["total"] == "8.48"
    assert "AMBIGUOUS_PRINTED_TIMESTAMPS" in document["extraction"]["issues"]
    assert document["review_required"] is True

    masked_text = text.replace("VISA **** 4827", "VISA ****")
    masked_document = extract_receipt_document(
        _image_pdf(masked_text),
        "application/pdf",
        lambda _page, _number: (masked_text, Decimal("0.95")),
    )
    assert masked_document["receipt"]["card_last_four"] is None


@pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="Local Tesseract executable is unavailable"
)
def test_rm_023_real_ocr_holds_incomplete_image_only_item_evidence() -> None:
    text = "\n".join(
        [
            "WALMART",
            "SYN PACKAGED ITEM ITEM # 12345678 UPC: 000123456789 18 OZ F 4.50",
            "SUBTOTAL 4.50",
            "TAX 0.27",
            "TOTAL 4.77",
            "VISA **** 4827",
            "01/02/2024 10:15:00",
            "01/02/2024 10:21:00",
        ]
    )

    document = extract_receipt_document(
        _image_pdf(text), "application/pdf", LocalTesseractReader()
    )

    item = document["items"][0]
    assert document["extraction"]["content_kind"] == "IMAGE_ONLY"
    assert document["extraction"]["method"] == "OCR_FALLBACK"
    assert item["store_product_id"] == "12345678"
    assert item["upc"] != item["store_product_id"]
    assert "ITEM # 12345678 UPC:" in item["raw_line_text"]
    assert item["line_total"] is None
    assert "INCOMPLETE_LINE_ITEMS:1" in document["extraction"]["issues"]
    assert document["review_required"] is True


def test_rm_025_image_only_order_sheet_segments_five_ten_and_fifteen_orders() -> None:
    for order_count in (5, 10, 15):
        text = _synthetic_order_sheet_text(order_count)
        source = _image_pdf(text)
        ocr_calls = 0

        def fake_ocr(
            _page: bytes, _page_number: int, selected_text: str = text
        ) -> tuple[str, Decimal]:
            nonlocal ocr_calls
            ocr_calls += 1
            return selected_text, Decimal("0.96")

        document = extract_receipt_document(source, "application/pdf", fake_ocr)

        assert ocr_calls == 1
        assert document["extraction"]["content_kind"] == "IMAGE_ONLY"
        assert document["review_required"] is False
        orders = document["orders"]
        assert len(orders) == order_count
        assert [order["receipt"]["transaction_number"] for order in orders] == [
            f"SYN-ORDER-{order_number:03d}" for order_number in range(1, order_count + 1)
        ]
        assert all(order["receipt"]["subtotal"] == "1.00" for order in orders)
        assert all(order["receipt"]["tax"] == "0.06" for order in orders)
        assert all(order["receipt"]["total"] == "1.06" for order in orders)
        assert all(order["review_required"] is False for order in orders)


def test_rm_025_mixed_pdf_segments_complete_ocr_order_sheet() -> None:
    text = _synthetic_order_sheet_text(5)
    source = _image_pdf(text)
    pdf = pymupdf.open(stream=source, filetype="pdf")
    pdf[0].insert_textbox(pymupdf.Rect(36, 36, 300, 100), "partial native header", fontsize=8)
    mixed_source = pdf.tobytes()
    pdf.close()

    document = extract_receipt_document(
        mixed_source,
        "application/pdf",
        lambda _page, _number: (text, Decimal("0.96")),
    )

    assert document["extraction"]["content_kind"] == "MIXED"
    assert [order["receipt"]["transaction_number"] for order in document["orders"]] == [
        f"SYN-ORDER-{number:03d}" for number in range(1, 6)
    ]
    assert all(order["review_required"] is False for order in document["orders"])


def test_rm_025_mixed_pdf_retains_native_header_evidence_on_hold() -> None:
    text = _synthetic_order_sheet_text(5)
    pdf = pymupdf.open(stream=_image_pdf(text), filetype="pdf")
    pdf[0].insert_textbox(
        pymupdf.Rect(36, 36, 300, 100),
        "Amazon\nOrder # SYN-NATIVE-CONFLICT\nOrder total: $9.99",
        fontsize=8,
    )
    source = pdf.tobytes()
    pdf.close()

    document = extract_receipt_document(
        source, "application/pdf", lambda _page, _number: (text, Decimal("0.96"))
    )

    assert len(document["orders"]) == 5
    assert document["review_required"] is True
    assert all(order["review_required"] is True for order in document["orders"])
    assert document["native_candidate"]["receipt"]["transaction_number"] == (
        "SYN-NATIVE-CONFLICT"
    )
    assert document["native_candidate"]["receipt"]["total"] == "9.99"
    assert "SEGMENTED_NATIVE_OCR_REQUIRES_REVIEW" in document["extraction"]["issues"]


@pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="Local Tesseract executable is unavailable"
)
def test_local_tesseract_reads_synthetic_image_only_pdf() -> None:
    source = _image_pdf(_synthetic_receipt_text())

    extraction = extract_pdf_text(source, LocalTesseractReader())

    assert extraction.method is PDFExtractionMethod.OCR_FALLBACK
    assert extraction.pages[0].ocr_confidence is not None
    assert extraction.pages[0].ocr_confidence > Decimal("0.10")
    assert "SYN-ITEM-7" in extraction.selected_text


def test_opt_in_reference_pdf_classification_and_json_schema(
    record_property: Any,
) -> None:
    reference_directory = os.environ.get("MBS_REFERENCE_PDF_DIR")
    if not reference_directory:
        pytest.skip("Set MBS_REFERENCE_PDF_DIR for the isolated local reference-PDF check")
    root = Path(reference_directory).resolve()
    pdf_files = sorted(root.glob("*.pdf"))
    if not pdf_files:
        pytest.skip("Reference directory contains no PDF files")

    native_pdf_count = 0
    image_pdf_count = 0
    full_page_image_pages = 0
    ocr_fallback_pages = 0
    review_required_count = 0
    expected_schema_gap_count = 0
    reviewed_expected_count = 0
    header_mismatches: list[dict[str, Any]] = []
    item_count_mismatches = 0
    item_field_mismatches: list[dict[str, Any]] = []

    def comparable(field: str, value: Any) -> Any:
        if value is None:
            return None
        if field in {"subtotal", "tax", "total", "line_total", "unit_price"}:
            try:
                return Decimal(str(value).replace("$", "").replace(",", "")).quantize(
                    Decimal("0.01")
                )
            except Exception:
                return str(value).strip().casefold()
        return str(value).strip().casefold()

    for pdf_path in pdf_files:
        source = pdf_path.read_bytes()
        classification = classify_pdf(source)
        if classification.has_selectable_text:
            native_pdf_count += 1
        if classification.has_embedded_images:
            image_pdf_count += 1
        full_page_image_pages += sum(page.full_page_image for page in classification.pages)
        extraction = extract_receipt_document(
            source,
            "application/pdf",
            LocalTesseractReader() if classification.requires_ocr else None,
        )
        extraction_pages = extraction.get("extraction", {}).get("pages", [])
        ocr_fallback_pages += sum(
            page.get("selected_source") == "OCR"
            for page in extraction_pages
            if isinstance(page, dict)
        )
        review_required_count += int(extraction["review_required"])

        slug = re.sub(r"[^a-z0-9]+", "-", pdf_path.name.lower()).strip("-")[:48]
        digest = hashlib.sha256(pdf_path.name.encode("utf-8")).hexdigest()[:10]
        expected_path = root / "expected" / f"{slug}-{digest}.expected.json"
        if not expected_path.is_file():
            expected_path = pdf_path.with_suffix(".json")
        if not expected_path.is_file():
            expected_schema_gap_count += 1
            continue
        wrapper = json.loads(expected_path.read_text(encoding="utf-8"))
        expected = wrapper.get("expected") if isinstance(wrapper, dict) else None
        if not isinstance(expected, dict):
            expected_schema_gap_count += 1
            continue
        reviewed = bool(wrapper.get("reviewed", False))
        if reviewed:
            reviewed_expected_count += 1
        if not isinstance(expected.get("items"), list):
            expected_schema_gap_count += 1
        header_keys = {
            "store",
            "date",
            "time",
            "transaction_number",
            "subtotal",
            "tax",
            "total",
            "payment_method",
        }
        expected_schema_gap_count += len(header_keys - expected.keys())
        extracted_header = extraction.get("receipt")
        assert isinstance(extracted_header, dict)
        assert header_keys <= extracted_header.keys()
        extracted_items = extraction.get("items")
        assert isinstance(extracted_items, list)
        if not reviewed:
            continue
        header_diff = [
            key
            for key in header_keys
            if key in expected
            and comparable(key, expected.get(key)) != comparable(key, extracted_header.get(key))
        ]
        if header_diff:
            header_mismatches.append(
                {"sample": f"R{len(header_mismatches) + 1:02d}", "fields": sorted(header_diff)}
            )
        expected_items = expected.get("items", [])
        if len(expected_items) != len(extracted_items):
            item_count_mismatches += 1
        item_field_map = {
            "description": "description",
            "item_number": "store_product_id",
            "size": "printed_size",
            "quantity": "quantity",
            "weight_lb": "weight_lb",
            "line_total": "line_total",
        }
        for item_index, (expected_item, extracted_item) in enumerate(
            zip(expected_items, extracted_items, strict=False)
        ):
            if not isinstance(expected_item, dict) or not isinstance(extracted_item, dict):
                continue
            differing_fields = [
                source_key
                for source_key, extracted_key in item_field_map.items()
                if source_key in expected_item
                and comparable(source_key, expected_item.get(source_key))
                != comparable(source_key, extracted_item.get(extracted_key))
            ]
            if differing_fields:
                item_field_mismatches.append(
                    {
                        "sample": f"R{pdf_files.index(pdf_path) + 1:02d}",
                        "line": item_index + 1,
                        "fields": sorted(differing_fields),
                    }
                )

    record_property("reference_pdf_count", len(pdf_files))
    record_property("native_text_pdf_count", native_pdf_count)
    record_property("embedded_image_pdf_count", image_pdf_count)
    record_property("full_page_image_page_count", full_page_image_pages)
    record_property("ocr_fallback_page_count", ocr_fallback_pages)
    record_property("review_required_count", review_required_count)
    record_property("expected_json_schema_gap_count", expected_schema_gap_count)
    record_property("reviewed_expected_count", reviewed_expected_count)
    record_property("header_mismatches", json.dumps(header_mismatches))
    record_property("item_count_mismatch_count", item_count_mismatches)
    record_property("item_field_mismatch_count", len(item_field_mismatches))
    record_property("item_field_mismatch_fields", json.dumps(item_field_mismatches))
