from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mbs.errors import NotFoundError
from mbs.models import AuditLog, Receipt, ReceiptItem, ReceiptLineApproval


def soft_delete_receipt(session: Session, receipt_pk: str, actor_id: int, reason: str) -> bool:
    """Hide a receipt without removing data; returns False when it was already deleted."""
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("A reason is required to delete a receipt")
    receipt = session.scalar(
        select(Receipt).where(Receipt.receipt_pk == receipt_pk).with_for_update()
    )
    if receipt is None:
        raise NotFoundError("Receipt not found")
    if receipt.deleted_at is not None:
        return False
    approved_lines = session.scalar(
        select(func.count(ReceiptLineApproval.id))
        .join(ReceiptItem, ReceiptItem.id == ReceiptLineApproval.receipt_item_id)
        .where(ReceiptItem.receipt_pk == receipt_pk)
    )
    if approved_lines:
        raise ValueError("A receipt with approved lines cannot be deleted")
    receipt.deleted_at = datetime.now(UTC)
    session.add(
        AuditLog(
            event_type="RECEIPT_SOFT_DELETED",
            actor=str(actor_id),
            entity_type="Receipt",
            entity_id=receipt_pk,
            details=f"reason={normalized_reason}",
        )
    )
    return True
