from __future__ import annotations

import shutil
from decimal import Decimal

import cv2
import numpy as np
import pytesseract
from PIL import Image
from pytesseract import Output

from mbs.domain.pdf_extraction import OCRUnavailableError


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
