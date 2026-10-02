from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mbs.celery_app import celery_app
from mbs.db import SessionLocal
from mbs.media_assets import MediaAssetService
from mbs.models import (
    AuditLog,
    Receipt,
    ReceiptItem,
    ReceiptOutboxEvent,
    ReceiptSource,
    ReceiptUpload,
    Setting,
    StoreResolutionHold,
)
from mbs.receipts.category_rules import load_category_rules
from mbs.receipts.ocr import OCREngine, normalize_receipt
from mbs.receipts.pdf_extraction import (
    EmbeddedPDFImage,
    LocalTesseractReader,
    OCRPageReader,
    extract_embedded_pdf_images,
)
from mbs.receipts.pdf_parsing import extract_receipt_document
from mbs.receipts.persistence import persist_extracted_receipt, persist_source_candidate
from mbs.receipts.storage import LocalProtectedFileStore, receipt_storage_root
from mbs.stores import StoreResolutionRequired

PERSISTED_UPLOAD_LEASE = timedelta(minutes=15)
MAX_ATTEMPTS = 3


class LocalOCREngine:
    """Adapt a configured extractor without inventing provider metadata."""

    def __init__(self, extractor: Callable[[bytes, str], dict[str, Any]]) -> None:
        self._extractor = extractor

    def extract(self, source: bytes, media_type: str) -> dict[str, Any]:
        return self._extractor(source, media_type)


class LocalReceiptOCREngine:
    def __init__(self, page_reader: OCRPageReader | None = None) -> None:
        self._page_reader = page_reader or LocalTesseractReader()

    def extract(self, source: bytes, media_type: str) -> dict[str, Any]:
        return extract_receipt_document(source, media_type, self._page_reader)

    def extract_image_candidates(
        self,
        source: bytes,
        receipt_document: dict[str, Any],
        minimum_dimension_px: int,
        max_image_bytes: int,
        max_dimension_px: int,
    ) -> tuple[EmbeddedPDFImage, ...]:
        return extract_embedded_pdf_images(
            source,
            receipt_document,
            minimum_dimension_px,
            max_image_bytes,
            max_dimension_px,
        )


_persisted_processor: PersistedUploadProcessor | None = None


class PersistedUploadProcessor:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        file_store: LocalProtectedFileStore,
        engine: OCREngine,
    ) -> None:
        self._session_factory = session_factory
        self._file_store = file_store
        self._engine = engine

    def process(self, upload_pk: str) -> str:
        lease_token = str(uuid4())
        now = datetime.now(UTC)
        file_key: str
        media_type: str
        with self._session_factory.begin() as session:
            upload = session.scalar(
                select(ReceiptUpload).where(ReceiptUpload.upload_pk == upload_pk).with_for_update()
            )
            if upload is None:
                raise ValueError("Receipt upload not found")
            if upload.processing_status in {"SUCCEEDED", "DUPLICATE", "REVIEW"}:
                return upload.processing_status
            lease_until = upload.processing_lease_until
            if lease_until is not None and lease_until.tzinfo is None:
                lease_until = lease_until.replace(tzinfo=UTC)
            if (
                upload.processing_status == "RUNNING"
                and lease_until is not None
                and lease_until > now
            ):
                return "RUNNING"
            upload.processing_status = "RUNNING"
            upload.processing_lease_token = lease_token
            upload.processing_lease_until = now + PERSISTED_UPLOAD_LEASE
            upload.ocr_attempts += 1
            file_key = upload.file_key
            media_type = upload.media_type

        try:
            source = self._file_store.read(file_key)
            document = self._engine.extract(source, media_type)
            image_candidates: tuple[EmbeddedPDFImage, ...] = ()
            image_extraction_failed = False
            image_extractor = getattr(self._engine, "extract_image_candidates", None)
            if (
                media_type == "application/pdf"
                and not isinstance(document.get("orders"), list)
                and document.get("review_required") is not True
                and callable(image_extractor)
            ):
                with self._session_factory() as settings_session:
                    enabled = settings_session.scalar(
                        select(Setting).where(Setting.key == "receipt_image_extraction_enabled")
                    )
                    minimum_dimension = settings_session.scalar(
                        select(Setting).where(Setting.key == "receipt_image_min_dimension_px")
                    )
                    max_image_bytes_setting = settings_session.scalar(
                        select(Setting).where(Setting.key == "image_max_bytes")
                    )
                    max_dimension_setting = settings_session.scalar(
                        select(Setting).where(Setting.key == "image_max_dimension_px")
                    )
                    if (
                        enabled is None
                        or minimum_dimension is None
                        or max_image_bytes_setting is None
                        or max_dimension_setting is None
                    ):
                        image_extraction_failed = True
                    elif str(enabled.value).strip().casefold() in {"yes", "true", "1"}:
                        try:
                            minimum_dimension_px = int(minimum_dimension.value or "0")
                            max_image_bytes = int(max_image_bytes_setting.value or "0")
                            max_dimension_px = int(max_dimension_setting.value or "0")
                        except ValueError:
                            image_extraction_failed = True
                        else:
                            if min(minimum_dimension_px, max_image_bytes, max_dimension_px) <= 0:
                                image_extraction_failed = True
                            else:
                                try:
                                    image_candidates = image_extractor(
                                        source,
                                        document,
                                        minimum_dimension_px,
                                        max_image_bytes,
                                        max_dimension_px,
                                    )
                                except Exception:
                                    image_extraction_failed = True
            with self._session_factory.begin() as session:
                upload = session.scalar(
                    select(ReceiptUpload)
                    .where(ReceiptUpload.upload_pk == upload_pk)
                    .with_for_update()
                )
                if upload is None:
                    raise ValueError("Receipt upload not found")
                if upload.processing_status in {"SUCCEEDED", "DUPLICATE", "REVIEW"}:
                    return upload.processing_status
                if upload.processing_lease_token != lease_token:
                    return upload.processing_status
                if document.get("review_required") is True:
                    upload.processing_status = "REVIEW"
                    upload.processing_lease_token = None
                    upload.processing_lease_until = None
                    upload.ocr_extraction_result = document
                    metadata = document.get("metadata", {})
                    if isinstance(metadata, dict):
                        upload.ocr_provider = str(metadata.get("provider", "unknown"))
                        upload.ocr_schema_version = str(metadata.get("schema_version", "unknown"))
                        page_count = metadata.get("page_count")
                        if isinstance(page_count, int):
                            upload.page_count = page_count
                    extraction = document.get("extraction", {})
                    issue_codes = (
                        extraction.get("issues", []) if isinstance(extraction, dict) else []
                    )
                    session.add(
                        AuditLog(
                            event_type="RECEIPT_OCR_EXTRACTION_REVIEW_REQUIRED",
                            entity_type="ReceiptUpload",
                            entity_id=upload_pk,
                            details=str(issue_codes)[:1000],
                        )
                    )
                    return "REVIEW"
                order_documents = document.get("orders")
                if isinstance(order_documents, list):
                    if not order_documents:
                        raise ValueError("Segmented receipt document contains no orders")
                    upload.ocr_extraction_result = document
                    source_review_required = False
                    category_rules = load_category_rules(session)
                    for order_document in order_documents:
                        if (
                            not isinstance(order_document, dict)
                            or order_document.get("review_required") is True
                        ):
                            raise ValueError("Segmented receipt document is invalid")
                        extracted = normalize_receipt(order_document, category_rules)
                        existing_receipt = session.scalar(
                            select(Receipt)
                            .where(Receipt.receipt_id == extracted.receipt_id)
                            .with_for_update()
                        )
                        if existing_receipt is not None:
                            existing_source = session.scalar(
                                select(ReceiptSource.id).where(
                                    ReceiptSource.upload_pk == upload.upload_pk,
                                    ReceiptSource.receipt_pk == existing_receipt.receipt_pk,
                                )
                            )
                            if existing_source is None:
                                persist_source_candidate(
                                    session,
                                    extracted,
                                    upload,
                                    existing_receipt,
                                )
                                source_review_required = True
                            continue
                        try:
                            with session.begin_nested():
                                persist_extracted_receipt(
                                    session,
                                    extracted,
                                    upload,
                                    increment_ocr_attempts=False,
                                )
                        except IntegrityError as error:
                            if not _is_receipt_id_collision(error):
                                raise
                            duplicate = session.scalar(
                                select(Receipt)
                                .where(Receipt.receipt_id == extracted.receipt_id)
                                .with_for_update()
                            )
                            if duplicate is None:
                                raise
                            persist_source_candidate(session, extracted, upload, duplicate)
                            source_review_required = True

                    upload.processing_lease_token = None
                    upload.processing_lease_until = None
                    if source_review_required:
                        upload.processing_status = "REVIEW"
                        upload.duplicate_status = "SOURCE_ASSOCIATION_REVIEW"
                        return "REVIEW"
                    upload.processing_status = "SUCCEEDED"
                    return "SUCCEEDED"
                extracted = normalize_receipt(document, load_category_rules(session))
                try:
                    with session.begin_nested():
                        receipt = persist_extracted_receipt(
                            session,
                            extracted,
                            upload,
                            increment_ocr_attempts=False,
                        )
                    if image_extraction_failed:
                        session.add(
                            AuditLog(
                                event_type="RECEIPT_IMAGE_EXTRACTION_FAILED",
                                actor=(
                                    str(upload.uploaded_by)
                                    if upload.uploaded_by is not None
                                    else None
                                ),
                                entity_type="ReceiptSource",
                                entity_id=str(receipt.receipt_pk),
                                details="IMAGE_EXTRACTION_FAILED",
                            )
                        )
                    if image_candidates:
                        source_row = session.scalar(
                            select(ReceiptSource).where(
                                ReceiptSource.upload_pk == upload.upload_pk,
                                ReceiptSource.receipt_pk == receipt.receipt_pk,
                            )
                        )
                        if source_row is None:
                            raise ValueError("Persisted receipt source is missing")
                        receipt_items = list(
                            session.scalars(
                                select(ReceiptItem)
                                .where(ReceiptItem.receipt_pk == receipt.receipt_pk)
                                .order_by(ReceiptItem.id)
                            )
                        )
                        MediaAssetService.persist_pdf_image_candidates(
                            session,
                            source_row,
                            image_candidates,
                            receipt_items,
                            self._file_store,
                            upload.uploaded_by,
                        )
                except StoreResolutionRequired as error:
                    upload.processing_status = "REVIEW"
                    upload.processing_lease_token = None
                    upload.processing_lease_until = None
                    session.add(
                        StoreResolutionHold(
                            upload_pk=upload.upload_pk,
                            reason=str(error),
                            raw_ocr_document=document,
                        )
                    )
                    session.add(
                        AuditLog(
                            event_type="RECEIPT_STORE_RESOLUTION_HELD",
                            entity_type="ReceiptUpload",
                            entity_id=upload.upload_pk,
                            details=str(error)[:1000],
                        )
                    )
                    return "REVIEW"
                except IntegrityError as error:
                    if not _is_receipt_id_collision(error):
                        raise
                    duplicate = session.scalar(
                        select(Receipt).where(Receipt.receipt_id == extracted.receipt_id)
                    )
                    if duplicate is None:
                        raise
                    source_row = persist_source_candidate(session, extracted, upload, duplicate)
                    if image_candidates:
                        MediaAssetService.persist_pdf_image_candidates(
                            session,
                            source_row,
                            image_candidates,
                            [],
                            self._file_store,
                            upload.uploaded_by,
                        )
                    return "REVIEW"
                upload.processing_lease_token = None
                upload.processing_lease_until = None
                return "SUCCEEDED"
        except Exception as error:
            with self._session_factory.begin() as session:
                upload = session.scalar(
                    select(ReceiptUpload)
                    .where(ReceiptUpload.upload_pk == upload_pk)
                    .with_for_update()
                )
                if (
                    upload is not None
                    and upload.processing_status == "RUNNING"
                    and upload.processing_lease_token == lease_token
                ):
                    upload.processing_status = (
                        "REVIEW" if upload.ocr_attempts >= MAX_ATTEMPTS else "QUEUED"
                    )
                    upload.processing_lease_token = None
                    upload.processing_lease_until = None
                    session.add(
                        AuditLog(
                            event_type="RECEIPT_OCR_FAILED",
                            entity_type="ReceiptUpload",
                            entity_id=upload_pk,
                            details=str(error)[:1000],
                        )
                    )
            raise


def _is_receipt_id_collision(error: IntegrityError) -> bool:
    constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if constraint_name == "uq_tbl_receipts_receipt_id":
        return True
    return "UNIQUE constraint failed: tbl_receipts.receipt_id" in str(error.orig)


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
    dispatched = 0
    file_store = LocalProtectedFileStore(receipt_storage_root())
    now = datetime.now(UTC)
    with SessionLocal.begin() as session:
        events = session.scalars(
            select(ReceiptOutboxEvent)
            .join(ReceiptUpload, ReceiptUpload.upload_pk == ReceiptOutboxEvent.upload_pk)
            .where(
                or_(
                    ReceiptOutboxEvent.dispatched_at.is_(None),
                    and_(
                        ReceiptUpload.processing_status == "RUNNING",
                        or_(
                            ReceiptUpload.processing_lease_until.is_(None),
                            ReceiptUpload.processing_lease_until <= now,
                        ),
                    ),
                )
            )
            .order_by(ReceiptOutboxEvent.id)
            .limit(50)
            .with_for_update(skip_locked=True)
        ).all()
        for event in events:
            if event.dispatched_at is not None:
                event.dispatched_at = None
                event.last_error = "Worker lease expired; redispatching upload"
            event.dispatch_attempts += 1
            try:
                upload = session.get(ReceiptUpload, event.upload_pk)
                if upload is None:
                    event.last_error = "Receipt upload not found"
                    continue
                if upload.staging_file_key is not None:
                    promoted_key = file_store.promote(
                        upload.staging_file_key,
                        upload.source_sha256,
                        upload.media_type,
                    )
                    if promoted_key != upload.file_key:
                        raise RuntimeError(
                            "Promoted receipt file key did not match its upload record"
                        )
                    upload.staging_file_key = None
                process_receipt_upload.delay(event.upload_pk)
            except Exception as error:
                event.last_error = str(error)[:1000]
                continue
            event.dispatched_at = datetime.now(UTC)
            event.last_error = None
            dispatched += 1
    return dispatched
