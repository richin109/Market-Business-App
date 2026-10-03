from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

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
