from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw

from mbs.receipts.duplicates import (
    InMemoryPerceptualDuplicateStore,
    PillowPerceptualHasher,
)
from mbs.receipts.upload import ReceiptUploadService, UploadStatus


class MockOCREngine:
    def __init__(self) -> None:
        self.calls = 0

    def extract(self, source: bytes, media_type: str) -> dict[str, Any]:
        self.calls += 1
        return {
            "receipt": {
                "store": "Synthetic Market",
                "date": "2026-09-30",
                "time": "14:05:06",
                "transaction_number": f"TC-{950 + self.calls}",
                "total": "1.00",
            },
            "items": [{"description": "Milk", "line_total": "1.00"}],
        }


def _image_bytes(offset: int = 0) -> bytes:
    image = Image.new("RGB", (64, 64), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((16 + offset, 16, 48 + offset, 48), fill="black")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_near_duplicate_is_held_before_ocr_and_can_be_resolved() -> None:
    engine = MockOCREngine()
    store = InMemoryPerceptualDuplicateStore()
    service = ReceiptUploadService(
        engine,
        perceptual_hasher=PillowPerceptualHasher(),
        perceptual_store=store,
    )

    first = service.upload(_image_bytes(), "image/png")
    possible = service.upload(_image_bytes(1), "image/png")

    assert first.status is UploadStatus.ACCEPTED
    assert possible.status is UploadStatus.POSSIBLE_DUPLICATE
    assert possible.matched_source_sha256 == first.source_sha256
    assert engine.calls == 1

    resolved = service.resolve_possible_duplicate(possible.source_sha256, process_as_new=True)

    assert resolved.status is UploadStatus.ACCEPTED
    assert engine.calls == 2


def test_manager_can_resolve_possible_duplicate_as_already_imported() -> None:
    engine = MockOCREngine()
    service = ReceiptUploadService(
        engine,
        perceptual_hasher=PillowPerceptualHasher(),
        perceptual_store=InMemoryPerceptualDuplicateStore(),
    )
    first = service.upload(_image_bytes(), "image/png")
    possible = service.upload(_image_bytes(1), "image/png")

    resolved = service.resolve_possible_duplicate(possible.source_sha256, process_as_new=False)

    assert resolved.status is UploadStatus.EXACT_DUPLICATE
    assert first.receipt is not None
    assert service.get_receipt(first.receipt.receipt_id) is not None
    assert engine.calls == 1
