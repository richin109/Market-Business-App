from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as calendar_date
from typing import Literal
from uuid import uuid4

from sqlalchemy.orm import Session

from mbs.domain.items import (
    _child_event_id,
    _request_signature,
)
from mbs.models import AuditLog, Item, ItemMappingEvent, StoreItem, StoreItemMapping
from mbs.repositories.items import ItemRepository

repository = ItemRepository()


def confirm_store_item_mapping(
    session: Session,
    store_item_id: str,
    item_id: str,
    actor_id: int,
    *,
    effective_from: calendar_date | None = None,
    reason: str = "Mapping confirmed",
    source_event_id: str | None = None,
    operation: Literal["MAP", "SPLIT", "CONFIRM"] | None = None,
) -> StoreItem:
    effective_date = effective_from or calendar_date.today()
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("A reason is required to change an item mapping")
    event_id = source_event_id or str(uuid4())
    signature = _request_signature(
        {
            "store_item_id": store_item_id,
            "item_id": item_id,
            "effective_from": effective_date.isoformat(),
            "reason": normalized_reason,
            "operation": operation or "MAP",
        }
    )
    prior_event = repository.mapping_event(session, event_id)
    if prior_event is not None:
        if prior_event.request_signature != signature:
            raise ValueError("Mapping event ID was already used with another request")
        store_item = repository.get_store_item(session, store_item_id)
        if store_item is None:
            raise ValueError("Store item not found")
        return store_item

    current_item_id = repository.current_item_id(session, store_item_id)
    if current_item_id is None:
        raise ValueError("Store item or canonical item not found")
    locked_items = repository.lock_items(session, {current_item_id, item_id})
    items_by_id = {item.item_id: item for item in locked_items}
    target_item = items_by_id.get(item_id)
    previous_item = items_by_id.get(current_item_id)
    if target_item is None or previous_item is None:
        raise ValueError("Store item or canonical item not found")
    if not target_item.is_active:
        raise ValueError("Cannot map a store item to an inactive canonical item")
    target_item.is_store_observed = True

    store_item = repository.get_store_item(session, store_item_id, lock=True, refresh=True)
    if store_item is None:
        raise ValueError("Store item or canonical item not found")
    prior_event = repository.mapping_event(session, event_id)
    if prior_event is not None:
        if prior_event.request_signature != signature:
            raise ValueError("Mapping event ID was already used with another request")
        return store_item

    previous_item_id = store_item.item_id
    if previous_item_id != current_item_id:
        raise ValueError("Store item mapping changed concurrently; retry the operation")
    previous_mapping = repository.current_mapping(session, store_item.store_item_id)
    if previous_mapping is None:
        previous_mapping = StoreItemMapping(
            store_item_id=store_item.store_item_id,
            item_id=previous_item_id,
            effective_from=store_item.created_at.date(),
            actor="SYSTEM",
        )
        repository.add(session, previous_mapping)
        repository.flush(session)
    if effective_date < previous_mapping.effective_from:
        raise ValueError("Mapping effective date cannot precede the current mapping")
    latest_purchase_date = repository.latest_purchase_date(session, store_item.store_item_id)
    if latest_purchase_date is not None and effective_date <= latest_purchase_date:
        raise ValueError("Historical item mapping changes require a linked restatement")
    if (
        effective_date == previous_mapping.effective_from
        and previous_item_id != target_item.item_id
    ):
        raise ValueError("A conflicting mapping already exists for this effective date")

    if previous_item_id != target_item.item_id:
        if previous_item.is_store_observed:
            item_count = repository.count_store_items(session, previous_item_id)
            if (item_count or 0) <= 1:
                raise ValueError(
                    "The last store item cannot be moved away from a store-observed item"
                )
        previous_mapping.effective_to = effective_date
        repository.add(
            session,
            StoreItemMapping(
                store_item_id=store_item.store_item_id,
                item_id=target_item.item_id,
                effective_from=effective_date,
                actor=str(actor_id),
                source_event_id=event_id,
            ),
        )
        store_item.item_id = target_item.item_id

    was_confirmed = store_item.mapping_confirmed
    store_item.mapping_confirmed = True
    if previous_item_id != target_item.item_id or not was_confirmed:
        repository.add(
            session,
            AuditLog(
                event_type="STORE_ITEM_MAPPING_CONFIRMED",
                actor=str(actor_id),
                entity_type="StoreItem",
                entity_id=store_item.store_item_id,
                details=(
                    f"item_id={previous_item_id}->{target_item.item_id}; "
                    f"effective_from={effective_date.isoformat()}; reason={normalized_reason}"
                ),
            ),
        )
    repository.add(
        session,
        ItemMappingEvent(
            source_event_id=event_id,
            request_signature=signature,
            operation=operation
            or ("MAP" if previous_item_id != target_item.item_id else "CONFIRM"),
            store_item_id=store_item.store_item_id,
            previous_item_id=previous_item_id,
            item_id=target_item.item_id,
            effective_from=effective_date,
            actor=str(actor_id),
            reason=normalized_reason,
        ),
    )
    return store_item


def item_id_for_date(session: Session, store_item_id: str, effective_date: calendar_date) -> str:
    mapping = repository.mapping_on_date(session, store_item_id, effective_date)
    if mapping is None:
        raise ValueError("No canonical item mapping exists for the receipt date")
    return mapping.item_id


def merge_canonical_items(
    session: Session,
    source_item_id: str,
    target_item_id: str,
    actor_id: int,
    reason: str,
    source_event_id: str,
    effective_from: calendar_date,
) -> Item:
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("A reason is required to merge canonical items")
    signature = _request_signature(
        {
            "source_item_id": source_item_id,
            "target_item_id": target_item_id,
            "effective_from": effective_from.isoformat(),
            "reason": normalized_reason,
        }
    )
    prior_event = repository.mapping_event(session, source_event_id)
    if prior_event is not None:
        if prior_event.request_signature != signature:
            raise ValueError("Mapping event ID was already used with another request")
        target = repository.get_item(session, target_item_id)
        if target is None:
            raise ValueError("Target item not found")
        return target

    items = repository.lock_items(session, {source_item_id, target_item_id})
    prior_event = repository.mapping_event(session, source_event_id)
    if prior_event is not None:
        if prior_event.request_signature != signature:
            raise ValueError("Mapping event ID was already used with another request")
        target = repository.get_item(session, target_item_id)
        if target is None:
            raise ValueError("Target item not found")
        return target
    item_by_id = {item.item_id: item for item in items}
    source = item_by_id.get(source_item_id)
    target = item_by_id.get(target_item_id)
    if source is None or target is None or source is target:
        raise ValueError("Distinct source and target canonical items are required")
    if not target.is_active:
        raise ValueError("Cannot merge into an inactive canonical item")
    store_items = repository.store_items_for_update(session, source_item_id)
    for store_item in store_items:
        current_mapping = repository.current_mapping(session, store_item.store_item_id)
        if current_mapping is None or effective_from <= current_mapping.effective_from:
            raise ValueError("Merge effective date must follow each current mapping")
        latest_purchase_date = repository.latest_purchase_date(session, store_item.store_item_id)
        if latest_purchase_date is not None and effective_from <= latest_purchase_date:
            raise ValueError("Historical item merges require a linked restatement")
        current_mapping.effective_to = effective_from
        event_id = _child_event_id(source_event_id, store_item.store_item_id)
        repository.add(
            session,
            StoreItemMapping(
                store_item_id=store_item.store_item_id,
                item_id=target_item_id,
                effective_from=effective_from,
                actor=str(actor_id),
                source_event_id=event_id,
            ),
        )
        repository.add(
            session,
            ItemMappingEvent(
                source_event_id=event_id,
                request_signature=signature,
                operation="MERGE",
                store_item_id=store_item.store_item_id,
                previous_item_id=source_item_id,
                item_id=target_item_id,
                effective_from=effective_from,
                actor=str(actor_id),
                reason=normalized_reason,
            ),
        )
        repository.add(
            session,
            AuditLog(
                event_type="CANONICAL_ITEM_MERGED",
                actor=str(actor_id),
                entity_type="StoreItem",
                entity_id=store_item.store_item_id,
                details=(
                    f"item_id={source_item_id}->{target_item_id}; "
                    f"effective_from={effective_from.isoformat()}; reason={normalized_reason}"
                ),
            ),
        )
        store_item.item_id = target_item_id
        store_item.mapping_confirmed = True

    source.is_active = False
    source.superseded_by_item_id = target_item_id
    source.updated_at = datetime.now(UTC)
    target.is_store_observed = target.is_store_observed or bool(store_items)
    target.updated_at = datetime.now(UTC)
    repository.add(
        session,
        ItemMappingEvent(
            source_event_id=source_event_id,
            request_signature=signature,
            operation="MERGE_ITEMS",
            store_item_id="",
            previous_item_id=source_item_id,
            item_id=target_item_id,
            effective_from=effective_from,
            actor=str(actor_id),
            reason=normalized_reason,
        ),
    )
    repository.add(
        session,
        AuditLog(
            event_type="CANONICAL_ITEM_MERGE",
            actor=str(actor_id),
            entity_type="Item",
            entity_id=source_item_id,
            details=(
                f"target_item_id={target_item_id}; effective_from={effective_from.isoformat()}; "
                f"reason={normalized_reason}; source_event_id={source_event_id}"
            ),
        ),
    )
    return target
