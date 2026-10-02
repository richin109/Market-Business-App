from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs.errors import NotFoundError
from mbs.models import AuditLog, StoreItem
from mbs.receipts.approval import DispositionSubtype, validate_disposition_pair
from mbs.receipts.ocr import BusinessDisposition


def list_remembered_rules(session: Session, store_id: str | None = None) -> list[StoreItem]:
    query = select(StoreItem).where(StoreItem.last_disposition.is_not(None))
    if store_id is not None:
        query = query.where(StoreItem.store_id == store_id)
    return list(session.scalars(query.order_by(StoreItem.store_id, StoreItem.latest_description)))


def _locked_store_item(session: Session, store_item_id: str) -> StoreItem:
    store_item = session.scalar(
        select(StoreItem).where(StoreItem.store_item_id == store_item_id).with_for_update()
    )
    if store_item is None:
        raise NotFoundError("Store item not found")
    return store_item


def correct_remembered_rule(
    session: Session,
    store_item_id: str,
    disposition: BusinessDisposition,
    subtype: DispositionSubtype,
    actor_id: int,
    reason: str,
) -> bool:
    """Set the remembered classification; returns False when nothing changed."""
    if disposition is BusinessDisposition.UNCLASSIFIED:
        raise ValueError("Clear the rule instead of remembering Unclassified")
    validate_disposition_pair(disposition, subtype)
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("A reason is required to change a remembered rule")
    store_item = _locked_store_item(session, store_item_id)
    previous = (store_item.last_disposition, store_item.last_disposition_subtype)
    if previous == (disposition.value, subtype.value):
        return False
    store_item.last_disposition = disposition.value
    store_item.last_disposition_subtype = subtype.value
    session.add(
        AuditLog(
            event_type="REMEMBERED_RULE_CORRECTED",
            actor=str(actor_id),
            entity_type="StoreItem",
            entity_id=store_item_id,
            details=(
                f"{previous[0]}/{previous[1]}->{disposition.value}/{subtype.value}; "
                f"reason={normalized_reason}"
            ),
        )
    )
    return True


def clear_remembered_rule(session: Session, store_item_id: str, actor_id: int, reason: str) -> bool:
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("A reason is required to change a remembered rule")
    store_item = _locked_store_item(session, store_item_id)
    if store_item.last_disposition is None:
        return False
    previous = (store_item.last_disposition, store_item.last_disposition_subtype)
    store_item.last_disposition = None
    store_item.last_disposition_subtype = None
    session.add(
        AuditLog(
            event_type="REMEMBERED_RULE_CLEARED",
            actor=str(actor_id),
            entity_type="StoreItem",
            entity_id=store_item_id,
            details=f"{previous[0]}/{previous[1]}->none; reason={normalized_reason}",
        )
    )
    return True
