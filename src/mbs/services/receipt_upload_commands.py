from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from mbs.domain.receipt_uploads import UploadResult, UploadStatus
from mbs.repositories.receipt_uploads import ReceiptUploadRepository
from mbs.services.receipt_uploads import ReceiptUploadService

repository = ReceiptUploadRepository()


def upload_and_complete(
    session: Session,
    service: ReceiptUploadService,
    source: bytes,
    media_type: str,
    actor_id: int,
    dispatch: Callable[[], None],
) -> UploadResult:
    result = service.upload(session, source, media_type, actor_id)
    if result.status is UploadStatus.SCAN_PENDING:
        return result
    repository.commit(session)
    if result.upload_pk is not None and result.status is UploadStatus.QUEUED:
        service.index_committed_upload(session, result.upload_pk)
    if result.status in {UploadStatus.QUEUED, UploadStatus.EXACT_DUPLICATE}:
        dispatch()
    return result


def resolve_near_match_and_complete(
    session: Session,
    service: ReceiptUploadService,
    upload_pk: str,
    actor_id: int,
    process_as_new: bool,
    dispatch: Callable[[], None],
) -> UploadResult:
    result = service.resolve_possible_duplicate(session, upload_pk, actor_id, process_as_new)
    repository.commit(session)
    if result.status is UploadStatus.QUEUED:
        if result.upload_pk is not None:
            service.index_committed_upload(session, result.upload_pk)
        dispatch()
    return result


class ReceiptUploadBatch:
    def __init__(self, service: ReceiptUploadService, actor_id: int, max_bytes: int) -> None:
        self._service = service
        self._actor_id = actor_id
        self._max_bytes = max_bytes
        self._results: list[dict[str, object]] = []
        self._accepted_uploads: list[str] = []
        self._total_bytes = 0

    def reject_file(self, filename: str, status: str, detail: str) -> None:
        self._results.append({"filename": filename, "status": status, "detail": detail})

    def add_file(self, session: Session, filename: str, source: bytes, media_type: str) -> None:
        if len(source) > self._service.max_file_bytes:
            self.reject_file(filename, "TOO_LARGE", "File exceeds the per-file size limit")
            return
        if self._total_bytes + len(source) > self._max_bytes:
            self.reject_file(filename, "BATCH_LIMIT_EXCEEDED", "Batch exceeds the size limit")
            return
        self._total_bytes += len(source)
        try:
            result = self._service.upload(session, source, media_type, self._actor_id)
        except ValueError as error:
            self.reject_file(filename, "INVALID", str(error))
            return
        self._results.append(
            {
                "filename": filename,
                "status": result.status.value,
                "upload_pk": result.upload_pk,
                "source_sha256": result.source_sha256,
                "idempotent": result.idempotent,
            }
        )
        if result.status is UploadStatus.QUEUED and result.upload_pk is not None:
            self._accepted_uploads.append(result.upload_pk)

    def commit(self, session: Session) -> None:
        repository.commit(session)

    def finish(self, session: Session, dispatch: Callable[[], None]) -> dict[str, object]:
        for upload_pk in self._accepted_uploads:
            self._service.index_committed_upload(session, upload_pk)
        if self._accepted_uploads:
            dispatch()
        return {
            "file_count": len(self._results),
            "total_bytes": self._total_bytes,
            "files": self._results,
        }
