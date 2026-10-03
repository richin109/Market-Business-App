from __future__ import annotations

from mbs.celery_app import celery_app
from mbs.db import SessionLocal
from mbs.domain.receipt_jobs import MAX_ATTEMPTS as MAX_ATTEMPTS
from mbs.domain.receipt_jobs import PERSISTED_UPLOAD_LEASE as PERSISTED_UPLOAD_LEASE
from mbs.infrastructure.receipt_ocr import LocalOCREngine as LocalOCREngine
from mbs.infrastructure.receipt_ocr import LocalReceiptOCREngine as LocalReceiptOCREngine
from mbs.receipts.storage import LocalProtectedFileStore, receipt_storage_root
from mbs.services.receipt_outbox import dispatch_pending_uploads
from mbs.services.receipt_processing import PersistedUploadProcessor as PersistedUploadProcessor

_persisted_processor: PersistedUploadProcessor | None = None


def configure_persisted_processor(processor: PersistedUploadProcessor) -> None:
    global _persisted_processor
    _persisted_processor = processor


def _ensure_persisted_processor() -> PersistedUploadProcessor:
    global _persisted_processor
    if _persisted_processor is None:
        configure_persisted_processor(
            PersistedUploadProcessor(
                SessionLocal,
                LocalProtectedFileStore(receipt_storage_root()),
                LocalReceiptOCREngine(),
            )
        )
    processor = _persisted_processor
    if processor is None:
        raise RuntimeError("Persisted receipt processor could not be initialized")
    return processor


@celery_app.task(
    name="mbs.receipts.process_upload",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
    acks_late=True,
    reject_on_worker_lost=True,
)  # type: ignore[untyped-decorator]
def process_receipt_upload(upload_pk: str) -> str:
    return _ensure_persisted_processor().process(upload_pk)


@celery_app.task(
    name="mbs.receipts.dispatch_pending_uploads",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)  # type: ignore[untyped-decorator]
def dispatch_pending_receipt_uploads() -> int:
    return dispatch_pending_uploads(
        SessionLocal, LocalProtectedFileStore(receipt_storage_root()), process_receipt_upload.delay
    )
