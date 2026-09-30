from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from mbs.celery_app import celery_app
from mbs.receipts.ocr import ExtractedReceipt, OCREngine, normalize_receipt
from mbs.receipts.repository import InMemoryReceiptRepository

LEASE_DURATION = timedelta(minutes=5)
MAX_ATTEMPTS = 3


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    DUPLICATE = "DUPLICATE"
    FAILED = "FAILED"
    REVIEW = "REVIEW"


class ProcessStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    DUPLICATE = "DUPLICATE"
    RETRY = "RETRY"
    REVIEW = "REVIEW"


@dataclass
class OCRJob:
    job_key: str
    source: bytes
    media_type: str
    status: JobStatus = JobStatus.QUEUED
    attempts: int = 0
    lease_until: datetime | None = None
    receipt: ExtractedReceipt | None = None
    error: str | None = None


class OCRJobStore(Protocol):
    def get_or_create(self, job_key: str, source: bytes, media_type: str) -> OCRJob: ...

    def get(self, job_key: str) -> OCRJob: ...

    def claim(self, job_key: str, now: datetime, lease: timedelta) -> OCRJob | None: ...

    def complete(
        self, job: OCRJob, status: JobStatus, receipt: ExtractedReceipt | None
    ) -> None: ...

    def fail(self, job: OCRJob, error: str, review: bool) -> None: ...


class InMemoryOCRJobStore:
    def __init__(self) -> None:
        self.jobs: dict[str, OCRJob] = {}

    def get_or_create(self, job_key: str, source: bytes, media_type: str) -> OCRJob:
        return self.jobs.setdefault(job_key, OCRJob(job_key, source, media_type))

    def get(self, job_key: str) -> OCRJob:
        return self.jobs[job_key]

    def claim(self, job_key: str, now: datetime, lease: timedelta) -> OCRJob | None:
        job = self.jobs[job_key]
        if job.status in {JobStatus.SUCCEEDED, JobStatus.DUPLICATE, JobStatus.REVIEW}:
            return None
        if (
            job.status is JobStatus.RUNNING
            and job.lease_until is not None
            and job.lease_until > now
        ):
            return None
        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.lease_until = now + lease
        return job

    def complete(self, job: OCRJob, status: JobStatus, receipt: ExtractedReceipt | None) -> None:
        job.status = status
        job.lease_until = None
        job.receipt = receipt
        job.error = None

    def fail(self, job: OCRJob, error: str, review: bool) -> None:
        job.status = JobStatus.REVIEW if review else JobStatus.FAILED
        job.lease_until = None
        job.error = error


class LocalOCREngine:
    """Provider-neutral boundary for the future local Tesseract/OpenCV adapter."""

    def __init__(self, extractor: Callable[[bytes, str], dict[str, Any]]) -> None:
        self._extractor = extractor

    def extract(self, source: bytes, media_type: str) -> dict[str, Any]:
        document = self._extractor(source, media_type)
        metadata = document.setdefault("metadata", {})
        metadata.setdefault("provider", "local-tesseract-opencv")
        metadata.setdefault("schema_version", "local-ocr-v1")
        return document


class OCRJobProcessor:
    def __init__(
        self,
        engine: OCREngine,
        job_store: OCRJobStore,
        receipt_repository: InMemoryReceiptRepository,
        now: Callable[[], datetime] | None = None,
        lease: timedelta = LEASE_DURATION,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self._engine = engine
        self._job_store = job_store
        self._receipt_repository = receipt_repository
        self._now = now or (lambda: datetime.now(UTC))
        self._lease = lease
        self._max_attempts = max_attempts

    def enqueue(self, job_key: str, source: bytes, media_type: str) -> OCRJob:
        return self._job_store.get_or_create(job_key, source, media_type)

    def process(self, job_key: str) -> ProcessStatus:
        now = self._now()
        job = self._job_store.claim(job_key, now, self._lease)
        if job is None:
            existing = self._job_store.get(job_key)
            return (
                ProcessStatus.DUPLICATE
                if existing.status is JobStatus.DUPLICATE
                else ProcessStatus.SUCCEEDED
            )
        try:
            receipt = normalize_receipt(self._engine.extract(job.source, job.media_type))
            try:
                self._receipt_repository.save(receipt)
            except ValueError:
                self._job_store.complete(job, JobStatus.DUPLICATE, None)
                return ProcessStatus.DUPLICATE
            self._job_store.complete(job, JobStatus.SUCCEEDED, receipt)
            return ProcessStatus.SUCCEEDED
        except Exception as error:
            review = job.attempts >= self._max_attempts
            self._job_store.fail(job, str(error), review)
            return ProcessStatus.REVIEW if review else ProcessStatus.RETRY


_processor: OCRJobProcessor | None = None


def configure_processor(processor: OCRJobProcessor) -> None:
    global _processor
    _processor = processor


@celery_app.task(name="mbs.receipts.process_upload")  # type: ignore[untyped-decorator]
def process_receipt_upload(job_key: str) -> str:
    if _processor is None:
        raise RuntimeError("OCR processor is not configured")
    return _processor.process(job_key).value
