from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs.models import Base, CategoryRule, Store, StoreItem


class ReceiptRuleRepository:
    def enabled_categories(self, session: Session) -> list[CategoryRule]:
        return list(
            session.scalars(
                select(CategoryRule)
                .where(CategoryRule.enabled.is_(True))
                .order_by(CategoryRule.priority)
            )
        )

    def remembered_items(self, session: Session, store_id: str | None = None) -> list[StoreItem]:
        query = select(StoreItem).where(StoreItem.last_disposition.is_not(None))
        if store_id is not None:
            query = query.where(StoreItem.store_id == store_id)
        return list(
            session.scalars(query.order_by(StoreItem.store_id, StoreItem.latest_description))
        )

    def lock_store_item(self, session: Session, store_item_id: str) -> StoreItem | None:
        return session.scalar(
            select(StoreItem).where(StoreItem.store_item_id == store_item_id).with_for_update()
        )

    def store_names(self, session: Session) -> dict[str, str]:
        return {
            store_id: name
            for store_id, name in session.execute(select(Store.store_id, Store.display_name))
        }

    def add(self, session: Session, record: Base) -> None:
        session.add(record)

    def commit(self, session: Session) -> None:
        session.commit()
