from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from mbs.domain.item_images import ImageOwnerKind
from mbs.errors import ConflictError, NotFoundError, UnavailableError, UnsupportedMediaError
from mbs.models import AuditLog, MediaAssetLink, ReceiptItem, User
from mbs.receipts.upload import ReceiptUploadService
from mbs.repositories.item_images import GalleryPersistenceConflictError
from mbs.repositories.receipt_images import ReceiptImageRepository

repository = ReceiptImageRepository()


def decide_receipt_image_candidate(
    session: Session, user: User, receipt_pk: str, candidate_id: int, data: dict[str, Any]
) -> dict[str, object]:
    receipt = repository.get_receipt(session, receipt_pk, active_only=True, lock=True)
    if receipt is None:
        raise NotFoundError("Image candidate not found")
    candidate = repository.candidate_for_update(session, candidate_id, receipt_pk)
    if candidate is None:
        raise NotFoundError("Image candidate not found")
    if data["decision"] == "REJECT":
        reason = (data["reason"] or "").strip()
        if not reason:
            raise ValueError("A rejection reason is required")
        if candidate.status == "REJECTED":
            return {"candidate_id": candidate.id, "status": candidate.status, "idempotent": True}
        if candidate.status != "PENDING":
            raise ConflictError("Candidate is already confirmed")
        candidate.status = "REJECTED"
        candidate.rejection_reason = reason
        repository.add(
            session,
            AuditLog(
                event_type="RECEIPT_IMAGE_CANDIDATE_REJECTED",
                actor=str(user.id),
                entity_type="MediaAssetLink",
                entity_id=str(candidate.id),
                details=f"source_id={candidate.source_id}; reason_required=true",
            ),
        )
        repository.commit(session)
        return {"candidate_id": candidate.id, "status": candidate.status, "idempotent": False}
    if candidate.status == "CONFIRMED":
        return {"candidate_id": candidate.id, "status": candidate.status, "idempotent": True}
    if candidate.status != "PENDING":
        raise ConflictError("Rejected candidate cannot be confirmed")
    current_line = (
        repository.receipt_line_for_update(session, candidate.receipt_item_id, receipt_pk)
        if candidate.receipt_item_id is not None
        else None
    )
    if current_line is not None and data["receipt_item_id"] not in {None, current_line.id}:
        raise ConflictError("An associated image candidate cannot be reassigned to another line")
    receipt_item_id = data["receipt_item_id"] or candidate.receipt_item_id
    line: ReceiptItem | None = current_line
    if receipt_item_id is not None and (line is None or line.id != receipt_item_id):
        line = repository.receipt_line_for_update(session, receipt_item_id, receipt_pk)
    if line is None:
        raise ConflictError("Choose a receipt line before confirming this image")
    store_item = (
        repository.store_item_for_update(session, line.store_item_id)
        if line.store_item_id is not None
        else None
    )
    if line.store_item_id is not None and store_item is None:
        raise ConflictError("The receipt line's store item is unavailable")
    owner_kind: ImageOwnerKind
    owner_id: str | None
    if store_item is not None and store_item.mapping_confirmed and (line.item_id is not None):
        owner_kind, owner_id = ("ITEM", line.item_id)
    elif store_item is not None:
        owner_kind, owner_id = ("STORE_ITEM", store_item.store_item_id)
    else:
        owner_kind, owner_id = ("ITEM", line.item_id)
    if owner_id is None:
        raise ConflictError("Map this receipt line before confirming its image")
    owner = repository.get_owner(session, owner_kind, str(owner_id), lock=True)
    if owner is None:
        raise ConflictError("The receipt line's item mapping is unavailable")
    primary = repository.get_primary(session, owner_kind, str(owner_id), lock=True)
    same_asset = repository.find_active_asset_link(
        session, owner_kind, str(owner_id), candidate.asset_sha256, lock=True
    )
    if same_asset is None and primary is not None and (data["replace_primary"] is None):
        repository.rollback(session)
        return {
            "candidate_id": candidate_id,
            "replace_prompt_required": True,
            "primary_label": owner_kind,
        }
    replace_primary = data["replace_primary"] is True
    becomes_primary = (
        same_asset.is_primary if same_asset is not None else primary is None or replace_primary
    )
    try:
        with repository.savepoint(session):
            if primary is not None and same_asset is None and replace_primary:
                primary.is_primary = False
            if same_asset is not None and primary is None:
                same_asset.is_primary = True
            candidate.status = "CONFIRMED"
            if candidate.receipt_item_id is None:
                candidate.receipt_item_id = line.id
            if same_asset is None:
                repository.add(
                    session,
                    MediaAssetLink(
                        asset_sha256=candidate.asset_sha256,
                        owner_kind=owner_kind,
                        owner_id=str(owner_id),
                        status="CONFIRMED",
                        is_primary=becomes_primary,
                        source_id=candidate.source_id,
                        receipt_item_id=line.id,
                        source_page=candidate.source_page,
                        source_region=candidate.source_region,
                        created_by=user.id,
                    ),
                )
            repository.add(
                session,
                AuditLog(
                    event_type="RECEIPT_IMAGE_CANDIDATE_CONFIRMED",
                    actor=str(user.id),
                    entity_type="MediaAssetLink",
                    entity_id=str(candidate.id),
                    details=(
                        f"receipt_item_id={line.id}; owner_kind={owner_kind}; "
                        f"is_primary={becomes_primary}"
                    ),
                ),
            )
            repository.flush(session)
    except GalleryPersistenceConflictError as error:
        raise ConflictError(
            "The primary image changed; refresh and review this candidate again"
        ) from error
    repository.commit(session)
    return {
        "candidate_id": candidate.id,
        "status": candidate.status,
        "is_primary": becomes_primary,
        "idempotent": False,
    }


def get_receipt_source_content(
    session: Session, service: ReceiptUploadService, receipt_pk: str, source_id: int
) -> tuple[bytes, str]:
    source_row = repository.protected_source(session, source_id, receipt_pk)
    if source_row is None:
        raise NotFoundError("Receipt source not found")
    _, upload = source_row
    if upload.media_type not in {"application/pdf", "image/jpeg", "image/png"}:
        raise UnsupportedMediaError("Unsupported Media Type")
    try:
        content = service.read_protected_source(upload.file_key)
    except FileNotFoundError as error:
        raise NotFoundError("Protected source is unavailable") from error
    except (OSError, RuntimeError, ValueError) as error:
        raise UnavailableError("Source viewing unavailable") from error
    return (content, upload.media_type)


def get_receipt_image_candidate_thumbnail(
    session: Session, service: ReceiptUploadService, receipt_pk: str, candidate_id: int
) -> tuple[bytes, str]:
    row = repository.candidate_image(session, candidate_id, receipt_pk)
    if row is None:
        raise NotFoundError("Image candidate not found")
    _, asset = row
    if asset.ingest_status != "READY":
        raise UnavailableError("Image candidate is not ready")
    try:
        content = service.read_protected_source(asset.thumbnail_file_key)
    except (OSError, RuntimeError, ValueError) as error:
        raise UnavailableError("Protected image candidate is unavailable") from error
    return (content, asset.thumbnail_media_type)
