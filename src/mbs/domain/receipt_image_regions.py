from __future__ import annotations

import re
from typing import Any


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
