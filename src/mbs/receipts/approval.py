from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs.models import AuditLog, ReceiptItem, ReceiptLineApproval
from mbs.receipts.ocr import BusinessDisposition


class PostingKind(StrEnum):
    NO_POST = "NO_POST"
    ORDINARY_EXPENSE = "ORDINARY_EXPENSE"
    INGREDIENT_PURCHASE = "INGREDIENT_PURCHASE"
    CAPITAL_ASSET = "CAPITAL_ASSET"


class PostingStatus(StrEnum):
    NO_POST = "NO_POST"
    ROUTED = "ROUTED"


@dataclass(frozen=True)
class ApprovalResult:
    approval: ReceiptLineApproval
    idempotent: bool


def approve_receipt_item(
    session: Session,
    receipt_item_id: int,
    reviewer_id: int,
    disposition: BusinessDisposition,
    source_event_id: str | None = None,
) -> ApprovalResult:
    item = session.get(ReceiptItem, receipt_item_id)
    if item is None:
        raise ValueError("Receipt item not found")
    existing = session.scalar(
        select(ReceiptLineApproval).where(
            ReceiptLineApproval.receipt_item_id == receipt_item_id
        )
    )
    if existing is not None:
        if existing.disposition != disposition.value:
            raise ValueError("Receipt item already approved with another disposition")
        return ApprovalResult(existing, True)
    event_id = source_event_id or f"receipt-item:{receipt_item_id}:approval"
    if disposition is BusinessDisposition.PERSONAL_NON_BUSINESS:
        posting_kind = PostingKind.NO_POST
        posting_status = PostingStatus.NO_POST
    elif disposition is BusinessDisposition.ORDINARY_BUSINESS_PURCHASE:
        posting_kind = PostingKind.ORDINARY_EXPENSE
        posting_status = PostingStatus.ROUTED
    elif disposition is BusinessDisposition.RECIPE_INGREDIENT:
        posting_kind = PostingKind.INGREDIENT_PURCHASE
        posting_status = PostingStatus.ROUTED
    elif disposition is BusinessDisposition.CAPITAL_ASSET_EQUIPMENT:
        posting_kind = PostingKind.CAPITAL_ASSET
        posting_status = PostingStatus.ROUTED
    else:
        raise ValueError("Receipt item must have a reviewed business disposition")
    item.business_disposition = disposition.value
    approval = ReceiptLineApproval(
        receipt_item_id=receipt_item_id,
        reviewer_id=reviewer_id,
        disposition=disposition.value,
        posting_kind=posting_kind.value,
        posting_status=posting_status.value,
        source_event_id=event_id,
    )
    session.add(approval)
    session.add(
        AuditLog(
            event_type="RECEIPT_LINE_APPROVED",
            actor=str(reviewer_id),
            entity_type="ReceiptItem",
            entity_id=str(receipt_item_id),
            details=posting_kind.value,
        )
    )
    session.flush()
    return ApprovalResult(approval, False)
