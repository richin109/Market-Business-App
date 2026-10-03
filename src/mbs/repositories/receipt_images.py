from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs.models import (
    MediaAsset,
    MediaAssetLink,
    Receipt,
    ReceiptItem,
    ReceiptSource,
    ReceiptUpload,
    StoreItem,
)
from mbs.repositories.item_images import ItemImageGalleryRepository
from mbs.repositories.receipts import ReceiptRepository


class ReceiptImageRepository(ItemImageGalleryRepository, ReceiptRepository):
    def candidate_for_update(
        self, session: Session, candidate_id: int, receipt_pk: str
    ) -> MediaAssetLink | None:
        return session.scalar(
            select(MediaAssetLink)
            .join(ReceiptSource, ReceiptSource.id == MediaAssetLink.source_id)
            .where(
                MediaAssetLink.id == candidate_id,
                MediaAssetLink.owner_kind == "RECEIPT_LINE_CANDIDATE",
                ReceiptSource.receipt_pk == receipt_pk,
                ReceiptSource.association_kind != "REJECTED",
            )
            .with_for_update()
        )

    def receipt_line_for_update(
        self, session: Session, line_id: int, receipt_pk: str
    ) -> ReceiptItem | None:
        return session.scalar(
            select(ReceiptItem)
            .where(ReceiptItem.id == line_id, ReceiptItem.receipt_pk == receipt_pk)
            .with_for_update()
        )

    def store_item_for_update(self, session: Session, store_item_id: str) -> StoreItem | None:
        return session.scalar(
            select(StoreItem).where(StoreItem.store_item_id == store_item_id).with_for_update()
        )

    def candidate_image(
        self, session: Session, candidate_id: int, receipt_pk: str
    ) -> tuple[MediaAssetLink, MediaAsset] | None:
        return session.execute(
            select(MediaAssetLink, MediaAsset)
            .join(MediaAsset, MediaAsset.asset_sha256 == MediaAssetLink.asset_sha256)
            .join(ReceiptSource, ReceiptSource.id == MediaAssetLink.source_id)
            .join(Receipt, Receipt.receipt_pk == ReceiptSource.receipt_pk)
            .where(
                MediaAssetLink.id == candidate_id,
                MediaAssetLink.owner_kind == "RECEIPT_LINE_CANDIDATE",
                ReceiptSource.receipt_pk == receipt_pk,
                ReceiptSource.association_kind != "REJECTED",
                Receipt.deleted_at.is_(None),
            )
        ).one_or_none()

    def protected_source(
        self, session: Session, source_id: int, receipt_pk: str
    ) -> tuple[ReceiptSource, ReceiptUpload] | None:
        return session.execute(
            select(ReceiptSource, ReceiptUpload)
            .join(ReceiptUpload, ReceiptUpload.upload_pk == ReceiptSource.upload_pk)
            .join(Receipt, Receipt.receipt_pk == ReceiptSource.receipt_pk)
            .where(
                ReceiptSource.id == source_id,
                ReceiptSource.receipt_pk == receipt_pk,
                Receipt.deleted_at.is_(None),
            )
        ).one_or_none()

    def rollback(self, session: Session) -> None:
        session.rollback()
