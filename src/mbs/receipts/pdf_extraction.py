from __future__ import annotations

import re
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

import cv2
import numpy as np
import pymupdf
import pytesseract
from PIL import Image
from pytesseract import Output


class PDFContentKind(StrEnum):
    SELECTABLE_TEXT = "SELECTABLE_TEXT"
    IMAGE_ONLY = "IMAGE_ONLY"
    MIXED = "MIXED"


class PDFExtractionMethod(StrEnum):
    NATIVE_TEXT = "NATIVE_TEXT"
    OCR_FALLBACK = "OCR_FALLBACK"
    OCR_VERIFIED = "OCR_VERIFIED"


class OCRUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class PDFPageClassification:
    page_number: int
    selectable_text_chars: int
    embedded_image_count: int
    largest_image_coverage: Decimal
    full_page_image: bool
    native_confidence: Decimal
    requires_ocr: bool


@dataclass(frozen=True)
class PDFClassification:
    content_kind: PDFContentKind
    has_selectable_text: bool
    has_embedded_images: bool
    has_single_full_page_image: bool
    requires_ocr: bool
    pages: tuple[PDFPageClassification, ...]


@dataclass(frozen=True)
class ExtractedPDFPage:
    page_number: int
    native_text: str
    native_confidence: Decimal
    ocr_text: str | None
    ocr_confidence: Decimal | None
    selected_text: str
    selected_source: str


@dataclass(frozen=True)
class PDFTextExtraction:
    classification: PDFClassification
    method: PDFExtractionMethod
    pages: tuple[ExtractedPDFPage, ...]

    @property
    def selected_text(self) -> str:
        return "\n\f\n".join(page.selected_text for page in self.pages)


@dataclass(frozen=True)
class EmbeddedPDFImage:
    image_bytes: bytes
    media_type: str
    page_number: int
    region: tuple[float, float, float, float]
    page_width: float
    page_height: float
    pixel_width: int
    pixel_height: int
    item_index: int | None


OCRPageReader = Callable[[bytes, int], tuple[str, Decimal]]

_DEFAULT_IMAGE_MAX_BYTES = 10_000_000
_DEFAULT_IMAGE_MAX_DIMENSION_PX = 10_000
_LOW_CONFIDENCE_THRESHOLD = Decimal("0.62")
_MIN_NATIVE_TEXT_CHARS = 40
_STRUCTURAL_CUES = (
    "order",
    "receipt",
    "date",
    "item",
    "quantity",
    "qty",
    "subtotal",
    "tax",
    "total",
)


def classify_pdf(source: bytes) -> PDFClassification:
    if not source.startswith(b"%PDF-"):
        raise ValueError("Receipt PDF signature is invalid")
    try:
        document = pymupdf.open(stream=source, filetype="pdf")
    except (pymupdf.FileDataError, ValueError) as error:
        raise ValueError("Receipt PDF cannot be opened") from error
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


def extract_embedded_pdf_images(
    source: bytes,
    receipt_document: Mapping[str, Any],
    minimum_dimension_px: int,
    max_image_bytes: int = _DEFAULT_IMAGE_MAX_BYTES,
    max_dimension_px: int = _DEFAULT_IMAGE_MAX_DIMENSION_PX,
) -> tuple[EmbeddedPDFImage, ...]:
    if minimum_dimension_px <= 0 or max_image_bytes <= 0 or max_dimension_px <= 0:
        raise ValueError("Receipt image limits must be positive")
    document = pymupdf.open(stream=source, filetype="pdf")
    items_value = receipt_document.get("items")
    items = items_value if isinstance(items_value, list) else []
    candidates: list[EmbeddedPDFImage] = []
    for page_index in range(document.page_count):
        page = document.load_page(page_index)
        page_width, page_height = float(page.rect.width), float(page.rect.height)
        page_area = max(page.rect.get_area(), 1)
        text_regions = _pdf_text_regions(page.get_text("dict"))
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 1:
                continue
            image_bytes = block.get("image")
            width, height = block.get("width"), block.get("height")
            bbox = block.get("bbox")
            if (
                not isinstance(image_bytes, bytes)
                or not isinstance(width, int)
                or not isinstance(height, int)
                or not isinstance(bbox, tuple)
                or len(bbox) != 4
                or min(width, height) < minimum_dimension_px
                or max(width, height) > max_dimension_px
                or len(image_bytes) > max_image_bytes
                or (Image.MAX_IMAGE_PIXELS is not None and width * height > Image.MAX_IMAGE_PIXELS)
            ):
                continue
            x0, y0, x1, y1 = (float(value) for value in bbox)
            image_area = max(x1 - x0, 0) * max(y1 - y0, 0)
            if image_area / page_area >= 0.80:
                continue
            if _is_header_logo_region(x0, y0, x1, y1, page_width, page_height):
                continue
            if _is_decorative_or_barcode_image(image_bytes, width, height):
                continue
            media_type = _raster_media_type(image_bytes)
            if media_type is None:
                continue
            item_index = _match_image_to_receipt_item(
                items, text_regions, (x0, y0, x1, y1), page_index + 1
            )
            candidates.append(
                EmbeddedPDFImage(
                    image_bytes=image_bytes,
                    media_type=media_type,
                    page_number=page_index + 1,
                    region=(x0, y0, x1, y1),
                    page_width=page_width,
                    page_height=page_height,
                    pixel_width=width,
                    pixel_height=height,
                    item_index=item_index,
                )
            )
    return tuple(candidates)


def _pdf_text_regions(document_text: dict[str, Any]) -> list[tuple[str, tuple[float, ...]]]:
    regions: list[tuple[str, tuple[float, ...]]] = []
    for block in document_text.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = " ".join(str(span.get("text", "")) for span in line.get("spans", []))
            bbox = line.get("bbox")
            if text.strip() and isinstance(bbox, tuple) and len(bbox) == 4:
                regions.append((text, tuple(float(value) for value in bbox)))
    return regions


def _match_image_to_receipt_item(
    items: list[Any],
    text_regions: list[tuple[str, tuple[float, ...]]],
    image_region: tuple[float, float, float, float],
    page_number: int,
) -> int | None:
    matches: set[int] = set()
    image_y0, image_y1 = image_region[1], image_region[3]
    for item_index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        item_page = item.get("source_page", item.get("page_number"))
        if isinstance(item_page, int) and item_page != page_number:
            continue
        description = _normalized_region_text(str(item.get("description", "")))
        if len(description) < 4:
            continue
        for text, region in text_regions:
            normalized_text = _normalized_region_text(text)
            if description not in normalized_text:
                continue
            text_y0, text_y1 = region[1], region[3]
            vertical_gap = max(0.0, max(image_y0, text_y0) - min(image_y1, text_y1))
            if vertical_gap <= max(image_y1 - image_y0, text_y1 - text_y0) * 0.35:
                matches.add(item_index)
                break
    return next(iter(matches)) if len(matches) == 1 else None


def _normalized_region_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _raster_media_type(image_bytes: bytes) -> str | None:
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return None


def _is_header_logo_region(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    page_width: float,
    page_height: float,
) -> bool:
    image_width = x1 - x0
    image_height = y1 - y0
    return y1 <= page_height * 0.12 and (
        image_width >= page_width * 0.20 or image_width / max(image_height, 1) >= 1.8
    )


def _is_decorative_or_barcode_image(image_bytes: bytes, width: int, height: int) -> bool:
    if max(width, height) / max(min(width, height), 1) >= 8:
        return True
    image_array = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if image_array is None:
        return False
    if cv2.QRCodeDetector().detect(image_array)[0]:
        return True
    if width < height * 1.8:
        return False
    grayscale = image_array.astype(np.float32)
    horizontal_transitions = float(np.abs(np.diff(grayscale.mean(axis=0))).mean())
    vertical_transitions = float(np.abs(np.diff(grayscale.mean(axis=1))).mean())
    return horizontal_transitions > 24 and horizontal_transitions > vertical_transitions * 1.7


def extract_pdf_text(
    source: bytes,
    ocr_reader: OCRPageReader | None = None,
    *,
    force_ocr: bool = False,
) -> PDFTextExtraction:
    classification = classify_pdf(source)
    document = pymupdf.open(stream=source, filetype="pdf")
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


def merge_field_candidates(
    native_fields: Mapping[str, Any],
    native_confidence: Mapping[str, Decimal],
    ocr_fields: Mapping[str, Any],
    ocr_confidence: Mapping[str, Decimal],
) -> tuple[dict[str, Any], dict[str, str]]:
    merged: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for field in dict.fromkeys((*native_fields, *ocr_fields)):
        native_value = native_fields.get(field)
        ocr_value = ocr_fields.get(field)
        native_present = native_value is not None and native_value != ""
        ocr_present = ocr_value is not None and ocr_value != ""
        if not native_present and not ocr_present:
            merged[field] = None
            sources[field] = "MISSING"
        elif not native_present:
            merged[field], sources[field] = ocr_value, "OCR"
        elif not ocr_present:
            merged[field], sources[field] = native_value, "NATIVE_TEXT"
        elif ocr_confidence.get(field, Decimal("0")) > native_confidence.get(field, Decimal("0")):
            merged[field], sources[field] = ocr_value, "OCR"
        else:
            merged[field], sources[field] = native_value, "NATIVE_TEXT"
    return merged, sources


def _visible_text(value: str) -> str:
    return "".join(character for character in value if character.isprintable()).strip()


def _native_text_confidence(text: str) -> Decimal:
    visible = _visible_text(text)
    if not visible:
        return Decimal("0")
    words = [word for word in visible.split() if any(character.isalnum() for character in word)]
    folded = visible.casefold()
    cues = sum(cue in folded for cue in _STRUCTURAL_CUES)
    word_score = min(Decimal(len(words)) / Decimal("45"), Decimal("1"))
    cue_score = Decimal(cues) / Decimal("5")
    replacement_penalty = min(
        Decimal(visible.count("\ufffd")) / Decimal(max(len(visible), 1)),
        Decimal("0.5"),
    )
    score = word_score * Decimal("0.4") + cue_score * Decimal("0.6")
    return max(Decimal("0"), min(score - replacement_penalty, Decimal("1")))


class LocalTesseractReader:
    def __init__(
        self, language: str = "eng", minimum_confidence: Decimal = Decimal("0.10")
    ) -> None:
        self.language = language
        self.minimum_confidence = minimum_confidence

    def __call__(self, page_png: bytes, _page_number: int) -> tuple[str, Decimal]:
        if shutil.which(pytesseract.pytesseract.tesseract_cmd) is None:
            raise OCRUnavailableError("Tesseract executable is not installed")
        image_array = cv2.imdecode(np.frombuffer(page_png, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if image_array is None:
            raise ValueError("Rendered PDF page could not be decoded")
        enlarged = cv2.resize(image_array, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
        _, normalized = cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        image = Image.fromarray(normalized)
        data = pytesseract.image_to_data(
            image,
            lang=self.language,
            output_type=Output.DICT,
            config="--psm 6",
        )
        confidences = [
            Decimal(value) / Decimal("100")
            for value, word in zip(data["conf"], data["text"], strict=True)
            if word.strip() and value not in {"-1", ""}
        ]
        confidence = (
            sum(confidences, Decimal("0")) / Decimal(len(confidences))
            if confidences
            else Decimal("0")
        )
        text = pytesseract.image_to_string(image, lang=self.language, config="--psm 6")
        if confidence < self.minimum_confidence:
            return text, confidence
        return text, confidence
