from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from mbs.models import (
    Receipt,
    ReceiptItem,
    ReceiptSource,
    ReceiptUpload,
    Store,
    StoreAliasKey,
    StoreItem,
)
from mbs.repositories.receipts import ReceiptRepository


class ReceiptSourceRepository(ReceiptRepository):
    def store_for_update(self, session: Session, store_id: str) -> Store | None:
        return session.scalar(select(Store).where(Store.store_id == store_id).with_for_update())

    def receipt_event(self, session: Session, event_id: str) -> Receipt | None:
        return session.scalar(select(Receipt).where(Receipt.source_event_id == event_id))

    def first_store_alias(self, session: Session, store_id: str) -> StoreAliasKey | None:
        return session.scalar(
            select(StoreAliasKey)
            .where(StoreAliasKey.store_id == store_id)
            .order_by(StoreAliasKey.normalized_key)
            .limit(1)
        )

    def source_for_update(
        self, session: Session, source_id: int, receipt_pk: str
    ) -> ReceiptSource | None:
        return session.scalar(
            select(ReceiptSource)
            .where(ReceiptSource.id == source_id, ReceiptSource.receipt_pk == receipt_pk)
            .with_for_update()
        )

    def source_event(self, session: Session, event_id: str) -> ReceiptSource | None:
        return session.scalar(
            select(ReceiptSource).where(
                or_(
                    ReceiptSource.decision_event_id == event_id,
                    ReceiptSource.hold_event_id == event_id,
                )
            )
        )

    def upload_for_update(self, session: Session, upload_pk: str) -> ReceiptUpload | None:
        return session.scalar(
            select(ReceiptUpload).where(ReceiptUpload.upload_pk == upload_pk).with_for_update()
        )

    def active_lines(self, session: Session, receipt_pk: str) -> list[ReceiptItem]:
        return list(
            session.scalars(
                select(ReceiptItem)
                .where(ReceiptItem.receipt_pk == receipt_pk, ReceiptItem.is_excluded.is_(False))
                .order_by(ReceiptItem.id)
            )
        )

    def store_items(self, session: Session, store_item_ids: set[str]) -> list[StoreItem]:
        return list(
            session.scalars(select(StoreItem).where(StoreItem.store_item_id.in_(store_item_ids)))
        )
