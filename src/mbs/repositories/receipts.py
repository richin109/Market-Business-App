from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mbs.models import (
    Base,
    Item,
    Receipt,
    ReceiptCorrection,
    ReceiptExpenseDraft,
    ReceiptItem,
    ReceiptLineApproval,
    ReceiptRoutingRecord,
    StoreItem,
)


class ReceiptRepository:
    def get_line(
        self, session: Session, line_id: int, *, lock: bool = False, refresh: bool = False
    ) -> ReceiptItem | None:
        if not lock and not refresh:
            return session.get(ReceiptItem, line_id)
        query = select(ReceiptItem).where(ReceiptItem.id == line_id)
        if lock:
            query = query.with_for_update()
        if refresh:
            query = query.execution_options(populate_existing=True)
        return session.scalar(query)

    def get_receipt(
        self, session: Session, receipt_pk: str, *, active_only: bool = False, lock: bool = False
    ) -> Receipt | None:
        query = select(Receipt).where(Receipt.receipt_pk == receipt_pk)
        if active_only:
            query = query.where(Receipt.deleted_at.is_(None))
        return session.scalar(query.with_for_update() if lock else query)

    def latest_approval(
        self, session: Session, line_id: int, *, lock: bool = False
    ) -> ReceiptLineApproval | None:
        query = select(ReceiptLineApproval).where(ReceiptLineApproval.receipt_item_id == line_id)
        query = query.order_by(ReceiptLineApproval.approval_version.desc()).limit(1)
        return session.scalar(query.with_for_update() if lock else query)

    def approval_event(self, session: Session, event_id: str) -> ReceiptLineApproval | None:
        return session.scalar(
            select(ReceiptLineApproval).where(ReceiptLineApproval.source_event_id == event_id)
        )

    def active_line_subtotal(self, session: Session, receipt_pk: str) -> Decimal:
        return session.scalar(
            select(func.coalesce(func.sum(ReceiptItem.line_total), 0)).where(
                ReceiptItem.receipt_pk == receipt_pk,
                ReceiptItem.is_excluded.is_(False),
            )
        ) or Decimal("0")

    def get_store_item(self, session: Session, store_item_id: str) -> StoreItem | None:
        return session.get(StoreItem, store_item_id)

    def get_item(self, session: Session, item_id: str) -> Item | None:
        return session.get(Item, item_id)

    def correction_event(self, session: Session, event_id: str) -> ReceiptCorrection | None:
        return session.scalar(
            select(ReceiptCorrection).where(ReceiptCorrection.source_event_id == event_id)
        )

    def expense_route(
        self, session: Session, line_id: int, approval_version: int, destination: str
    ) -> ReceiptRoutingRecord | None:
        return session.scalar(
            select(ReceiptRoutingRecord)
            .where(
                ReceiptRoutingRecord.receipt_item_id == line_id,
                ReceiptRoutingRecord.destination_kind == destination,
                ReceiptRoutingRecord.approved_version == approval_version,
            )
            .with_for_update()
        )

    def expense_draft(self, session: Session, route_id: int) -> ReceiptExpenseDraft | None:
        return session.scalar(
            select(ReceiptExpenseDraft)
            .where(ReceiptExpenseDraft.routing_record_id == route_id)
            .with_for_update()
        )

    def lines(self, session: Session, receipt_pk: str) -> list[ReceiptItem]:
        return list(
            session.scalars(
                select(ReceiptItem)
                .where(ReceiptItem.receipt_pk == receipt_pk)
                .order_by(ReceiptItem.id)
            )
        )

    def approved_line_count(self, session: Session, receipt_pk: str) -> int:
        return (
            session.scalar(
                select(func.count(ReceiptLineApproval.id))
                .join(ReceiptItem, ReceiptItem.id == ReceiptLineApproval.receipt_item_id)
                .where(ReceiptItem.receipt_pk == receipt_pk)
            )
            or 0
        )

    def add(self, session: Session, record: Base) -> None:
        session.add(record)

    def add_all(self, session: Session, records: Sequence[Base]) -> None:
        session.add_all(records)

    def flush(self, session: Session) -> None:
        session.flush()

    def commit(self, session: Session) -> None:
        session.commit()

    def line_id_in_receipt(self, session: Session, line_id: int, receipt_pk: str) -> int | None:
        return session.scalar(
            select(ReceiptItem.id).where(
                ReceiptItem.id == line_id,
                ReceiptItem.receipt_pk == receipt_pk,
            )
        )

    def routing_record(
        self, session: Session, line_id: int, destination: str, approval_version: int
    ) -> ReceiptRoutingRecord | None:
        return session.scalar(
            select(ReceiptRoutingRecord).where(
                ReceiptRoutingRecord.receipt_item_id == line_id,
                ReceiptRoutingRecord.destination_kind == destination,
                ReceiptRoutingRecord.approved_version == approval_version,
            )
        )

    @contextmanager
    def savepoint(self, session: Session) -> Iterator[None]:
        with session.begin_nested():
            yield
