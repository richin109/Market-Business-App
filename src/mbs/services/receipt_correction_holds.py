from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbs.domain.receipt_corrections import (
    HoldResolutionAction,
    _item_value,
    _receipt_id,
)
from mbs.errors import NotFoundError
from mbs.models import AuditLog, ReceiptCorrection, ReceiptCorrectionHold
from mbs.repositories.receipt_corrections import ReceiptCorrectionRepository
from mbs.services.receipt_correction_state import _apply_header, _document, _proposed_values

repository = ReceiptCorrectionRepository()


def resolve_correction_hold(
    session: Session,
    hold_id: int,
    admin_id: int,
    action: HoldResolutionAction,
    reason: str,
    new_transaction_number: str | None = None,
) -> ReceiptCorrectionHold:
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("Resolution reason is required")
    hold = repository.hold_for_update(session, hold_id)
    if hold is None:
        raise NotFoundError("Correction hold not found")
    if hold.status != "PENDING":
        raise ValueError("Correction hold is already resolved")
    receipt = repository.get_receipt(session, hold.receipt_pk, lock=True)
    if receipt is None:
        raise NotFoundError("Receipt not found")

    now = datetime.now(UTC)
    if action is HoldResolutionAction.REKEY:
        if new_transaction_number is None or not new_transaction_number.strip():
            raise ValueError("Re-key requires a new transaction number")
        if repository.first_approval_id(session, receipt.receipt_pk) is not None:
            raise ValueError("Approved receipts require a linked reversal or replacement workflow")
        proposed_document = hold.proposed_document
        proposed_items = proposed_document.get("items")
        if not isinstance(proposed_items, list) or len(proposed_items) != len(
            repository.unordered_lines(session, receipt.receipt_pk)
        ):
            raise ValueError("Correction proposal does not match the receipt items")
        items = repository.lines(session, receipt.receipt_pk)
        proposed = _proposed_values(
            receipt,
            {
                "store": proposed_document["store"],
                "receipt_date": proposed_document["date"],
                "receipt_time": proposed_document["time"],
                "transaction_number": new_transaction_number.strip(),
                "subtotal": proposed_document.get("subtotal"),
                "tax": proposed_document.get("tax"),
                "total": proposed_document["total"],
                "payment_method": proposed_document.get("payment_method"),
            },
        )
        proposed_receipt_id = _receipt_id(
            proposed["store"],
            proposed["receipt_date"],
            proposed["receipt_time"],
            proposed["transaction_number"],
        )
        if (
            repository.receipt_collision_pk(session, proposed_receipt_id, receipt.receipt_pk)
            is not None
        ):
            raise ValueError("New receipt identity is already in use")
        item_updates = {
            index: {
                field: _item_value(field, value)
                for field, value in item_document.items()
                if field
                in {
                    "description",
                    "upc",
                    "quantity",
                    "weight_lb",
                    "package_count",
                    "pack_size",
                    "pack_unit",
                    "unit_price",
                    "line_total",
                    "category",
                    "business_disposition",
                    "disposition_subtype",
                }
            }
            for index, item_document in enumerate(proposed_items)
            if isinstance(item_document, dict)
        }
        before_document = deepcopy(receipt.receipt_document)
        after_document = _document(proposed, items, item_updates)
        next_version = receipt.receipt_document_version + 1
        try:
            with repository.savepoint(session):
                _apply_header(receipt, proposed, proposed_receipt_id)
                for index, updates in item_updates.items():
                    for field, value in updates.items():
                        setattr(items[index], field, value)
                receipt.receipt_document = after_document
                receipt.receipt_document_version = next_version
                receipt.reviewed_by = admin_id
                receipt.reviewed_at = now
                repository.add(
                    session,
                    ReceiptCorrection(
                        receipt_pk=receipt.receipt_pk,
                        actor_id=admin_id,
                        reason=normalized_reason,
                        source_event_id=f"receipt-correction-hold:{hold.id}:rekey",
                        request_document={
                            "hold_id": hold.id,
                            "action": HoldResolutionAction.REKEY.value,
                            "new_transaction_number": new_transaction_number.strip(),
                        },
                        before_document=before_document,
                        after_document=after_document,
                        document_version=next_version,
                    ),
                )
                repository.add(
                    session,
                    AuditLog(
                        event_type="RECEIPT_CORRECTED",
                        actor=str(admin_id),
                        entity_type="Receipt",
                        entity_id=receipt.receipt_pk,
                        details=f"version={next_version}; reason={normalized_reason}",
                    ),
                )
                repository.flush(session)
        except IntegrityError as error:
            collision = repository.receipt_collision_pk(
                session, proposed_receipt_id, receipt.receipt_pk
            )
            if collision is not None:
                raise ValueError("New receipt identity is already in use") from error
            raise
        hold.status = HoldResolutionAction.REKEY.value
    elif action is HoldResolutionAction.KEEP:
        hold.status = HoldResolutionAction.KEEP.value
    elif action is HoldResolutionAction.REJECT:
        if repository.first_approval_id(session, receipt.receipt_pk) is not None:
            raise ValueError("Approved receipts cannot be rejected")
        receipt.deleted_at = now
        receipt.import_state = "REJECTED"
        hold.status = HoldResolutionAction.REJECT.value
    else:
        raise ValueError("Unsupported correction hold action")

    hold.resolved_by = admin_id
    hold.resolution_action = action.value
    hold.resolution_reason = normalized_reason
    hold.resolved_at = now
    repository.add(
        session,
        AuditLog(
            event_type="RECEIPT_CORRECTION_HOLD_RESOLVED",
            actor=str(admin_id),
            entity_type="ReceiptCorrectionHold",
            entity_id=str(hold.id),
            details=f"action={action.value}; reason={normalized_reason}",
        ),
    )
    repository.flush(session)
    return hold
