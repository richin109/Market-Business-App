from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from mbs.errors import NotFoundError
from mbs.items import (
    assign_reviewed_store_product_identifier,
    confirm_store_item_mapping,
    merge_canonical_items,
    set_item_active,
    set_item_common_name,
    set_store_item_common_name,
)
from mbs.repositories.items import ItemCommandRepository


class ItemCommandService:
    def __init__(self, repository: ItemCommandRepository | None = None) -> None:
        self._repository = repository or ItemCommandRepository()

    def review_identifier(
        self,
        session: Session,
        receipt_item_id: int,
        store_product_id: str,
        actor_id: int,
        source_event_id: str,
    ) -> dict[str, object]:
        store_item = assign_reviewed_store_product_identifier(
            session, receipt_item_id, store_product_id, actor_id, source_event_id
        )
        self._repository.commit(session)
        return {
            "store_item_id": store_item.store_item_id,
            "item_id": store_item.item_id,
            "mapping_confirmed": store_item.mapping_confirmed,
        }

    def update_item(
        self,
        session: Session,
        item_id: str,
        common_name: str | None,
        update_name: bool,
        is_active: bool | None,
        actor_id: int,
    ) -> dict[str, object]:
        item = self._repository.get_item(session, item_id)
        if item is None:
            raise NotFoundError("Item not found")
        if update_name:
            set_item_common_name(session, item_id, common_name, actor_id)
        if is_active is not None:
            item = set_item_active(session, item_id, is_active, actor_id)
        self._repository.commit(session)
        return {
            "item_id": item.item_id,
            "common_name": item.common_name,
            "is_active": item.is_active,
        }

    def update_store_item(
        self, session: Session, store_item_id: str, common_name: str | None, actor_id: int
    ) -> dict[str, object]:
        store_item = set_store_item_common_name(session, store_item_id, common_name, actor_id)
        self._repository.commit(session)
        return {"store_item_id": store_item.store_item_id, "common_name": store_item.common_name}

    def map_item(
        self,
        session: Session,
        store_item_id: str,
        item_id: str,
        actor_id: int,
        effective_from: date,
        reason: str,
        source_event_id: str,
        store_common_name: str | None,
    ) -> dict[str, object]:
        store_item = confirm_store_item_mapping(
            session,
            store_item_id,
            item_id,
            actor_id,
            effective_from=effective_from,
            reason=reason,
            source_event_id=source_event_id,
        )
        if store_common_name is not None:
            set_store_item_common_name(session, store_item_id, store_common_name, actor_id)
        self._repository.commit(session)
        return {
            "store_item_id": store_item.store_item_id,
            "item_id": store_item.item_id,
            "mapping_confirmed": store_item.mapping_confirmed,
        }

    def split_item(
        self,
        session: Session,
        store_item_id: str,
        common_name: str | None,
        actor_id: int,
        effective_from: date,
        reason: str,
        source_event_id: str,
    ) -> dict[str, object]:
        store_item = self._repository.get_store_item(session, store_item_id)
        if store_item is None:
            raise NotFoundError("Store item not found")
        item = self._repository.create_observed_item(session, common_name)
        mapped = confirm_store_item_mapping(
            session,
            store_item.store_item_id,
            item.item_id,
            actor_id,
            effective_from=effective_from,
            reason=reason,
            source_event_id=source_event_id,
            operation="SPLIT",
        )
        self._repository.commit(session)
        return {"store_item_id": mapped.store_item_id, "item_id": mapped.item_id}

    def merge_items(
        self,
        session: Session,
        source_item_id: str,
        target_item_id: str,
        actor_id: int,
        reason: str,
        source_event_id: str,
        effective_from: date,
    ) -> dict[str, object]:
        target = merge_canonical_items(
            session,
            source_item_id,
            target_item_id,
            actor_id,
            reason,
            source_event_id,
            effective_from,
        )
        self._repository.commit(session)
        return {"item_id": target.item_id, "common_name": target.common_name}


def get_item_command_service() -> ItemCommandService:
    return ItemCommandService()
