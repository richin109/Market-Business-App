from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from mbs.errors import NotFoundError
from mbs.models import User
from mbs.repositories.receipt_corrections import ReceiptCorrectionRepository
from mbs.services.manual_receipts import create_manual_receipt
from mbs.services.receipt_approval import (
    ApprovalResult,
    approve_receipt_item,
    reclassify_expense_routing,
)
from mbs.services.receipt_correction_holds import resolve_correction_hold
from mbs.services.receipt_corrections import review_receipt
from mbs.services.receipt_lifecycle import soft_delete_receipt
from mbs.services.receipt_reads import _manual_item_responses, _store_items_for_lines
from mbs.services.receipt_sources import decide_receipt_source

repository = ReceiptCorrectionRepository()


def enter_manual_receipt(session: Session, user: User, data: dict[str, Any]) -> dict[str, object]:
    receipt = create_manual_receipt(
        session,
        user,
        store_id=data["store_id"],
        receipt_date=data["receipt_date"],
        vendor_reference=data["vendor_reference"],
        receipt_time=data["receipt_time"],
        subtotal=data["subtotal"],
        tax=data["tax"],
        total=data["total"],
        payment_method=data["payment_method"],
        lines=data["items"],
        source_event_id=data["source_event_id"],
    )
    repository.commit(session)
    receipt_items = repository.lines(session, receipt.receipt_pk)
    store_items = _store_items_for_lines(session, receipt_items)
    return {
        "receipt_pk": receipt.receipt_pk,
        "receipt_id": receipt.receipt_id,
        "source_type": receipt.source_type,
        "item_count": len(data["items"]),
        "items": _manual_item_responses(receipt_items, store_items),
    }


def delete_receipt(
    session: Session, user: User, receipt_pk: str, data: dict[str, Any]
) -> dict[str, object]:
    deleted = soft_delete_receipt(session, receipt_pk, user.id, data["reason"])
    repository.commit(session)
    return {"receipt_pk": receipt_pk, "deleted": True, "idempotent": not deleted}


def decide_receipt_source_route(
    session: Session, user: User, receipt_pk: str, source_id: int, data: dict[str, Any]
) -> dict[str, object]:
    result = decide_receipt_source(
        session,
        receipt_pk,
        source_id,
        user.id,
        data["decision"],
        data["reason"],
        data["source_event_id"],
        data["confirmed_repeated_line_indexes"],
    )
    repository.commit(session)
    return {
        "receipt_pk": receipt_pk,
        "source_id": source_id,
        "association_kind": result.source.association_kind,
        "added_line_count": result.added_line_count,
        "held": result.held,
        "hold_reason": result.source.hold_reason,
        "idempotent": result.idempotent,
    }


def approve_receipt_line(
    session: Session, user: User, receipt_pk: str, receipt_item_id: int, data: dict[str, Any]
) -> dict[str, object]:
    line_exists = repository.line_id_in_receipt(session, receipt_item_id, receipt_pk)
    if line_exists is None:
        raise NotFoundError("Receipt item not found")
    result = approve_receipt_item(
        session,
        receipt_item_id,
        user.id,
        data["disposition"],
        data["source_event_id"],
        data["disposition_subtype"],
        data["update_remembered_rule"],
    )
    repository.commit(session)
    return _approval_response(session, receipt_item_id, result)


def reroute_receipt_line(
    session: Session, user: User, receipt_pk: str, receipt_item_id: int, data: dict[str, Any]
) -> dict[str, object]:
    line_exists = repository.line_id_in_receipt(session, receipt_item_id, receipt_pk)
    if line_exists is None:
        raise NotFoundError("Receipt item not found")
    result = reclassify_expense_routing(
        session,
        receipt_item_id,
        user.id,
        data["disposition"],
        data["disposition_subtype"],
        data["reason"],
        data["source_event_id"],
        data["update_remembered_rule"],
    )
    repository.commit(session)
    return _approval_response(session, receipt_item_id, result)


def correct_receipt(
    session: Session, user: User, receipt_pk: str, data: dict[str, Any]
) -> dict[str, object]:
    result = review_receipt(
        session,
        receipt_pk,
        user.id,
        reason=data["reason"],
        source_event_id=data["source_event_id"],
        header_updates=data["header_updates"],
        item_updates=data["item_updates"],
        item_additions=data["item_additions"],
        item_exclusions=data["item_exclusions"],
        remember_package_default_indexes=data["remember_package_default_indexes"],
    )
    repository.commit(session)
    return {
        "status": result.status.value,
        "receipt_pk": result.receipt.receipt_pk,
        "receipt_id": result.receipt.receipt_id,
        "document_version": result.receipt.receipt_document_version,
        "hold_id": result.hold.id if result.hold is not None else None,
        "idempotent": result.idempotent,
    }


def resolve_receipt_correction_hold(
    session: Session, user: User, hold_id: int, data: dict[str, Any]
) -> dict[str, object]:
    hold = resolve_correction_hold(
        session, hold_id, user.id, data["action"], data["reason"], data["new_transaction_number"]
    )
    repository.commit(session)
    return {"id": hold.id, "status": hold.status, "action": hold.resolution_action}


def list_receipt_correction_holds(session: Session) -> list[dict[str, object]]:
    holds = repository.pending_holds(session)
    return [
        {
            "id": hold.id,
            "receipt_pk": hold.receipt_pk,
            "proposed_receipt_id": hold.proposed_receipt_id,
            "proposed_document": hold.proposed_document,
            "created_at": hold.created_at.isoformat(),
        }
        for hold in holds
    ]


def _approval_response(
    session: Session, receipt_item_id: int, result: ApprovalResult
) -> dict[str, object]:
    routing_record = repository.routing_record(
        session, receipt_item_id, result.approval.posting_kind, result.approval.approval_version
    )
    return {
        "receipt_item_id": receipt_item_id,
        "disposition": result.approval.disposition,
        "disposition_subtype": result.approval.disposition_subtype,
        "posting_kind": result.approval.posting_kind,
        "posting_status": result.approval.posting_status,
        "routing_record_id": routing_record.id if routing_record is not None else None,
        "idempotent": result.idempotent,
        "remembered_rule_differs": result.remembered_rule_differs,
    }
