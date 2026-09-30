from datetime import UTC, datetime, timedelta
from typing import Any

from mbs.receipts.repository import InMemoryReceiptRepository
from mbs.receipts.tasks import (
    InMemoryOCRJobStore,
    JobStatus,
    LocalOCREngine,
    OCRJobProcessor,
    ProcessStatus,
)


def _document(transaction_number: str = "TC-700") -> dict[str, Any]:
    return {
        "receipt": {
            "store": "Synthetic Market",
            "date": "2026-09-30",
            "time": "14:05:06",
            "transaction_number": transaction_number,
            "total": "1.00",
        },
        "items": [{"description": "Milk", "line_total": "1.00"}],
    }


def test_local_ocr_boundary_stamps_provider_metadata() -> None:
    engine = LocalOCREngine(lambda source, media_type: _document())

    document = engine.extract(b"synthetic", "image/png")

    assert document["metadata"] == {
        "provider": "local-tesseract-opencv",
        "schema_version": "local-ocr-v1",
    }


def test_job_lease_prevents_concurrent_duplicate_processing() -> None:
    jobs = InMemoryOCRJobStore()
    job = jobs.get_or_create("job-1", b"synthetic", "image/png")
    now = datetime(2026, 9, 30, tzinfo=UTC)

    lease = timedelta(minutes=5)
    assert jobs.claim(job.job_key, now, lease) is job
    assert jobs.claim(job.job_key, now, lease) is None


def test_failed_ocr_retries_then_succeeds_idempotently() -> None:
    calls = 0

    def flaky_extractor(source: bytes, media_type: str) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic OCR failure")
        return _document()

    jobs = InMemoryOCRJobStore()
    repository = InMemoryReceiptRepository()
    processor = OCRJobProcessor(
        LocalOCREngine(flaky_extractor),
        jobs,
        repository,
        now=lambda: datetime(2026, 9, 30, tzinfo=UTC),
    )
    processor.enqueue("job-2", b"synthetic", "image/png")

    assert processor.process("job-2") is ProcessStatus.RETRY
    assert processor.process("job-2") is ProcessStatus.SUCCEEDED
    assert processor.process("job-2") is ProcessStatus.SUCCEEDED
    assert calls == 2
    assert jobs.jobs["job-2"].status is JobStatus.SUCCEEDED


def test_repeated_receipt_id_is_marked_duplicate_without_overwrite() -> None:
    jobs = InMemoryOCRJobStore()
    repository = InMemoryReceiptRepository()
    processor = OCRJobProcessor(
        LocalOCREngine(lambda source, media_type: _document()),
        jobs,
        repository,
    )
    processor.enqueue("job-3", b"one", "image/png")
    processor.enqueue("job-4", b"two", "image/png")

    assert processor.process("job-3") is ProcessStatus.SUCCEEDED
    assert processor.process("job-4") is ProcessStatus.DUPLICATE
    assert jobs.jobs["job-4"].status is JobStatus.DUPLICATE
