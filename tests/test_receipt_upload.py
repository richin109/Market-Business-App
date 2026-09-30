from typing import Any

import pytest

from mbs.receipts.upload import (
    InMemoryReceiptIdStore,
    InMemorySourceHashStore,
    ReceiptUploadService,
    UploadStatus,
)


class MockOCREngine:
    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document
        self.calls: list[tuple[bytes, str]] = []

    def extract(self, source: bytes, media_type: str) -> dict[str, Any]:
        self.calls.append((source, media_type))
        return self.document


class FailingOCREngine(MockOCREngine):
    def extract(self, source: bytes, media_type: str) -> dict[str, Any]:
        self.calls.append((source, media_type))
        raise RuntimeError("synthetic OCR failure")


def _document() -> dict[str, object]:
    return {
        "receipt": {
            "store": "Synthetic Market",
            "date": "2026-09-30",
            "time": "14:05:06",
            "transaction_number": "TC-99",
            "total": "1.00",
        },
        "items": [{"description": "Milk", "line_total": "1.00"}],
    }


def test_upload_calls_ocr_once_and_rejects_exact_duplicate_before_ocr() -> None:
    engine = MockOCREngine(_document())
    service = ReceiptUploadService(engine)

    source = b"\x89PNG\r\n\x1a\nsynthetic-receipt"
    first = service.upload(source, "image/png")
    duplicate = service.upload(source, "image/png")

    assert first.status is UploadStatus.ACCEPTED
    assert first.receipt is not None
    assert duplicate.status is UploadStatus.EXACT_DUPLICATE
    assert duplicate.receipt is None
    assert len(engine.calls) == 1


def test_shared_hash_store_rejects_duplicate_across_service_instances() -> None:
    source_hash_store = InMemorySourceHashStore()
    first_engine = MockOCREngine(_document())
    second_engine = MockOCREngine(_document())
    first_service = ReceiptUploadService(first_engine, source_hash_store=source_hash_store)
    second_service = ReceiptUploadService(second_engine, source_hash_store=source_hash_store)
    source = b"\x89PNG\r\n\x1a\nshared-source"

    first = first_service.upload(source, "image/png")
    duplicate = second_service.upload(source, "image/png")

    assert first.status is UploadStatus.ACCEPTED
    assert duplicate.status is UploadStatus.EXACT_DUPLICATE
    assert len(first_engine.calls) == 1
    assert second_engine.calls == []


def test_different_sources_with_same_receipt_id_are_rejected() -> None:
    engine = MockOCREngine(_document())
    service = ReceiptUploadService(engine, receipt_id_store=InMemoryReceiptIdStore())
    first_source = b"\x89PNG\r\n\x1a\nfirst-source"
    second_source = b"\x89PNG\r\n\x1a\nsecond-source"

    first = service.upload(first_source, "image/png")
    duplicate = service.upload(second_source, "image/png")

    assert first.status is UploadStatus.ACCEPTED
    assert duplicate.status is UploadStatus.RECEIPT_ID_DUPLICATE
    assert duplicate.receipt is None
    assert len(engine.calls) == 2


def test_accepted_receipt_can_be_retrieved_from_repository() -> None:
    engine = MockOCREngine(_document())
    service = ReceiptUploadService(engine)
    source = b"\x89PNG\r\n\x1a\nretrievable-source"

    result = service.upload(source, "image/png")

    assert result.receipt is not None
    assert service.get_receipt(result.receipt.receipt_id) == result.receipt


def test_failed_ocr_releases_hash_for_a_safe_retry() -> None:
    failing_engine = FailingOCREngine(_document())
    source_hash_store = InMemorySourceHashStore()
    failing_service = ReceiptUploadService(
        failing_engine,
        source_hash_store=source_hash_store,
    )
    successful_engine = MockOCREngine(_document())
    successful_service = ReceiptUploadService(
        successful_engine,
        source_hash_store=source_hash_store,
    )
    source = b"\x89PNG\r\n\x1a\nretryable-source"

    with pytest.raises(RuntimeError):
        failing_service.upload(source, "image/png")

    result = successful_service.upload(source, "image/png")

    assert result.status is UploadStatus.ACCEPTED
    assert len(successful_engine.calls) == 1


@pytest.mark.parametrize(
    ("source", "media_type"),
    [
        (b"receipt", "text/plain"),
        (b"", "image/png"),
        (b"not-a-png", "image/png"),
    ],
)
def test_upload_rejects_invalid_source_before_ocr(source: bytes, media_type: str) -> None:
    engine = MockOCREngine(_document())
    service = ReceiptUploadService(engine)

    with pytest.raises(ValueError):
        service.upload(source, media_type)

    assert engine.calls == []


@pytest.mark.parametrize(
    ("source", "media_type"),
    [
        (b"\xff\xd8\xffsynthetic", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\nsynthetic", "image/png"),
        (b"%PDF-1.7 synthetic", "application/pdf"),
    ],
)
def test_upload_accepts_supported_file_signatures(source: bytes, media_type: str) -> None:
    engine = MockOCREngine(
        {
            "receipt": {
                "store": "Synthetic Market",
                "date": "2026-09-30",
                "time": "14:05:06",
                "transaction_number": "TC-100",
                "total": "1.00",
            },
            "items": [{"description": "Milk", "line_total": "1.00"}],
        }
    )
    service = ReceiptUploadService(engine)

    result = service.upload(source, media_type)

    assert result.status is UploadStatus.ACCEPTED
