from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from mbs.models import (
    AuditLog,
    Receipt,
    Store,
    StoreAdminEvent,
    StoreAliasKey,
    StoreItem,
)


class StoreAdministrationConflict(ValueError):
    pass


def merge_stores(
    session: Session,
    source_store_id: str,
    target_store_id: str,
    actor_id: int,
    reason: str,
    source_event_id: str,
) -> tuple[Store, bool]:
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise StoreAdministrationConflict("A reason is required to merge stores")
    signature = _signature(
        {
            "source_store_id": source_store_id,
            "target_store_id": target_store_id,
            "reason": normalized_reason,
        }
    )
    prior_event = session.scalar(
        select(StoreAdminEvent).where(StoreAdminEvent.source_event_id == source_event_id)
    )
    if prior_event is not None:
        if prior_event.request_signature != signature:
            raise StoreAdministrationConflict("Store event ID was reused with another request")
        target = session.get(Store, target_store_id)
        if target is None:
            raise StoreAdministrationConflict("Target store not found")
        return target, True
    if source_store_id == target_store_id:
        raise StoreAdministrationConflict("Source and target stores must differ")

    stores = session.scalars(
        select(Store)
        .where(Store.store_id.in_({source_store_id, target_store_id}))
        .order_by(Store.store_id)
        .with_for_update()
    ).all()
    store_by_id = {store.store_id: store for store in stores}
    prior_event = session.scalar(
        select(StoreAdminEvent).where(StoreAdminEvent.source_event_id == source_event_id)
    )
    if prior_event is not None:
        if prior_event.request_signature != signature:
            raise StoreAdministrationConflict("Store event ID was reused with another request")
        target = store_by_id.get(target_store_id)
        if target is None:
            raise StoreAdministrationConflict("Target store not found")
        return target, True
    source = store_by_id.get(source_store_id)
    target = store_by_id.get(target_store_id)
    if source is None or target is None:
        raise StoreAdministrationConflict("Source or target store not found")
    if source.superseded_by_store_id is not None or not source.is_active:
        raise StoreAdministrationConflict("Source store is already inactive or superseded")
    if target.superseded_by_store_id is not None or not target.is_active:
        raise StoreAdministrationConflict("Target store must be active and canonical")

    source_items = session.scalars(
        select(StoreItem)
        .where(StoreItem.store_id == source_store_id)
        .order_by(StoreItem.store_product_id)
        .with_for_update()
    ).all()
    target_items_by_key = {
        item.store_product_id: item
        for item in session.scalars(select(StoreItem).where(StoreItem.store_id == target_store_id))
    }
    unresolved_collisions = sorted(
        item.store_product_id
        for item in source_items
        if item.store_product_id in target_items_by_key
        and target_items_by_key[item.store_product_id].item_id != item.item_id
    )
    if unresolved_collisions:
        raise StoreAdministrationConflict(
            "Resolve colliding store product identifiers before merging stores"
        )
    retained_historical_items = {
        item.store_item_id for item in source_items if item.store_product_id in target_items_by_key
    }

    alias_keys = session.scalars(
        select(StoreAliasKey).where(StoreAliasKey.store_id == source_store_id).with_for_update()
    ).all()
    for alias in alias_keys:
        alias.store_id = target_store_id
    for store_item in source_items:
        if store_item.store_item_id not in retained_historical_items:
            store_item.store_id = target_store_id
    session.execute(
        update(Receipt).where(Receipt.store_id == source_store_id).values(store_id=target_store_id)
    )
    source.is_active = False
    source.superseded_by_store_id = target_store_id
    session.add(
        StoreAdminEvent(
            source_event_id=source_event_id,
            request_signature=signature,
            operation="MERGE",
            source_store_id=source_store_id,
            target_store_id=target_store_id,
            actor=str(actor_id),
            reason=normalized_reason,
        )
    )
    session.add(
        AuditLog(
            event_type="STORE_MERGED",
            actor=str(actor_id),
            entity_type="Store",
            entity_id=source_store_id,
            details=(
                f"target_store_id={target_store_id}; aliases={len(alias_keys)}; "
                f"store_items={len(source_items)}; "
                f"retained_historical_items={len(retained_historical_items)}; "
                f"reason={normalized_reason}; "
                f"source_event_id={source_event_id}"
            ),
        )
    )
    return target, False


def split_store_aliases(
    session: Session,
    source_store_id: str,
    alias_keys: Sequence[str],
    actor_id: int,
    reason: str,
    source_event_id: str,
    *,
    target_store_id: str | None = None,
    new_display_name: str | None = None,
) -> tuple[Store, bool]:
    normalized_aliases = tuple(sorted({key.strip() for key in alias_keys if key.strip()}))
    normalized_reason = reason.strip()
    if not normalized_reason or not normalized_aliases:
        raise StoreAdministrationConflict("A reason and at least one alias are required")
    if (target_store_id is None) == (new_display_name is None):
        raise StoreAdministrationConflict(
            "Select exactly one existing target store or new display name"
        )
    normalized_name = new_display_name.strip() if new_display_name is not None else None
    if normalized_name is not None and not normalized_name:
        raise StoreAdministrationConflict("New store display name must not be empty")
    signature = _signature(
        {
            "source_store_id": source_store_id,
            "target_store_id": target_store_id or "",
            "new_display_name": normalized_name or "",
            "alias_keys": "|".join(normalized_aliases),
            "reason": normalized_reason,
        }
    )
    prior_event = session.scalar(
        select(StoreAdminEvent).where(StoreAdminEvent.source_event_id == source_event_id)
    )
    if prior_event is not None:
        if prior_event.request_signature != signature:
            raise StoreAdministrationConflict("Store event ID was reused with another request")
        target = session.get(Store, prior_event.target_store_id)
        if target is None:
            raise StoreAdministrationConflict("Split target store not found")
        return target, True

    source = session.scalar(
        select(Store).where(Store.store_id == source_store_id).with_for_update()
    )
    prior_event = session.scalar(
        select(StoreAdminEvent).where(StoreAdminEvent.source_event_id == source_event_id)
    )
    if prior_event is not None:
        if prior_event.request_signature != signature:
            raise StoreAdministrationConflict("Store event ID was reused with another request")
        target = session.get(Store, prior_event.target_store_id)
        if target is None:
            raise StoreAdministrationConflict("Split target store not found")
        return target, True
    if source is None or not source.is_active or source.superseded_by_store_id is not None:
        raise StoreAdministrationConflict("Source store must be active and canonical")
    aliases = session.scalars(
        select(StoreAliasKey)
        .where(StoreAliasKey.normalized_key.in_(normalized_aliases))
        .order_by(StoreAliasKey.normalized_key)
        .with_for_update()
    ).all()
    if len(aliases) != len(normalized_aliases) or any(
        alias.store_id != source_store_id for alias in aliases
    ):
        raise StoreAdministrationConflict("Every selected alias must belong to the source store")

    if target_store_id is not None:
        target = session.scalar(
            select(Store).where(Store.store_id == target_store_id).with_for_update()
        )
        if (
            target is None
            or target.store_id == source_store_id
            or not target.is_active
            or target.superseded_by_store_id is not None
        ):
            raise StoreAdministrationConflict("Split target must be another active canonical store")
    else:
        target = Store(display_name=normalized_name)
        session.add(target)
        session.flush()

    for alias in aliases:
        alias.store_id = target.store_id
    session.add(
        StoreAdminEvent(
            source_event_id=source_event_id,
            request_signature=signature,
            operation="SPLIT",
            source_store_id=source_store_id,
            target_store_id=target.store_id,
            actor=str(actor_id),
            reason=normalized_reason,
        )
    )
    session.add(
        AuditLog(
            event_type="STORE_SPLIT_FORWARD_ONLY",
            actor=str(actor_id),
            entity_type="Store",
            entity_id=source_store_id,
            details=(
                f"target_store_id={target.store_id}; aliases={','.join(normalized_aliases)}; "
                f"posted receipts unchanged; reason={normalized_reason}; "
                f"source_event_id={source_event_id}"
            ),
        )
    )
    return target, False


def _signature(payload: dict[str, str]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
