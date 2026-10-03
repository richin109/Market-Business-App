from __future__ import annotations

from sqlalchemy.orm import Session

from mbs.domain.receipt_dispositions import DispositionSubtype, validate_disposition_pair
from mbs.domain.receipt_normalization import BusinessDisposition
from mbs.errors import NotFoundError
from mbs.models import AuditLog, StoreItem
from mbs.repositories.receipt_rules import ReceiptRuleRepository

repository = ReceiptRuleRepository()


def list_remembered_rules(session: Session, store_id: str | None = None) -> list[StoreItem]:
    return repository.remembered_items(session, store_id)


def _locked_store_item(session: Session, store_item_id: str) -> StoreItem:
    store_item = repository.lock_store_item(session, store_item_id)
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
    repository.add(
        session,
        AuditLog(
            event_type="REMEMBERED_RULE_CORRECTED",
            actor=str(actor_id),
            entity_type="StoreItem",
            entity_id=store_item_id,
            details=(
                f"{previous[0]}/{previous[1]}->{disposition.value}/{subtype.value}; "
                f"reason={normalized_reason}"
            ),
        ),
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
    repository.add(
        session,
        AuditLog(
            event_type="REMEMBERED_RULE_CLEARED",
            actor=str(actor_id),
            entity_type="StoreItem",
            entity_id=store_item_id,
            details=f"{previous[0]}/{previous[1]}->none; reason={normalized_reason}",
        ),
    )
    return True


def remembered_rules_context(session: Session) -> dict[str, object]:
    names = repository.store_names(session)
    return {
        "rules": [
            {
                "store_item_id": rule.store_item_id,
                "store_name": names.get(rule.store_id, ""),
                "store_product_id": rule.store_product_id,
                "description": rule.latest_description,
                "upc": rule.upc,
                "disposition": rule.last_disposition,
                "disposition_subtype": rule.last_disposition_subtype,
            }
            for rule in list_remembered_rules(session)
        ],
        "dispositions": [
            disposition.value
            for disposition in BusinessDisposition
            if disposition is not BusinessDisposition.UNCLASSIFIED
        ],
    }


def remembered_rules_response(session: Session, store_id: str | None) -> list[dict[str, object]]:
    return [
        {
            "store_item_id": rule.store_item_id,
            "store_id": rule.store_id,
            "store_product_id": rule.store_product_id,
            "description": rule.latest_description,
            "upc": rule.upc,
            "disposition": rule.last_disposition,
            "disposition_subtype": rule.last_disposition_subtype,
        }
        for rule in list_remembered_rules(session, store_id)
    ]


def change_remembered_rule(
    session: Session,
    store_item_id: str,
    disposition: BusinessDisposition,
    subtype: DispositionSubtype,
    actor_id: int,
    reason: str,
) -> dict[str, object]:
    changed = correct_remembered_rule(
        session, store_item_id, disposition, subtype, actor_id, reason
    )
    repository.commit(session)
    return {"store_item_id": store_item_id, "changed": changed}


def remove_remembered_rule(
    session: Session, store_item_id: str, actor_id: int, reason: str
) -> dict[str, object]:
    changed = clear_remembered_rule(session, store_item_id, actor_id, reason)
    repository.commit(session)
    return {"store_item_id": store_item_id, "changed": changed}
