from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from mbs.domain.items import (
    _normalize_common_name,
)
from mbs.models import AuditLog, Item, ReceiptItem, StoreItem
from mbs.receipts.units import normalize_unit_alias
from mbs.repositories.items import ItemRepository

repository = ItemRepository()


def set_item_common_name(
    session: Session,
    item_id: str,
    common_name: str | None,
    actor_id: int,
) -> Item:
    item = repository.get_item(session, item_id, lock=True)
    if item is None:
        raise ValueError("Canonical item not found")
    normalized_name = _normalize_common_name(common_name)
    if item.common_name != normalized_name:
        previous_name = item.common_name
        item.common_name = normalized_name
        item.updated_at = datetime.now(UTC)
        repository.add(
            session,
            AuditLog(
                event_type="ITEM_COMMON_NAME_UPDATED",
                actor=str(actor_id),
                entity_type="Item",
                entity_id=item.item_id,
                details=f"common_name={previous_name!r}->{normalized_name!r}",
            ),
        )
    return item


def set_store_item_common_name(
    session: Session,
    store_item_id: str,
    common_name: str | None,
    actor_id: int,
) -> StoreItem:
    store_item = repository.get_store_item(session, store_item_id, lock=True)
    if store_item is None:
        raise ValueError("Store item not found")
    normalized_name = _normalize_common_name(common_name)
    if store_item.common_name != normalized_name:
        previous_name = store_item.common_name
        store_item.common_name = normalized_name
        store_item.updated_at = datetime.now(UTC)
        repository.add(
            session,
            AuditLog(
                event_type="STORE_ITEM_COMMON_NAME_UPDATED",
                actor=str(actor_id),
                entity_type="StoreItem",
                entity_id=store_item.store_item_id,
                details=f"common_name={previous_name!r}->{normalized_name!r}",
            ),
        )
    return store_item


def remember_store_item_package(
    session: Session,
    store_item_id: str,
    pack_size: Decimal,
    pack_unit: str,
    actor_id: int,
    reason: str,
) -> StoreItem:
    normalized_reason = reason.strip()
    normalized_unit = normalize_unit_alias(pack_unit)
    if not normalized_reason:
        raise ValueError("A reason is required to update a remembered package")
    if pack_size <= 0 or normalized_unit is None:
        raise ValueError("Remembered package size and unit must be valid")
    store_item = repository.get_store_item(session, store_item_id, lock=True)
    if store_item is None:
        raise ValueError("Store item not found")
    if (
        store_item.remembered_pack_size != pack_size
        or store_item.remembered_pack_unit != normalized_unit
    ):
        previous = (store_item.remembered_pack_size, store_item.remembered_pack_unit)
        store_item.remembered_pack_size = pack_size
        store_item.remembered_pack_unit = normalized_unit
        store_item.updated_at = datetime.now(UTC)
        repository.add(
            session,
            AuditLog(
                event_type="STORE_ITEM_PACKAGE_DEFAULT_UPDATED",
                actor=str(actor_id),
                entity_type="StoreItem",
                entity_id=store_item.store_item_id,
                details=(
                    f"previous={previous!r}; next=({pack_size}, {normalized_unit}); "
                    f"reason={normalized_reason}"
                ),
            ),
        )
    return store_item


def set_item_active(
    session: Session,
    item_id: str,
    is_active: bool,
    actor_id: int,
) -> Item:
    item = repository.get_item(session, item_id, lock=True)
    if item is None:
        raise ValueError("Canonical item not found")
    if is_active and item.superseded_by_item_id is not None:
        raise ValueError("A superseded canonical item cannot be reactivated")
    if not is_active and item.is_active:
        linked_count = repository.count_store_items(session, item_id)
        if linked_count:
            raise ValueError("Move or merge mapped store items before deactivating this item")
    if item.is_active != is_active:
        previous_status = item.is_active
        item.is_active = is_active
        item.updated_at = datetime.now(UTC)
        repository.add(
            session,
            AuditLog(
                event_type="ITEM_STATUS_UPDATED",
                actor=str(actor_id),
                entity_type="Item",
                entity_id=item.item_id,
                details=f"is_active={previous_status}->{is_active}",
            ),
        )
    return item


def displayed_item_name(session: Session, receipt_item: ReceiptItem) -> str:
    if receipt_item.store_item_id is None:
        return receipt_item.description
    store_item = repository.get_store_item(session, receipt_item.store_item_id)
    if store_item is None:
        return receipt_item.description
    if store_item.common_name:
        return store_item.common_name
    item = repository.get_item(session, receipt_item.item_id) if receipt_item.item_id else None
    return item.common_name if item is not None and item.common_name else receipt_item.description
