from __future__ import annotations

from io import BytesIO

import imagehash
from PIL import Image


class PillowPerceptualHasher:
    def fingerprint(self, source: bytes, media_type: str) -> str:
        if media_type not in {"image/jpeg", "image/png"}:
            raise ValueError("Perceptual image hashing requires a rendered image page")
        with Image.open(BytesIO(source)) as image:
            return str(imagehash.phash(image.convert("RGB")))
