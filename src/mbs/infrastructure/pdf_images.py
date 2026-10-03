from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import cv2
import numpy as np
import pymupdf
from PIL import Image

from mbs.domain.pdf_extraction import (
    _DEFAULT_IMAGE_MAX_BYTES,
    _DEFAULT_IMAGE_MAX_DIMENSION_PX,
    EmbeddedPDFImage,
)
from mbs.domain.receipt_image_regions import (
    _is_header_logo_region,
    _match_image_to_receipt_item,
    _pdf_text_regions,
    _raster_media_type,
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
    try:
        items_value = receipt_document.get("items")
        items = items_value if isinstance(items_value, list) else []
        candidates: list[EmbeddedPDFImage] = []
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            page_width, page_height = float(page.rect.width), float(page.rect.height)
            page_area = max(page.rect.get_area(), 1)
            page_text = page.get_text("dict")
            text_regions = _pdf_text_regions(page_text)
            for block in page_text.get("blocks", []):
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
                    or (
                        Image.MAX_IMAGE_PIXELS is not None
                        and width * height > Image.MAX_IMAGE_PIXELS
                    )
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
    finally:
        document.close()


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
