from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as calendar_date
from typing import Literal
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbs.domain.items import (
    _request_signature,
)
from mbs.models import AuditLog, Item, ItemMappingEvent, StoreItem, StoreItemMapping
from mbs.repositories.items import ItemRepository
from mbs.services.item_mapping import confirm_store_item_mapping, item_id_for_date

repository = ItemRepository()


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
    store = repository.store_for_update(session, store_id)
    if store is None:
        raise ValueError("Canonical store not found")
    existing = repository.observed_store_item(session, store_id, normalized_identifier, lock=True)
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
        with repository.savepoint(session):
            item = None
            if confirmed_mapping is not None:
                item = repository.get_item(session, confirmed_mapping[0], lock=True)
                if item is None or not item.is_active:
                    raise ValueError("Active canonical item not found")
                item.is_store_observed = True
                item.updated_at = datetime.now(UTC)
            else:
                item = Item(is_store_observed=True)
                repository.add(session, item)
                repository.flush(session)
            store_item = StoreItem(
                store_id=store_id,
                store_product_id=normalized_identifier,
                item_id=item.item_id,
                latest_description=description,
                upc=upc,
                identifier_source=identifier_source,
                mapping_confirmed=confirmed_mapping is not None,
            )
            repository.add(session, store_item)
            repository.flush(session)
            repository.add(
                session,
                StoreItemMapping(
                    store_item_id=store_item.store_item_id,
                    item_id=item.item_id,
                    effective_from=effective_from or calendar_date.today(),
                    actor=str(actor_id) if actor_id is not None else "SYSTEM",
                ),
            )
            repository.add(
                session,
                AuditLog(
                    event_type="STORE_ITEM_CREATED",
                    actor=str(actor_id) if actor_id is not None else None,
                    entity_type="StoreItem",
                    entity_id=store_item.store_item_id,
                    details=(
                        f"store_id={store_id}; store_product_id={normalized_identifier}; "
                        f"item_id={item.item_id}"
                    ),
                ),
            )
            if confirmed_mapping is not None:
                repository.add(
                    session,
                    AuditLog(
                        event_type="STORE_ITEM_MAPPING_CONFIRMED",
                        actor=str(confirmed_mapping[1]),
                        entity_type="StoreItem",
                        entity_id=store_item.store_item_id,
                        details=f"item_id=None->{item.item_id}",
                    ),
                )
        return store_item
    except IntegrityError as error:
        existing = repository.observed_store_item(
            session, store_id, normalized_identifier, lock=False
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


def assign_manual_store_product_identifier(
    session: Session,
    receipt_item_id: int,
    actor_id: int,
) -> StoreItem:
    receipt_item = repository.receipt_line_for_update(session, receipt_item_id)
    if receipt_item is None:
        raise ValueError("Receipt item not found")
    if receipt_item.store_item_id is not None:
        raise ValueError("Receipt item already has a store product identifier")
    merchant_product_id = (
        receipt_item.raw_ocr_item.get("store_product_id") if receipt_item.raw_ocr_item else None
    )
    if merchant_product_id is not None and str(merchant_product_id).strip():
        raise ValueError("A merchant product identifier already exists in the source")
    receipt = repository.get_receipt(session, receipt_item.receipt_pk)
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
    repository.add(
        session,
        AuditLog(
            event_type="MANUAL_STORE_PRODUCT_ID_ASSIGNED",
            actor=str(actor_id),
            entity_type="ReceiptItem",
            entity_id=str(receipt_item.id),
            details=(
                f"store_item_id={store_item.store_item_id}; "
                f"store_product_id={store_item.store_product_id}; identifier_source=MANUAL"
            ),
        ),
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
    prior_event = repository.mapping_event(session, event_id)
    if prior_event is not None:
        if prior_event.request_signature != signature:
            raise ValueError("Identifier review event ID was reused with another request")
        store_item = repository.get_store_item(session, prior_event.store_item_id)
        if store_item is None:
            raise ValueError("Store item not found")
        return store_item

    receipt_item = repository.receipt_line_for_update(session, receipt_item_id)
    if receipt_item is None or receipt_item.store_item_id is not None:
        raise ValueError("Unmapped receipt item not found")
    merchant_product_id = (
        receipt_item.raw_ocr_item.get("store_product_id") if receipt_item.raw_ocr_item else None
    )
    if merchant_product_id is not None and str(merchant_product_id).strip():
        raise ValueError("A source product identifier already exists")
    receipt = repository.get_receipt(session, receipt_item.receipt_pk, active_only=True, lock=True)
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
    repository.add(
        session,
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
        ),
    )
    repository.add(
        session,
        AuditLog(
            event_type="RECEIPT_LINE_STORE_PRODUCT_ID_REVIEWED",
            actor=str(actor_id),
            entity_type="ReceiptItem",
            entity_id=str(receipt_item.id),
            details=(
                f"store_item_id={store_item.store_item_id}; "
                f"store_product_id={normalized_identifier}; source_event_id={event_id}"
            ),
        ),
    )
    return store_item


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
        repository.add(
            session,
            AuditLog(
                event_type="STORE_ITEM_SOURCE_DETAILS_UPDATED",
                entity_type="StoreItem",
                entity_id=store_item.store_item_id,
                details=(
                    f"description={old_description!r}->{store_item.latest_description!r}; "
                    f"upc={old_upc!r}->{store_item.upc!r}"
                ),
            ),
        )
