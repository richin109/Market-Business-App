from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from datetime import date as calendar_date
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Literal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbs.models import (
    AuditLog,
    Item,
    ItemMappingEvent,
    Receipt,
    ReceiptItem,
    Store,
    StoreItem,
    StoreItemMapping,
)
from mbs.receipts.units import normalize_unit_alias
from mbs.settings import read_setting


def register_store_item(
    session: Session,
    store_id: str,
    store_product_id: str | None,
    description: str,
    upc: str | None = None,
    identifier_source: Literal["MERCHANT", "USER_ENTERED", "MANUAL"] = "MERCHANT",
    *,
    confirmed_item_id: str | None = None,
    actor_id: int | None = None,
    effective_from: calendar_date | None = None,
) -> StoreItem:
    if store_product_id is None or not store_product_id.strip():
        raise ValueError("A store product identifier is required")
    normalized_identifier = store_product_id.strip()
    is_manual_identifier = normalized_identifier.startswith("MANUAL:")
    if (identifier_source == "MANUAL") != is_manual_identifier:
        raise ValueError("Manual identifiers must use the reserved MANUAL: prefix")
    confirmed_mapping: tuple[str, int] | None = None
    if confirmed_item_id is not None:
        if actor_id is None:
            raise ValueError("An actor is required to confirm an item mapping")
        confirmed_mapping = (confirmed_item_id, actor_id)
    store = session.scalar(select(Store).where(Store.store_id == store_id).with_for_update())
    if store is None:
        raise ValueError("Canonical store not found")
    existing = session.scalar(
        select(StoreItem)
        .where(
            StoreItem.store_id == store_id,
            StoreItem.store_product_id == normalized_identifier,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.identifier_source != identifier_source and "MANUAL" in {
            existing.identifier_source,
            identifier_source,
        }:
            raise ValueError("Store product identifier source conflicts with existing identity")
        _update_observed_store_item(session, existing, description, upc)
        if confirmed_mapping is not None:
            return confirm_store_item_mapping(
                session, existing.store_item_id, confirmed_mapping[0], confirmed_mapping[1]
            )
        return existing

    try:
        with session.begin_nested():
            item = None
            if confirmed_mapping is not None:
                item = session.scalar(
                    select(Item).where(Item.item_id == confirmed_mapping[0]).with_for_update()
                )
                if item is None or not item.is_active:
                    raise ValueError("Active canonical item not found")
                item.is_store_observed = True
                item.updated_at = datetime.now(UTC)
            else:
                item = Item(is_store_observed=True)
                session.add(item)
                session.flush()
            store_item = StoreItem(
                store_id=store_id,
                store_product_id=normalized_identifier,
                item_id=item.item_id,
                latest_description=description,
                upc=upc,
                identifier_source=identifier_source,
                mapping_confirmed=confirmed_mapping is not None,
            )
            session.add(store_item)
            session.flush()
            session.add(
                StoreItemMapping(
                    store_item_id=store_item.store_item_id,
                    item_id=item.item_id,
                    effective_from=effective_from or calendar_date.today(),
                    actor=str(actor_id) if actor_id is not None else "SYSTEM",
                )
            )
            session.add(
                AuditLog(
                    event_type="STORE_ITEM_CREATED",
                    actor=str(actor_id) if actor_id is not None else None,
                    entity_type="StoreItem",
                    entity_id=store_item.store_item_id,
                    details=(
                        f"store_id={store_id}; store_product_id={normalized_identifier}; "
                        f"item_id={item.item_id}"
                    ),
                )
            )
            if confirmed_mapping is not None:
                session.add(
                    AuditLog(
                        event_type="STORE_ITEM_MAPPING_CONFIRMED",
                        actor=str(confirmed_mapping[1]),
                        entity_type="StoreItem",
                        entity_id=store_item.store_item_id,
                        details=f"item_id=None->{item.item_id}",
                    )
                )
        return store_item
    except IntegrityError as error:
        existing = session.scalar(
            select(StoreItem).where(
                StoreItem.store_id == store_id,
                StoreItem.store_product_id == normalized_identifier,
            )
        )
        if existing is None:
            raise
        if existing.identifier_source != identifier_source and "MANUAL" in {
            existing.identifier_source,
            identifier_source,
        }:
            raise ValueError(
                "Store product identifier source conflicts with existing identity"
            ) from error
        _update_observed_store_item(session, existing, description, upc)
        if confirmed_mapping is not None:
            return confirm_store_item_mapping(
                session, existing.store_item_id, confirmed_mapping[0], confirmed_mapping[1]
            )
        return existing


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
    prior_event = session.scalar(
        select(ItemMappingEvent).where(ItemMappingEvent.source_event_id == event_id)
    )
    if prior_event is not None:
        if prior_event.request_signature != signature:
            raise ValueError("Mapping event ID was already used with another request")
        store_item = session.get(StoreItem, store_item_id)
        if store_item is None:
            raise ValueError("Store item not found")
        return store_item

    current_item_id = session.scalar(
        select(StoreItem.item_id).where(StoreItem.store_item_id == store_item_id)
    )
    if current_item_id is None:
        raise ValueError("Store item or canonical item not found")
    locked_items = session.scalars(
        select(Item)
        .where(Item.item_id.in_({current_item_id, item_id}))
        .order_by(Item.item_id)
        .with_for_update()
    ).all()
    items_by_id = {item.item_id: item for item in locked_items}
    target_item = items_by_id.get(item_id)
    previous_item = items_by_id.get(current_item_id)
    if target_item is None or previous_item is None:
        raise ValueError("Store item or canonical item not found")
    if not target_item.is_active:
        raise ValueError("Cannot map a store item to an inactive canonical item")
    target_item.is_store_observed = True

    store_item = session.scalar(
        select(StoreItem)
        .where(StoreItem.store_item_id == store_item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if store_item is None:
        raise ValueError("Store item or canonical item not found")
    prior_event = session.scalar(
        select(ItemMappingEvent).where(ItemMappingEvent.source_event_id == event_id)
    )
    if prior_event is not None:
        if prior_event.request_signature != signature:
            raise ValueError("Mapping event ID was already used with another request")
        return store_item

    previous_item_id = store_item.item_id
    if previous_item_id != current_item_id:
        raise ValueError("Store item mapping changed concurrently; retry the operation")
    previous_mapping = session.scalar(
        select(StoreItemMapping)
        .where(
            StoreItemMapping.store_item_id == store_item.store_item_id,
            StoreItemMapping.effective_to.is_(None),
        )
        .with_for_update()
    )
    if previous_mapping is None:
        previous_mapping = StoreItemMapping(
            store_item_id=store_item.store_item_id,
            item_id=previous_item_id,
            effective_from=store_item.created_at.date(),
            actor="SYSTEM",
        )
        session.add(previous_mapping)
        session.flush()
    if effective_date < previous_mapping.effective_from:
        raise ValueError("Mapping effective date cannot precede the current mapping")
    latest_purchase_date = session.scalar(
        select(func.max(Receipt.receipt_date))
        .join(ReceiptItem, ReceiptItem.receipt_pk == Receipt.receipt_pk)
        .where(ReceiptItem.store_item_id == store_item.store_item_id)
    )
    if latest_purchase_date is not None and effective_date <= latest_purchase_date:
        raise ValueError("Historical item mapping changes require a linked restatement")
    if (
        effective_date == previous_mapping.effective_from
        and previous_item_id != target_item.item_id
    ):
        raise ValueError("A conflicting mapping already exists for this effective date")

    if previous_item_id != target_item.item_id:
        if previous_item.is_store_observed:
            item_count = session.scalar(
                select(func.count(StoreItem.store_item_id)).where(
                    StoreItem.item_id == previous_item_id
                )
            )
            if (item_count or 0) <= 1:
                raise ValueError(
                    "The last store item cannot be moved away from a store-observed item"
                )
        previous_mapping.effective_to = effective_date
        session.add(
            StoreItemMapping(
                store_item_id=store_item.store_item_id,
                item_id=target_item.item_id,
                effective_from=effective_date,
                actor=str(actor_id),
                source_event_id=event_id,
            )
        )
        store_item.item_id = target_item.item_id

    was_confirmed = store_item.mapping_confirmed
    store_item.mapping_confirmed = True
    if previous_item_id != target_item.item_id or not was_confirmed:
        session.add(
            AuditLog(
                event_type="STORE_ITEM_MAPPING_CONFIRMED",
                actor=str(actor_id),
                entity_type="StoreItem",
                entity_id=store_item.store_item_id,
                details=(
                    f"item_id={previous_item_id}->{target_item.item_id}; "
                    f"effective_from={effective_date.isoformat()}; reason={normalized_reason}"
                ),
            )
        )
    session.add(
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
        )
    )
    return store_item


def item_id_for_date(session: Session, store_item_id: str, effective_date: calendar_date) -> str:
    mapping = session.scalar(
        select(StoreItemMapping)
        .where(
            StoreItemMapping.store_item_id == store_item_id,
            StoreItemMapping.effective_from <= effective_date,
            (StoreItemMapping.effective_to.is_(None))
            | (StoreItemMapping.effective_to > effective_date),
        )
        .order_by(StoreItemMapping.effective_from.desc())
        .limit(1)
    )
    if mapping is None:
        raise ValueError("No canonical item mapping exists for the receipt date")
    return mapping.item_id


def suggest_item_mappings(session: Session, store_item_id: str) -> list[dict[str, object]]:
    store_item = session.get(StoreItem, store_item_id)
    if store_item is None:
        raise ValueError("Store item not found")
    configured_limit = read_setting(session, "item_mapping_suggestion_limit")
    if configured_limit is None:
        raise ValueError("Item mapping suggestion limit is not configured")
    try:
        limit = int(configured_limit)
    except ValueError as error:
        raise ValueError("Item mapping suggestion limit must be an integer") from error
    if not 1 <= limit <= 100:
        raise ValueError("Item mapping suggestion limit must be between 1 and 100")

    normalized_description = _normalize_item_text(store_item.latest_description)
    candidate_items = session.scalars(
        select(Item).where(Item.is_active.is_(True), Item.item_id != store_item.item_id)
    ).all()
    candidate_store_items = session.scalars(
        select(StoreItem).where(StoreItem.mapping_confirmed.is_(True))
    ).all()
    store_items_by_item: dict[str, list[StoreItem]] = {}
    for candidate in candidate_store_items:
        store_items_by_item.setdefault(candidate.item_id, []).append(candidate)

    suggestions: list[dict[str, object]] = []
    for candidate_item in candidate_items:
        linked_items = store_items_by_item.get(candidate_item.item_id, [])
        reasons: set[str] = set()
        score = 0.0
        if store_item.upc is not None and any(
            candidate.upc == store_item.upc for candidate in linked_items
        ):
            score += 100
            reasons.add("Shared UPC")
        common_name = _normalize_item_text(candidate_item.common_name or "")
        if common_name and common_name == normalized_description:
            score += 90
            reasons.add("Common name matches printed description")
        descriptions = {
            _normalize_item_text(candidate.latest_description) for candidate in linked_items
        }
        if normalized_description and normalized_description in descriptions:
            score += 80
            reasons.add("Previously confirmed description")
        closest_description = max(
            (
                SequenceMatcher(None, normalized_description, description).ratio()
                for description in descriptions
                if description
            ),
            default=0.0,
        )
        if closest_description >= 0.55 and "Previously confirmed description" not in reasons:
            score += closest_description * 40
            reasons.add("Similar confirmed description")
        if reasons:
            suggestions.append(
                {
                    "item_id": candidate_item.item_id,
                    "common_name": candidate_item.common_name,
                    "score": round(score, 3),
                    "reasons": sorted(reasons),
                }
            )

    def sort_key(suggestion: dict[str, object]) -> tuple[float, str]:
        score = suggestion["score"]
        return (-(score if isinstance(score, float) else 0.0), str(suggestion["item_id"]))

    suggestions.sort(key=sort_key)
    return suggestions[:limit]


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
    prior_event = session.scalar(
        select(ItemMappingEvent).where(ItemMappingEvent.source_event_id == source_event_id)
    )
    if prior_event is not None:
        if prior_event.request_signature != signature:
            raise ValueError("Mapping event ID was already used with another request")
        target = session.get(Item, target_item_id)
        if target is None:
            raise ValueError("Target item not found")
        return target

    items = session.scalars(
        select(Item)
        .where(Item.item_id.in_({source_item_id, target_item_id}))
        .order_by(Item.item_id)
        .with_for_update()
    ).all()
    prior_event = session.scalar(
        select(ItemMappingEvent).where(ItemMappingEvent.source_event_id == source_event_id)
    )
    if prior_event is not None:
        if prior_event.request_signature != signature:
            raise ValueError("Mapping event ID was already used with another request")
        target = session.get(Item, target_item_id)
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
    store_items = session.scalars(
        select(StoreItem)
        .where(StoreItem.item_id == source_item_id)
        .order_by(StoreItem.store_item_id)
        .with_for_update()
    ).all()
    for store_item in store_items:
        current_mapping = session.scalar(
            select(StoreItemMapping)
            .where(
                StoreItemMapping.store_item_id == store_item.store_item_id,
                StoreItemMapping.effective_to.is_(None),
            )
            .with_for_update()
        )
        if current_mapping is None or effective_from <= current_mapping.effective_from:
            raise ValueError("Merge effective date must follow each current mapping")
        latest_purchase_date = session.scalar(
            select(func.max(Receipt.receipt_date))
            .join(ReceiptItem, ReceiptItem.receipt_pk == Receipt.receipt_pk)
            .where(ReceiptItem.store_item_id == store_item.store_item_id)
        )
        if latest_purchase_date is not None and effective_from <= latest_purchase_date:
            raise ValueError("Historical item merges require a linked restatement")
        current_mapping.effective_to = effective_from
        event_id = _child_event_id(source_event_id, store_item.store_item_id)
        session.add(
            StoreItemMapping(
                store_item_id=store_item.store_item_id,
                item_id=target_item_id,
                effective_from=effective_from,
                actor=str(actor_id),
                source_event_id=event_id,
            )
        )
        session.add(
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
            )
        )
        session.add(
            AuditLog(
                event_type="CANONICAL_ITEM_MERGED",
                actor=str(actor_id),
                entity_type="StoreItem",
                entity_id=store_item.store_item_id,
                details=(
                    f"item_id={source_item_id}->{target_item_id}; "
                    f"effective_from={effective_from.isoformat()}; reason={normalized_reason}"
                ),
            )
        )
        store_item.item_id = target_item_id
        store_item.mapping_confirmed = True

    source.is_active = False
    source.superseded_by_item_id = target_item_id
    source.updated_at = datetime.now(UTC)
    target.is_store_observed = target.is_store_observed or bool(store_items)
    target.updated_at = datetime.now(UTC)
    session.add(
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
        )
    )
    session.add(
        AuditLog(
            event_type="CANONICAL_ITEM_MERGE",
            actor=str(actor_id),
            entity_type="Item",
            entity_id=source_item_id,
            details=(
                f"target_item_id={target_item_id}; effective_from={effective_from.isoformat()}; "
                f"reason={normalized_reason}; source_event_id={source_event_id}"
            ),
        )
    )
    return target


def assign_manual_store_product_identifier(
    session: Session,
    receipt_item_id: int,
    actor_id: int,
) -> StoreItem:
    receipt_item = session.scalar(
        select(ReceiptItem).where(ReceiptItem.id == receipt_item_id).with_for_update()
    )
    if receipt_item is None:
        raise ValueError("Receipt item not found")
    if receipt_item.store_item_id is not None:
        raise ValueError("Receipt item already has a store product identifier")
    merchant_product_id = (
        receipt_item.raw_ocr_item.get("store_product_id") if receipt_item.raw_ocr_item else None
    )
    if merchant_product_id is not None and str(merchant_product_id).strip():
        raise ValueError("A merchant product identifier already exists in the source")
    receipt = session.get(Receipt, receipt_item.receipt_pk)
    if receipt is None:
        raise ValueError("Receipt item not found")
    if receipt.source_type != "MANUAL":
        raise ValueError("Manual store product identifiers require a manually entered receipt")

    store_product_id = f"MANUAL:{uuid4()}"
    store_item = register_store_item(
        session,
        receipt.store_id,
        store_product_id,
        receipt_item.description,
        receipt_item.upc,
        identifier_source="MANUAL",
        effective_from=receipt.receipt_date,
    )
    store_item.mapping_confirmed = True
    receipt_item.store_item_id = store_item.store_item_id
    receipt_item.item_id = store_item.item_id
    session.add(
        AuditLog(
            event_type="MANUAL_STORE_PRODUCT_ID_ASSIGNED",
            actor=str(actor_id),
            entity_type="ReceiptItem",
            entity_id=str(receipt_item.id),
            details=(
                f"store_item_id={store_item.store_item_id}; "
                f"store_product_id={store_item.store_product_id}; identifier_source=MANUAL"
            ),
        )
    )
    return store_item


def assign_reviewed_store_product_identifier(
    session: Session,
    receipt_item_id: int,
    store_product_id: str,
    actor_id: int,
    source_event_id: str | None = None,
) -> StoreItem:
    normalized_identifier = store_product_id.strip()
    if not normalized_identifier:
        raise ValueError("A store product identifier is required")
    if normalized_identifier.upper().startswith("MANUAL:"):
        raise ValueError("MANUAL: identifiers are reserved for manually entered receipts")
    event_id = source_event_id or str(uuid4())
    signature = _request_signature(
        {
            "receipt_item_id": str(receipt_item_id),
            "store_product_id": normalized_identifier,
        }
    )
    prior_event = session.scalar(
        select(ItemMappingEvent).where(ItemMappingEvent.source_event_id == event_id)
    )
    if prior_event is not None:
        if prior_event.request_signature != signature:
            raise ValueError("Identifier review event ID was reused with another request")
        store_item = session.get(StoreItem, prior_event.store_item_id)
        if store_item is None:
            raise ValueError("Store item not found")
        return store_item

    receipt_item = session.scalar(
        select(ReceiptItem).where(ReceiptItem.id == receipt_item_id).with_for_update()
    )
    if receipt_item is None or receipt_item.store_item_id is not None:
        raise ValueError("Unmapped receipt item not found")
    merchant_product_id = (
        receipt_item.raw_ocr_item.get("store_product_id") if receipt_item.raw_ocr_item else None
    )
    if merchant_product_id is not None and str(merchant_product_id).strip():
        raise ValueError("A source product identifier already exists")
    receipt = session.scalar(
        select(Receipt)
        .where(Receipt.receipt_pk == receipt_item.receipt_pk, Receipt.deleted_at.is_(None))
        .with_for_update()
    )
    if receipt is None or receipt.source_type != "OCR":
        raise ValueError("Reviewed merchant identifiers require an active OCR receipt")

    store_item = register_store_item(
        session,
        receipt.store_id,
        normalized_identifier,
        receipt_item.description,
        receipt_item.upc,
        effective_from=receipt.receipt_date,
    )
    resolved_item_id = item_id_for_date(session, store_item.store_item_id, receipt.receipt_date)
    receipt_item.store_item_id = store_item.store_item_id
    receipt_item.item_id = resolved_item_id
    session.add(
        ItemMappingEvent(
            source_event_id=event_id,
            request_signature=signature,
            operation="IDENTIFIER_REVIEWED",
            store_item_id=store_item.store_item_id,
            previous_item_id=None,
            item_id=resolved_item_id,
            effective_from=receipt.receipt_date,
            actor=str(actor_id),
            reason="Reviewer supplied printed product identifier",
        )
    )
    session.add(
        AuditLog(
            event_type="RECEIPT_LINE_STORE_PRODUCT_ID_REVIEWED",
            actor=str(actor_id),
            entity_type="ReceiptItem",
            entity_id=str(receipt_item.id),
            details=(
                f"store_item_id={store_item.store_item_id}; "
                f"store_product_id={normalized_identifier}; "
                f"source_event_id={event_id}"
            ),
        )
    )
    return store_item


def set_item_common_name(
    session: Session,
    item_id: str,
    common_name: str | None,
    actor_id: int,
) -> Item:
    item = session.scalar(select(Item).where(Item.item_id == item_id).with_for_update())
    if item is None:
        raise ValueError("Canonical item not found")
    normalized_name = _normalize_common_name(common_name)
    if item.common_name != normalized_name:
        previous_name = item.common_name
        item.common_name = normalized_name
        item.updated_at = datetime.now(UTC)
        session.add(
            AuditLog(
                event_type="ITEM_COMMON_NAME_UPDATED",
                actor=str(actor_id),
                entity_type="Item",
                entity_id=item.item_id,
                details=f"common_name={previous_name!r}->{normalized_name!r}",
            )
        )
    return item


def set_store_item_common_name(
    session: Session,
    store_item_id: str,
    common_name: str | None,
    actor_id: int,
) -> StoreItem:
    store_item = session.scalar(
        select(StoreItem).where(StoreItem.store_item_id == store_item_id).with_for_update()
    )
    if store_item is None:
        raise ValueError("Store item not found")
    normalized_name = _normalize_common_name(common_name)
    if store_item.common_name != normalized_name:
        previous_name = store_item.common_name
        store_item.common_name = normalized_name
        store_item.updated_at = datetime.now(UTC)
        session.add(
            AuditLog(
                event_type="STORE_ITEM_COMMON_NAME_UPDATED",
                actor=str(actor_id),
                entity_type="StoreItem",
                entity_id=store_item.store_item_id,
                details=f"common_name={previous_name!r}->{normalized_name!r}",
            )
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
    store_item = session.scalar(
        select(StoreItem).where(StoreItem.store_item_id == store_item_id).with_for_update()
    )
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
        session.add(
            AuditLog(
                event_type="STORE_ITEM_PACKAGE_DEFAULT_UPDATED",
                actor=str(actor_id),
                entity_type="StoreItem",
                entity_id=store_item.store_item_id,
                details=(
                    f"previous={previous!r}; next=({pack_size}, {normalized_unit}); "
                    f"reason={normalized_reason}"
                ),
            )
        )
    return store_item


def set_item_active(
    session: Session,
    item_id: str,
    is_active: bool,
    actor_id: int,
) -> Item:
    item = session.scalar(select(Item).where(Item.item_id == item_id).with_for_update())
    if item is None:
        raise ValueError("Canonical item not found")
    if is_active and item.superseded_by_item_id is not None:
        raise ValueError("A superseded canonical item cannot be reactivated")
    if not is_active and item.is_active:
        linked_count = session.scalar(
            select(func.count(StoreItem.store_item_id)).where(StoreItem.item_id == item_id)
        )
        if linked_count:
            raise ValueError("Move or merge mapped store items before deactivating this item")
    if item.is_active != is_active:
        previous_status = item.is_active
        item.is_active = is_active
        item.updated_at = datetime.now(UTC)
        session.add(
            AuditLog(
                event_type="ITEM_STATUS_UPDATED",
                actor=str(actor_id),
                entity_type="Item",
                entity_id=item.item_id,
                details=f"is_active={previous_status}->{is_active}",
            )
        )
    return item


def displayed_item_name(session: Session, receipt_item: ReceiptItem) -> str:
    if receipt_item.store_item_id is None:
        return receipt_item.description
    store_item = session.get(StoreItem, receipt_item.store_item_id)
    if store_item is None:
        return receipt_item.description
    if store_item.common_name:
        return store_item.common_name
    item = session.get(Item, receipt_item.item_id) if receipt_item.item_id else None
    return item.common_name if item is not None and item.common_name else receipt_item.description


def _update_observed_store_item(
    session: Session,
    store_item: StoreItem,
    description: str,
    upc: str | None,
) -> None:
    old_description = store_item.latest_description
    old_upc = store_item.upc
    store_item.latest_description = description
    if upc is not None:
        store_item.upc = upc
    if old_description != store_item.latest_description or old_upc != store_item.upc:
        session.add(
            AuditLog(
                event_type="STORE_ITEM_SOURCE_DETAILS_UPDATED",
                entity_type="StoreItem",
                entity_id=store_item.store_item_id,
                details=(
                    f"description={old_description!r}->{store_item.latest_description!r}; "
                    f"upc={old_upc!r}->{store_item.upc!r}"
                ),
            )
        )


def _normalize_common_name(common_name: str | None) -> str | None:
    if common_name is None:
        return None
    normalized_name = common_name.strip()
    if len(normalized_name) > 255:
        raise ValueError("Common name must be 255 characters or fewer")
    return normalized_name or None


def _request_signature(payload: dict[str, str]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _child_event_id(source_event_id: str, store_item_id: str) -> str:
    return "item-merge:" + hashlib.sha256(f"{source_event_id}:{store_item_id}".encode()).hexdigest()


def _normalize_item_text(value: str) -> str:
    return " ".join(value.casefold().split())
