from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from mbs.models import (
    Base,
    Item,
    ItemMappingEvent,
    Receipt,
    ReceiptItem,
    Store,
    StoreItem,
    StoreItemMapping,
)
from mbs.repositories.query import LIKE_ESCAPE, contains_pattern


class ItemRepository:
    def store_for_update(self, session: Session, store_id: str) -> Store | None:
        return session.scalar(select(Store).where(Store.store_id == store_id).with_for_update())

    def observed_store_item(
        self, session: Session, store_id: str, product_id: str, *, lock: bool = False
    ) -> StoreItem | None:
        query = select(StoreItem).where(
            StoreItem.store_id == store_id, StoreItem.store_product_id == product_id
        )
        return session.scalar(query.with_for_update() if lock else query)

    def get_item(self, session: Session, item_id: str, *, lock: bool = False) -> Item | None:
        if not lock:
            return session.get(Item, item_id)
        return session.scalar(select(Item).where(Item.item_id == item_id).with_for_update())

    def mapping_event(self, session: Session, event_id: str) -> ItemMappingEvent | None:
        return session.scalar(
            select(ItemMappingEvent).where(ItemMappingEvent.source_event_id == event_id)
        )

    def get_store_item(
        self, session: Session, store_item_id: str, *, lock: bool = False, refresh: bool = False
    ) -> StoreItem | None:
        if not lock and not refresh:
            return session.get(StoreItem, store_item_id)
        query = select(StoreItem).where(StoreItem.store_item_id == store_item_id)
        if lock:
            query = query.with_for_update()
        if refresh:
            query = query.execution_options(populate_existing=True)
        return session.scalar(query)

    def current_item_id(self, session: Session, store_item_id: str) -> str | None:
        return session.scalar(
            select(StoreItem.item_id).where(StoreItem.store_item_id == store_item_id)
        )

    def lock_items(self, session: Session, item_ids: set[str]) -> list[Item]:
        return list(
            session.scalars(
                select(Item)
                .where(Item.item_id.in_(item_ids))
                .order_by(Item.item_id)
                .with_for_update()
            )
        )

    def current_mapping(self, session: Session, store_item_id: str) -> StoreItemMapping | None:
        return session.scalar(
            select(StoreItemMapping)
            .where(
                StoreItemMapping.store_item_id == store_item_id,
                StoreItemMapping.effective_to.is_(None),
            )
            .with_for_update()
        )

    def latest_purchase_date(self, session: Session, store_item_id: str) -> date | None:
        return session.scalar(
            select(func.max(Receipt.receipt_date))
            .join(ReceiptItem, ReceiptItem.receipt_pk == Receipt.receipt_pk)
            .where(ReceiptItem.store_item_id == store_item_id)
        )

    def count_store_items(self, session: Session, item_id: str) -> int:
        return (
            session.scalar(
                select(func.count(StoreItem.store_item_id)).where(StoreItem.item_id == item_id)
            )
            or 0
        )

    def mapping_on_date(
        self, session: Session, store_item_id: str, effective_date: date
    ) -> StoreItemMapping | None:
        return session.scalar(
            select(StoreItemMapping)
            .where(
                StoreItemMapping.store_item_id == store_item_id,
                StoreItemMapping.effective_from <= effective_date,
                StoreItemMapping.effective_to.is_(None)
                | (StoreItemMapping.effective_to > effective_date),
            )
            .order_by(StoreItemMapping.effective_from.desc())
            .limit(1)
        )

    def active_items_except(self, session: Session, item_id: str) -> list[Item]:
        return list(
            session.scalars(select(Item).where(Item.is_active.is_(True), Item.item_id != item_id))
        )

    def confirmed_store_items(self, session: Session) -> list[StoreItem]:
        return list(session.scalars(select(StoreItem).where(StoreItem.mapping_confirmed.is_(True))))

    def store_items_for_update(self, session: Session, item_id: str) -> list[StoreItem]:
        return list(
            session.scalars(
                select(StoreItem)
                .where(StoreItem.item_id == item_id)
                .order_by(StoreItem.store_item_id)
                .with_for_update()
            )
        )

    def receipt_line_for_update(self, session: Session, receipt_item_id: int) -> ReceiptItem | None:
        return session.scalar(
            select(ReceiptItem).where(ReceiptItem.id == receipt_item_id).with_for_update()
        )

    def get_receipt(
        self, session: Session, receipt_pk: str, *, active_only: bool = False, lock: bool = False
    ) -> Receipt | None:
        if not active_only and not lock:
            return session.get(Receipt, receipt_pk)
        query = select(Receipt).where(Receipt.receipt_pk == receipt_pk)
        if active_only:
            query = query.where(Receipt.deleted_at.is_(None))
        return session.scalar(query.with_for_update() if lock else query)

    def add(self, session: Session, record: Base) -> None:
        session.add(record)

    def flush(self, session: Session) -> None:
        session.flush()

    @contextmanager
    def savepoint(self, session: Session) -> Iterator[None]:
        with session.begin_nested():
            yield


class ItemCommandRepository:
    def get_item(self, session: Session, item_id: str) -> Item | None:
        return session.get(Item, item_id)

    def get_store_item(self, session: Session, store_item_id: str) -> StoreItem | None:
        return session.get(StoreItem, store_item_id)

    def create_observed_item(self, session: Session, common_name: str | None) -> Item:
        item = Item(common_name=common_name, is_store_observed=True)
        session.add(item)
        session.flush()
        return item

    def commit(self, session: Session) -> None:
        session.commit()


class ItemReadRepository:
    def mapping_rows(self, session: Session) -> list[tuple[StoreItem, Item, Store, date | None]]:
        return [
            (store_item, item, store, last_purchase_date)
            for store_item, item, store, last_purchase_date in session.execute(
                select(StoreItem, Item, Store, func.max(Receipt.receipt_date))
                .join(Item, Item.item_id == StoreItem.item_id)
                .join(Store, Store.store_id == StoreItem.store_id)
                .outerjoin(ReceiptItem, ReceiptItem.store_item_id == StoreItem.store_item_id)
                .outerjoin(
                    Receipt,
                    and_(
                        Receipt.receipt_pk == ReceiptItem.receipt_pk, Receipt.deleted_at.is_(None)
                    ),
                )
                .group_by(StoreItem.store_item_id, Item.item_id, Store.store_id)
                .order_by(Store.display_name, StoreItem.latest_description, StoreItem.store_item_id)
            )
        ]

    def list_items(
        self, session: Session, query: str | None = None, *, active_only: bool = False
    ) -> list[Item]:
        statement = select(Item).order_by(Item.common_name, Item.item_id)
        if active_only:
            statement = statement.where(Item.is_active.is_(True))
        if query:
            statement = statement.where(
                Item.common_name.ilike(contains_pattern(query), escape=LIKE_ESCAPE)
            )
        return list(session.scalars(statement))

    def store_item_counts(self, session: Session) -> dict[str, int]:
        return {
            item_id: count
            for item_id, count in session.execute(
                select(StoreItem.item_id, func.count(StoreItem.store_item_id)).group_by(
                    StoreItem.item_id
                )
            )
        }

    def store_item_rows(
        self, session: Session, query: str | None, unmapped_only: bool
    ) -> list[tuple[StoreItem, Item, str, date | None]]:
        statement = (
            select(StoreItem, Item, Store.display_name, func.max(Receipt.receipt_date))
            .join(Item, Item.item_id == StoreItem.item_id)
            .join(Store, Store.store_id == StoreItem.store_id)
            .outerjoin(ReceiptItem, ReceiptItem.store_item_id == StoreItem.store_item_id)
            .outerjoin(
                Receipt,
                and_(Receipt.receipt_pk == ReceiptItem.receipt_pk, Receipt.deleted_at.is_(None)),
            )
            .group_by(StoreItem.store_item_id, Item.item_id, Store.store_id)
            .order_by(Store.display_name, StoreItem.latest_description)
        )
        if unmapped_only:
            statement = statement.where(StoreItem.mapping_confirmed.is_(False))
        if query:
            term = contains_pattern(query)
            statement = statement.where(
                StoreItem.latest_description.ilike(term, escape=LIKE_ESCAPE)
                | StoreItem.store_product_id.ilike(term, escape=LIKE_ESCAPE)
                | StoreItem.common_name.ilike(term, escape=LIKE_ESCAPE)
                | Item.common_name.ilike(term, escape=LIKE_ESCAPE)
                | Store.display_name.ilike(term, escape=LIKE_ESCAPE)
            )
        return [
            (store_item, item, store_name, last_purchase_date)
            for store_item, item, store_name, last_purchase_date in session.execute(statement)
        ]

    def get_item(self, session: Session, item_id: str) -> Item | None:
        return session.get(Item, item_id)

    def item_mappings(self, session: Session, item_id: str) -> list[StoreItem]:
        return list(
            session.scalars(
                select(StoreItem).where(StoreItem.item_id == item_id).order_by(StoreItem.store_id)
            )
        )
