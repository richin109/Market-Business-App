from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mbs.domain.receipt_jobs import MAX_ATTEMPTS, PERSISTED_UPLOAD_LEASE
from mbs.domain.receipt_normalization import OCREngine, normalize_receipt
from mbs.domain.stores import StoreResolutionRequired
from mbs.models import AuditLog, StoreResolutionHold
from mbs.receipts.pdf_extraction import EmbeddedPDFImage
from mbs.receipts.storage import LocalProtectedFileStore
from mbs.repositories.receipt_jobs import ReceiptJobRepository, is_receipt_id_collision
from mbs.services.category_rules import load_category_rules
from mbs.services.media_assets import MediaAssetService
from mbs.services.receipt_intake import persist_extracted_receipt, persist_source_candidate

repository = ReceiptJobRepository()


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
        with repository.transaction(self._session_factory) as session:
            upload = repository.upload_for_update(session, upload_pk)
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
                with repository.session(self._session_factory) as settings_session:
                    enabled = repository.image_setting(
                        settings_session, "receipt_image_extraction_enabled"
                    )
                    minimum_dimension = repository.image_setting(
                        settings_session, "receipt_image_min_dimension_px"
                    )
                    max_image_bytes_setting = repository.image_setting(
                        settings_session, "image_max_bytes"
                    )
                    max_dimension_setting = repository.image_setting(
                        settings_session, "image_max_dimension_px"
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
            with repository.transaction(self._session_factory) as session:
                upload = repository.upload_for_update(session, upload_pk)
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
                    repository.add(
                        session,
                        AuditLog(
                            event_type="RECEIPT_OCR_EXTRACTION_REVIEW_REQUIRED",
                            entity_type="ReceiptUpload",
                            entity_id=upload_pk,
                            details=str(issue_codes)[:1000],
                        ),
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
                        existing_receipt = repository.receipt_identity(
                            session, extracted.receipt_id, lock=True
                        )
                        if existing_receipt is not None:
                            existing_source = repository.source_id(
                                session, upload.upload_pk, existing_receipt.receipt_pk
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
                            with repository.savepoint(session):
                                persist_extracted_receipt(
                                    session,
                                    extracted,
                                    upload,
                                    increment_ocr_attempts=False,
                                )
                        except IntegrityError as error:
                            if not is_receipt_id_collision(error):
                                raise
                            duplicate = repository.receipt_identity(
                                session, extracted.receipt_id, lock=True
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
                    with repository.savepoint(session):
                        receipt = persist_extracted_receipt(
                            session,
                            extracted,
                            upload,
                            increment_ocr_attempts=False,
                        )
                    if image_extraction_failed:
                        repository.add(
                            session,
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
                            ),
                        )
                    if image_candidates:
                        source_row = repository.source(
                            session, upload.upload_pk, receipt.receipt_pk
                        )
                        if source_row is None:
                            raise ValueError("Persisted receipt source is missing")
                        receipt_items = list(repository.lines(session, receipt.receipt_pk))
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
                    repository.add(
                        session,
                        StoreResolutionHold(
                            upload_pk=upload.upload_pk,
                            reason=str(error),
                            raw_ocr_document=document,
                        ),
                    )
                    repository.add(
                        session,
                        AuditLog(
                            event_type="RECEIPT_STORE_RESOLUTION_HELD",
                            entity_type="ReceiptUpload",
                            entity_id=upload.upload_pk,
                            details=str(error)[:1000],
                        ),
                    )
                    return "REVIEW"
                except IntegrityError as error:
                    if not is_receipt_id_collision(error):
                        raise
                    duplicate = repository.receipt_identity(
                        session, extracted.receipt_id, lock=False
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
            with repository.transaction(self._session_factory) as session:
                upload = repository.upload_for_update(session, upload_pk)
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
                    repository.add(
                        session,
                        AuditLog(
                            event_type="RECEIPT_OCR_FAILED",
                            entity_type="ReceiptUpload",
                            entity_id=upload_pk,
                            details=str(error)[:1000],
                        ),
                    )
            raise
