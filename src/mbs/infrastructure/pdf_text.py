from __future__ import annotations

from decimal import Decimal

import pymupdf

from mbs.domain.pdf_extraction import (
    _LOW_CONFIDENCE_THRESHOLD,
    _MIN_NATIVE_TEXT_CHARS,
    ExtractedPDFPage,
    OCRPageReader,
    OCRUnavailableError,
    PDFClassification,
    PDFContentKind,
    PDFExtractionMethod,
    PDFPageClassification,
    PDFTextExtraction,
    _native_text_confidence,
    _visible_text,
)


def classify_pdf(source: bytes) -> PDFClassification:
    if not source.startswith(b"%PDF-"):
        raise ValueError("Receipt PDF signature is invalid")
    try:
        document = pymupdf.open(stream=source, filetype="pdf")
    except (pymupdf.FileDataError, ValueError) as error:
        raise ValueError("Receipt PDF cannot be opened") from error
    try:
        if not document.page_count:
            raise ValueError("Receipt PDF has no pages")

        pages: list[PDFPageClassification] = []
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            text = page.get_text("text", sort=True)
            image_infos = page.get_image_info(xrefs=True)
            page_area = max(page.rect.get_area(), 1)
            largest_image_coverage = max(
                (
                    Decimal(str(pymupdf.Rect(info["bbox"]).get_area() / page_area))
                    for info in image_infos
                    if info.get("bbox") is not None
                ),
                default=Decimal("0"),
            )
            full_page_image = largest_image_coverage >= Decimal("0.80")
            text_chars = len(_visible_text(text))
            confidence = _native_text_confidence(text)
            requires_ocr = (
                text_chars < _MIN_NATIVE_TEXT_CHARS
                or confidence < _LOW_CONFIDENCE_THRESHOLD
                or full_page_image
            )
            pages.append(
                PDFPageClassification(
                    page_number=page_index + 1,
                    selectable_text_chars=text_chars,
                    embedded_image_count=len(image_infos),
                    largest_image_coverage=largest_image_coverage,
                    full_page_image=full_page_image,
                    native_confidence=confidence,
                    requires_ocr=requires_ocr,
                )
            )

        has_text = any(page.selectable_text_chars for page in pages)
        has_images = any(page.embedded_image_count for page in pages)
        has_full_page_image = any(page.full_page_image for page in pages)
        kind = (
            PDFContentKind.MIXED
            if has_text and has_images
            else PDFContentKind.SELECTABLE_TEXT
            if has_text
            else PDFContentKind.IMAGE_ONLY
        )
        return PDFClassification(
            content_kind=kind,
            has_selectable_text=has_text,
            has_embedded_images=has_images,
            has_single_full_page_image=has_full_page_image,
            requires_ocr=any(page.requires_ocr for page in pages),
            pages=tuple(pages),
        )
    finally:
        document.close()


def extract_pdf_text(
    source: bytes,
    ocr_reader: OCRPageReader | None = None,
    *,
    force_ocr: bool = False,
) -> PDFTextExtraction:
    classification = classify_pdf(source)
    document = pymupdf.open(stream=source, filetype="pdf")
    try:
        needs_ocr = classification.requires_ocr or force_ocr
        if needs_ocr and ocr_reader is None and force_ocr:
            raise OCRUnavailableError("PDF text is incomplete or image-only; local OCR is required")

        pages: list[ExtractedPDFPage] = []
        any_ocr_used = False
        any_native_verified = False
        for page_index, page_classification in enumerate(classification.pages):
            page = document.load_page(page_index)
            native_text = page.get_text("text", sort=True)
            native_confidence = _native_text_confidence(native_text)
            ocr_text: str | None = None
            ocr_confidence: Decimal | None = None
            if (page_classification.requires_ocr or force_ocr) and ocr_reader is not None:
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                ocr_text, ocr_confidence = ocr_reader(pixmap.tobytes("png"), page_index + 1)
                any_ocr_used = True

            if ocr_text is None:
                selected_text, selected_source = native_text, "NATIVE_TEXT"
            elif (
                native_text.strip()
                and ocr_confidence is not None
                and native_confidence >= ocr_confidence
            ):
                selected_text, selected_source = native_text, "NATIVE_TEXT"
                any_native_verified = True
            else:
                selected_text, selected_source = ocr_text, "OCR"
                any_native_verified = bool(native_text.strip()) or any_native_verified
            pages.append(
                ExtractedPDFPage(
                    page_number=page_index + 1,
                    native_text=native_text,
                    native_confidence=native_confidence,
                    ocr_text=ocr_text,
                    ocr_confidence=ocr_confidence,
                    selected_text=selected_text,
                    selected_source=selected_source,
                )
            )

        method = (
            PDFExtractionMethod.OCR_VERIFIED
            if any_ocr_used and any_native_verified
            else PDFExtractionMethod.OCR_FALLBACK
            if any_ocr_used
            else PDFExtractionMethod.NATIVE_TEXT
        )
        return PDFTextExtraction(classification, method, tuple(pages))
    finally:
        document.close()
