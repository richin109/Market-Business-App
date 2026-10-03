from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbs.domain.receipt_uploads import (
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_MAX_IMAGE_DIMENSION_PX,
    DEFAULT_PHASH_THRESHOLD,
    UploadResult,
    UploadStatus,
    _source_sha256,
    validate_upload_bytes,
)
from mbs.errors import NotFoundError
from mbs.infrastructure.images import validate_receipt_image
from mbs.models import AuditLog, ReceiptOutboxEvent
from mbs.receipts.duplicates import (
    InMemoryPerceptualDuplicateStore,
    PendingDuplicate,
    PerceptualDuplicateStore,
    PerceptualHasher,
)
from mbs.receipts.persistence import create_upload
from mbs.receipts.storage import (
    MalwareScanner,
    ProtectedFileStore,
    ScanStatus,
)
from mbs.repositories.receipt_uploads import ReceiptUploadRepository

repository = ReceiptUploadRepository()


class ReceiptUploadService:
    def __init__(
        self,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_image_dimension_px: int = DEFAULT_MAX_IMAGE_DIMENSION_PX,
        file_store: ProtectedFileStore | None = None,
        malware_scanner: MalwareScanner | None = None,
        perceptual_hasher: PerceptualHasher | None = None,
        perceptual_store: PerceptualDuplicateStore | None = None,
        perceptual_threshold: int = DEFAULT_PHASH_THRESHOLD,
    ) -> None:
        if max_file_bytes <= 0 or max_image_dimension_px <= 0:
            raise ValueError("Upload byte and image dimension limits must be positive")
        self._max_file_bytes = max_file_bytes
        self._max_image_dimension_px = max_image_dimension_px
        self._file_store = file_store
        self._malware_scanner = malware_scanner
        self._perceptual_hasher = perceptual_hasher
        self._perceptual_store = perceptual_store or InMemoryPerceptualDuplicateStore()
        self._perceptual_threshold = perceptual_threshold

    @property
    def max_file_bytes(self) -> int:
        return self._max_file_bytes

    def upload(
        self,
        session: Session,
        source: bytes,
        media_type: str,
        uploaded_by: int,
    ) -> UploadResult:
        self._validate_source(source, media_type)
        source_sha256 = _source_sha256(source)
        existing = repository.source_hash(session, source_sha256)
        if existing is not None:
            existing_status = (
                UploadStatus.POSSIBLE_DUPLICATE
                if existing.processing_status == UploadStatus.POSSIBLE_DUPLICATE.value
                else UploadStatus.EXACT_DUPLICATE
            )
            return UploadResult(
                source_sha256=source_sha256,
                status=existing_status,
                upload_pk=existing.upload_pk,
                file_key=existing.file_key,
                idempotent=True,
            )

        scan_status: ScanStatus | None = None
        if media_type == "application/pdf":
            if self._malware_scanner is None:
                return UploadResult(source_sha256, UploadStatus.SCAN_PENDING)
            scan_status = self._malware_scanner.scan(source)
            if scan_status is ScanStatus.UNAVAILABLE:
                return UploadResult(source_sha256, UploadStatus.SCAN_PENDING)
            if scan_status is ScanStatus.INFECTED:
                repository.add(
                    session,
                    AuditLog(
                        event_type="RECEIPT_UPLOAD_MALWARE_REJECTED",
                        actor=str(uploaded_by),
                        entity_type="ReceiptSource",
                        entity_id=source_sha256,
                        details=f"media_type={media_type}; bytes={len(source)}",
                    ),
                )
                return UploadResult(source_sha256, UploadStatus.MALWARE_REJECTED)

        fingerprint: str | None = None
        if self._perceptual_hasher is not None and media_type.startswith("image/"):
            fingerprint = self._perceptual_hasher.fingerprint(source, media_type)
        matched_source = (
            self._perceptual_store.find_near(fingerprint, self._perceptual_threshold)
            if fingerprint is not None
            else None
        )
        if self._file_store is None:
            raise RuntimeError("Protected file storage is not configured")
        staging_key = self._file_store.stage(source_sha256, source, media_type)
        file_key = self._file_store.key_for(source_sha256, media_type)

        try:
            with repository.savepoint(session):
                upload = create_upload(
                    session,
                    source_sha256,
                    file_key,
                    media_type,
                    len(source),
                    uploaded_by,
                )
                upload.staging_file_key = staging_key
                upload.scan_status = scan_status.value if scan_status is not None else "NOT_SCANNED"
                upload.perceptual_hash = fingerprint
                repository.add(
                    session,
                    AuditLog(
                        event_type="RECEIPT_UPLOAD_ACCEPTED",
                        actor=str(uploaded_by),
                        entity_type="ReceiptUpload",
                        entity_id=upload.upload_pk,
                        details=(
                            f"media_type={media_type}; bytes={len(source)}; "
                            f"scan_status={upload.scan_status}"
                        ),
                    ),
                )
                if media_type.startswith("image/"):
                    repository.add(
                        session,
                        AuditLog(
                            event_type="RECEIPT_UPLOAD_NOT_SCANNED",
                            actor=str(uploaded_by),
                            entity_type="ReceiptUpload",
                            entity_id=upload.upload_pk,
                            details="D-68 validated JPEG/PNG no-scan boundary",
                        ),
                    )
                if matched_source is not None and fingerprint is not None:
                    upload.processing_status = UploadStatus.POSSIBLE_DUPLICATE.value
                    upload.duplicate_status = UploadStatus.POSSIBLE_DUPLICATE.value
                    self._perceptual_store.hold(
                        source_sha256,
                        PendingDuplicate(source, media_type, fingerprint),
                    )
                    repository.add(
                        session,
                        AuditLog(
                            event_type="RECEIPT_UPLOAD_POSSIBLE_DUPLICATE",
                            actor=str(uploaded_by),
                            entity_type="ReceiptUpload",
                            entity_id=upload.upload_pk,
                            details=f"matched_source_sha256={matched_source}",
                        ),
                    )
                    result_status = UploadStatus.POSSIBLE_DUPLICATE
                else:
                    repository.add(
                        session,
                        ReceiptOutboxEvent(
                            upload_pk=upload.upload_pk,
                            event_type="PROCESS_RECEIPT_UPLOAD",
                        ),
                    )
                    result_status = UploadStatus.QUEUED
                repository.flush(session)
        except IntegrityError:
            existing = repository.source_hash(session, source_sha256)
            if existing is None:
                raise
            return UploadResult(
                source_sha256,
                UploadStatus.EXACT_DUPLICATE,
                existing.upload_pk,
                existing.file_key,
                idempotent=True,
            )

        return UploadResult(
            source_sha256=source_sha256,
            status=result_status,
            upload_pk=upload.upload_pk,
            file_key=file_key,
            matched_source_sha256=matched_source,
        )

    def resolve_possible_duplicate(
        self,
        session: Session,
        upload_pk: str,
        reviewer_id: int,
        process_as_new: bool,
    ) -> UploadResult:
        upload = repository.upload_for_update(session, upload_pk)
        if upload is None:
            raise NotFoundError("Receipt upload not found")
        if upload.duplicate_status != UploadStatus.POSSIBLE_DUPLICATE.value:
            raise ValueError("Receipt upload has no pending near match")
        pending = self._perceptual_store.take_pending(upload.source_sha256)
        if pending is None:
            if self._file_store is None or self._perceptual_hasher is None:
                raise RuntimeError("Near-match recovery is not configured")
            source = self._file_store.read(upload.staging_file_key or upload.file_key)
            pending = PendingDuplicate(
                source,
                upload.media_type,
                self._perceptual_hasher.fingerprint(source, upload.media_type),
            )
        if not process_as_new:
            upload.processing_status = "DUPLICATE"
            upload.duplicate_status = "CONFIRMED_DUPLICATE"
            upload.perceptual_hash = None
            repository.add(
                session,
                AuditLog(
                    event_type="RECEIPT_UPLOAD_DUPLICATE_CONFIRMED",
                    actor=str(reviewer_id),
                    entity_type="ReceiptUpload",
                    entity_id=upload.upload_pk,
                    details="Manager confirmed the source was already imported",
                ),
            )
            return UploadResult(
                upload.source_sha256,
                UploadStatus.EXACT_DUPLICATE,
                upload.upload_pk,
                upload.file_key,
            )
        upload.processing_status = UploadStatus.QUEUED.value
        upload.duplicate_status = "PROCESS_AS_NEW"
        upload.perceptual_hash = pending.fingerprint
        repository.add(
            session,
            ReceiptOutboxEvent(
                upload_pk=upload.upload_pk,
                event_type="PROCESS_RECEIPT_UPLOAD",
            ),
        )
        repository.add(
            session,
            AuditLog(
                event_type="RECEIPT_UPLOAD_NEAR_MATCH_RESOLVED",
                actor=str(reviewer_id),
                entity_type="ReceiptUpload",
                entity_id=upload.upload_pk,
                details="Manager approved processing as a new source",
            ),
        )
        return UploadResult(
            upload.source_sha256,
            UploadStatus.QUEUED,
            upload.upload_pk,
            upload.file_key,
        )

    def index_committed_upload(self, session: Session, upload_pk: str) -> None:
        upload = repository.get_upload(session, upload_pk)
        if (
            upload is not None
            and upload.perceptual_hash is not None
            and upload.processing_status == UploadStatus.QUEUED.value
            and upload.duplicate_status != UploadStatus.POSSIBLE_DUPLICATE.value
        ):
            self._perceptual_store.save(upload.source_sha256, upload.perceptual_hash)

    def read_protected_source(self, file_key: str) -> bytes:
        if self._file_store is None:
            raise RuntimeError("Protected file storage is not configured")
        return self._file_store.read(file_key)

    def _validate_source(self, source: bytes, media_type: str) -> None:
        validate_upload_bytes(source, media_type, self._max_file_bytes)
        if media_type.startswith("image/"):
            validate_receipt_image(source, self._max_image_dimension_px)


def initialize_perceptual_store(session: Session, store: PerceptualDuplicateStore) -> int:
    from mbs.services.settings import read_setting

    threshold = read_setting(session, "phash_duplicate_threshold")
    if threshold is None:
        raise RuntimeError("The phash_duplicate_threshold setting must not be NULL")
    for source_sha256, fingerprint in repository.accepted_fingerprints(session):
        if fingerprint is not None:
            store.save(source_sha256, fingerprint)
    return int(threshold)
