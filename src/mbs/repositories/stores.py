from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from mbs.models import (
    Base,
    Receipt,
    Store,
    StoreAdminEvent,
    StoreAliasKey,
    StoreAliasSpelling,
    StoreItem,
)
from mbs.repositories.query import LIKE_ESCAPE, contains_pattern


class StoreRepository:
    def get_store(
        self, session: Session, store_id: str, *, lock: bool = False, refresh: bool = False
    ) -> Store | None:
        if not lock and not refresh:
            return session.get(Store, store_id)
        query = select(Store).where(Store.store_id == store_id)
        if lock:
            query = query.with_for_update()
        if refresh:
            query = query.execution_options(populate_existing=True)
        return session.scalar(query)

    def get_alias(
        self, session: Session, normalized_key: str, *, refresh: bool = False
    ) -> StoreAliasKey | None:
        if not refresh:
            return session.get(StoreAliasKey, normalized_key)
        return session.scalar(
            select(StoreAliasKey)
            .where(StoreAliasKey.normalized_key == normalized_key)
            .execution_options(populate_existing=True)
        )

    def spelling_id(self, session: Session, normalized_key: str, raw_alias: str) -> int | None:
        return session.scalar(
            select(StoreAliasSpelling.id).where(
                StoreAliasSpelling.normalized_key == normalized_key,
                StoreAliasSpelling.raw_alias == raw_alias,
            )
        )

    def admin_event(self, session: Session, event_id: str) -> StoreAdminEvent | None:
        return session.scalar(
            select(StoreAdminEvent).where(StoreAdminEvent.source_event_id == event_id)
        )

    def lock_stores(self, session: Session, store_ids: set[str]) -> list[Store]:
        return list(
            session.scalars(
                select(Store)
                .where(Store.store_id.in_(store_ids))
                .order_by(Store.store_id)
                .with_for_update()
            )
        )

    def store_items(
        self, session: Session, store_id: str, *, lock: bool = False
    ) -> list[StoreItem]:
        query = select(StoreItem).where(StoreItem.store_id == store_id)
        if lock:
            query = query.order_by(StoreItem.store_product_id).with_for_update()
        return list(session.scalars(query))

    def aliases_for_update(self, session: Session, store_id: str) -> list[StoreAliasKey]:
        return list(
            session.scalars(
                select(StoreAliasKey).where(StoreAliasKey.store_id == store_id).with_for_update()
            )
        )

    def lock_aliases(self, session: Session, keys: Sequence[str]) -> list[StoreAliasKey]:
        return list(
            session.scalars(
                select(StoreAliasKey)
                .where(StoreAliasKey.normalized_key.in_(keys))
                .order_by(StoreAliasKey.normalized_key)
                .with_for_update()
            )
        )

    def repoint_receipts(
        self, session: Session, source_store_id: str, target_store_id: str
    ) -> None:
        session.execute(
            update(Receipt)
            .where(Receipt.store_id == source_store_id)
            .values(store_id=target_store_id)
        )

    def page_rows(self, session: Session) -> list[tuple[Store, int, date | None]]:
        return [
            (store, count, purchased)
            for store, count, purchased in session.execute(
                select(Store, func.count(Receipt.receipt_pk), func.max(Receipt.receipt_date))
                .outerjoin(
                    Receipt, and_(Receipt.store_id == Store.store_id, Receipt.deleted_at.is_(None))
                )
                .group_by(Store.store_id)
                .order_by(Store.display_name, Store.store_id)
            )
        ]

    def alias_rows(self, session: Session) -> list[tuple[str, str, str | None]]:
        return [
            (store_id, key, raw_alias)
            for store_id, key, raw_alias in session.execute(
                select(
                    StoreAliasKey.store_id,
                    StoreAliasKey.normalized_key,
                    StoreAliasSpelling.raw_alias,
                )
                .outerjoin(
                    StoreAliasSpelling,
                    StoreAliasSpelling.normalized_key == StoreAliasKey.normalized_key,
                )
                .order_by(StoreAliasKey.normalized_key, StoreAliasSpelling.raw_alias)
            )
        ]

    def directory_rows(
        self, session: Session, query: str | None, active_only: bool
    ) -> list[tuple[Store, int, int, date | None]]:
        statement = (
            select(
                Store,
                func.count(func.distinct(StoreAliasKey.normalized_key)),
                func.count(func.distinct(Receipt.receipt_pk)),
                func.max(Receipt.receipt_date),
            )
            .outerjoin(StoreAliasKey, StoreAliasKey.store_id == Store.store_id)
            .outerjoin(
                Receipt, and_(Receipt.store_id == Store.store_id, Receipt.deleted_at.is_(None))
            )
            .group_by(Store.store_id)
            .order_by(Store.is_active.desc(), Store.display_name, Store.store_id)
        )
        if query:
            statement = statement.where(
                Store.display_name.ilike(contains_pattern(query), escape=LIKE_ESCAPE)
            )
        if active_only:
            statement = statement.where(Store.is_active.is_(True))
        return [
            (store, aliases, count, purchased)
            for store, aliases, count, purchased in session.execute(statement)
        ]

    def alias_spellings(self, session: Session, store_id: str) -> list[tuple[str, str | None]]:
        return [
            (key, raw_alias)
            for key, raw_alias in session.execute(
                select(StoreAliasKey.normalized_key, StoreAliasSpelling.raw_alias)
                .outerjoin(
                    StoreAliasSpelling,
                    StoreAliasSpelling.normalized_key == StoreAliasKey.normalized_key,
                )
                .where(StoreAliasKey.store_id == store_id)
                .order_by(StoreAliasKey.normalized_key, StoreAliasSpelling.raw_alias)
            )
        ]

    def active_stores_except(self, session: Session, store_id: str) -> list[Store]:
        return list(
            session.scalars(
                select(Store).where(Store.store_id != store_id, Store.is_active.is_(True))
            )
        )

    def add(self, session: Session, record: Base) -> None:
        session.add(record)

    def flush(self, session: Session) -> None:
        session.flush()

    def commit(self, session: Session) -> None:
        session.commit()

    @contextmanager
    def savepoint(self, session: Session) -> Iterator[None]:
        with session.begin_nested():
            yield
