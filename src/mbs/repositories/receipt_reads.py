from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from mbs.models import (
    Item,
    MediaAsset,
    MediaAssetLink,
    Receipt,
    ReceiptItem,
    ReceiptLineApproval,
    ReceiptSource,
    ReceiptUpload,
    Store,
    StoreItem,
)
from mbs.repositories.receipts import ReceiptRepository


class ReceiptReadRepository(ReceiptRepository):
    def directory_rows(
        self,
        session: Session,
        store: str | None,
        store_id: str | None,
        date_from: date | None,
        date_to: date | None,
        page: int,
        page_size: int,
    ) -> list[tuple[Receipt, int]]:
        filters: list[ColumnElement[bool]] = [Receipt.deleted_at.is_(None)]
        if store is not None:
            filters.append(Receipt.store == store)
        if store_id is not None:
            filters.append(Receipt.store_id == store_id)
        if date_from is not None:
            filters.append(Receipt.receipt_date >= date_from)
        if date_to is not None:
            filters.append(Receipt.receipt_date <= date_to)
        counts = (
            select(ReceiptItem.receipt_pk, func.count(ReceiptItem.id).label("item_count"))
            .where(ReceiptItem.is_excluded.is_(False))
            .group_by(ReceiptItem.receipt_pk)
            .subquery()
        )
        return [
            (receipt, count)
            for receipt, count in session.execute(
                select(Receipt, func.coalesce(counts.c.item_count, 0))
                .outerjoin(counts, counts.c.receipt_pk == Receipt.receipt_pk)
                .where(*filters)
                .order_by(Receipt.receipt_date.desc(), Receipt.receipt_id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ]

    def sources(self, session: Session, receipt_pk: str) -> list[ReceiptSource]:
        return list(
            session.scalars(
                select(ReceiptSource)
                .where(ReceiptSource.receipt_pk == receipt_pk)
                .order_by(ReceiptSource.id)
            )
        )

    def store_items(self, session: Session, ids: set[str]) -> list[StoreItem]:
        return list(session.scalars(select(StoreItem).where(StoreItem.store_item_id.in_(ids))))

    def canonical_items(self, session: Session, ids: set[str]) -> list[Item]:
        return list(session.scalars(select(Item).where(Item.item_id.in_(ids))))

    def approval_versions(self, session: Session, ids: list[int]) -> list[ReceiptLineApproval]:
        return list(
            session.scalars(
                select(ReceiptLineApproval)
                .where(ReceiptLineApproval.receipt_item_id.in_(ids))
                .order_by(ReceiptLineApproval.approval_version)
            )
        )

    def source_uploads(
        self, session: Session, receipt_pk: str
    ) -> list[tuple[ReceiptSource, ReceiptUpload]]:
        return [
            (source, upload)
            for source, upload in session.execute(
                select(ReceiptSource, ReceiptUpload)
                .join(ReceiptUpload, ReceiptUpload.upload_pk == ReceiptSource.upload_pk)
                .where(ReceiptSource.receipt_pk == receipt_pk)
                .order_by(ReceiptSource.id)
            )
        ]

    def source_candidates(
        self, session: Session, ids: list[int]
    ) -> list[tuple[MediaAssetLink, MediaAsset]]:
        return [
            (link, asset)
            for link, asset in session.execute(
                select(MediaAssetLink, MediaAsset)
                .join(MediaAsset, MediaAsset.asset_sha256 == MediaAssetLink.asset_sha256)
                .join(ReceiptSource, ReceiptSource.id == MediaAssetLink.source_id)
                .where(
                    MediaAssetLink.owner_kind == "RECEIPT_LINE_CANDIDATE",
                    MediaAssetLink.source_id.in_(ids),
                    ReceiptSource.association_kind != "REJECTED",
                )
                .order_by(MediaAssetLink.id)
            )
        ]

    def remembered_items(self, session: Session, store_id: str) -> list[StoreItem]:
        return list(
            session.scalars(
                select(StoreItem).where(
                    StoreItem.store_id == store_id,
                    StoreItem.last_disposition.is_not(None),
                )
            )
        )

    def manual_stores(self, session: Session) -> list[Store]:
        return list(
            session.scalars(
                select(Store)
                .where(Store.is_active.is_(True), Store.superseded_by_store_id.is_(None))
                .order_by(Store.display_name, Store.store_id)
            )
        )
