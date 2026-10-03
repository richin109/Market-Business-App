from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs.models import (
    Receipt,
    ReceiptCorrectionHold,
    ReceiptItem,
    ReceiptLineApproval,
    ReceiptSource,
    StoreItem,
)
from mbs.repositories.receipts import ReceiptRepository


class ReceiptCorrectionRepository(ReceiptRepository):
    def pending_holds(self, session: Session) -> list[ReceiptCorrectionHold]:
        return list(
            session.scalars(
                select(ReceiptCorrectionHold)
                .where(ReceiptCorrectionHold.status == "PENDING")
                .order_by(ReceiptCorrectionHold.id)
            )
        )

    def hold_event(self, session: Session, event_id: str) -> ReceiptCorrectionHold | None:
        return session.scalar(
            select(ReceiptCorrectionHold).where(ReceiptCorrectionHold.source_event_id == event_id)
        )

    def hold_for_update(self, session: Session, hold_id: int) -> ReceiptCorrectionHold | None:
        return session.scalar(
            select(ReceiptCorrectionHold)
            .where(ReceiptCorrectionHold.id == hold_id)
            .with_for_update()
        )

    def accepted_source(
        self, session: Session, source_id: int, receipt_pk: str
    ) -> ReceiptSource | None:
        return session.scalar(
            select(ReceiptSource).where(
                ReceiptSource.id == source_id,
                ReceiptSource.receipt_pk == receipt_pk,
                ReceiptSource.association_kind.in_(("PRIMARY", "SUPPLEMENT")),
            )
        )

    def store_items(self, session: Session, store_item_ids: set[str]) -> list[StoreItem]:
        return list(
            session.scalars(select(StoreItem).where(StoreItem.store_item_id.in_(store_item_ids)))
        )

    def first_approval_id(self, session: Session, receipt_pk: str) -> int | None:
        return session.scalar(
            select(ReceiptLineApproval.id)
            .join(ReceiptItem, ReceiptItem.id == ReceiptLineApproval.receipt_item_id)
            .where(ReceiptItem.receipt_pk == receipt_pk)
            .limit(1)
        )

    def receipt_collision(
        self, session: Session, receipt_id: str, receipt_pk: str
    ) -> Receipt | None:
        return session.scalar(
            select(Receipt).where(
                Receipt.receipt_id == receipt_id,
                Receipt.receipt_pk != receipt_pk,
            )
        )

    def receipt_collision_pk(
        self, session: Session, receipt_id: str, receipt_pk: str
    ) -> str | None:
        return session.scalar(
            select(Receipt.receipt_pk).where(
                Receipt.receipt_id == receipt_id,
                Receipt.receipt_pk != receipt_pk,
            )
        )

    def unordered_lines(self, session: Session, receipt_pk: str) -> list[ReceiptItem]:
        return list(
            session.scalars(select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt_pk))
        )
