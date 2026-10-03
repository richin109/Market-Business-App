from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbs.domain.media_assets import _sha256
from mbs.models import AuditLog, MediaAssetLink, ReceiptItem, ReceiptSource
from mbs.receipts.pdf_extraction import EmbeddedPDFImage
from mbs.receipts.storage import ProtectedFileStore
from mbs.repositories.media_assets import MediaAssetRepository
from mbs.services.media_assets import MediaAssetService

repository = MediaAssetRepository()


def persist_pdf_image_candidates(
    session: Session,
    source: ReceiptSource,
    candidates: tuple[EmbeddedPDFImage, ...],
    receipt_items: list[ReceiptItem],
    file_store: ProtectedFileStore,
    actor_id: int | None,
) -> list[MediaAssetLink]:
    service = MediaAssetService(file_store)
    created: list[MediaAssetLink] = []
    for candidate in candidates:
        content_sha256 = _sha256(candidate.image_bytes)
        region_key = ":".join(f"{coordinate:.4f}" for coordinate in candidate.region)
        candidate_key = _sha256(
            f"{source.source_sha256}:{candidate.page_number}:{region_key}:{content_sha256}".encode()
        )
        existing_candidate = repository.candidate_key(session, candidate_key)
        if existing_candidate is not None:
            continue

        try:
            asset = service.stage(
                session,
                candidate.image_bytes,
                candidate.media_type,
                actor_id,
            )
        except ValueError:
            repository.add(
                session,
                AuditLog(
                    event_type="RECEIPT_IMAGE_CANDIDATE_INGEST_REJECTED",
                    actor=str(actor_id) if actor_id is not None else None,
                    entity_type="ReceiptSource",
                    entity_id=str(source.id),
                    details=(
                        f"source_id={source.id}; page={candidate.page_number}; "
                        "issue=INVALID_IMAGE_CONTENT"
                    ),
                ),
            )
            continue
        service.promote(session, asset.asset_sha256)
        line = (
            receipt_items[candidate.item_index]
            if candidate.item_index is not None and 0 <= candidate.item_index < len(receipt_items)
            else None
        )
        link = MediaAssetLink(
            asset_sha256=asset.asset_sha256,
            owner_kind="RECEIPT_LINE_CANDIDATE",
            owner_id=candidate_key,
            status="PENDING",
            source_id=source.id,
            receipt_item_id=line.id if line is not None else None,
            source_page=candidate.page_number,
            source_region={
                "bbox": list(candidate.region),
                "page_width": candidate.page_width,
                "page_height": candidate.page_height,
                "pixel_width": candidate.pixel_width,
                "pixel_height": candidate.pixel_height,
                "item_index": candidate.item_index,
            },
            created_by=actor_id,
        )
        try:
            with repository.savepoint(session):
                repository.add(session, link)
                repository.add(
                    session,
                    AuditLog(
                        event_type="RECEIPT_IMAGE_CANDIDATE_CREATED",
                        actor=str(actor_id) if actor_id is not None else None,
                        entity_type="MediaAssetLink",
                        entity_id=candidate_key,
                        details=(
                            f"source_id={source.id}; page={candidate.page_number}; "
                            f"line={line.id if line is not None else 'unassigned'}"
                        ),
                    ),
                )
                repository.flush(session)
        except IntegrityError:
            concurrent_candidate = repository.candidate_key(session, candidate_key)
            if concurrent_candidate is None:
                raise
            continue
        created.append(link)
    return created
