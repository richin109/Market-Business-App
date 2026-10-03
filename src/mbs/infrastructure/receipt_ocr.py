from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mbs.receipts.pdf_extraction import (
    EmbeddedPDFImage,
    LocalTesseractReader,
    OCRPageReader,
    extract_embedded_pdf_images,
)
from mbs.receipts.pdf_parsing import extract_receipt_document


class LocalOCREngine:
    """Adapt a configured extractor without inventing provider metadata."""

    def __init__(self, extractor: Callable[[bytes, str], dict[str, Any]]) -> None:
        self._extractor = extractor

    def extract(self, source: bytes, media_type: str) -> dict[str, Any]:
        return self._extractor(source, media_type)


class LocalReceiptOCREngine:
    def __init__(self, page_reader: OCRPageReader | None = None) -> None:
        self._page_reader = page_reader or LocalTesseractReader()

    def extract(self, source: bytes, media_type: str) -> dict[str, Any]:
        return extract_receipt_document(source, media_type, self._page_reader)

    def extract_image_candidates(
        self,
        source: bytes,
        receipt_document: dict[str, Any],
        minimum_dimension_px: int,
        max_image_bytes: int,
        max_dimension_px: int,
    ) -> tuple[EmbeddedPDFImage, ...]:
        return extract_embedded_pdf_images(
            source,
            receipt_document,
            minimum_dimension_px,
            max_image_bytes,
            max_dimension_px,
        )
