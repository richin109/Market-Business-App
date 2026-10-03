from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbs.domain.receipt_dispositions import (
    DispositionSubtype as DispositionSubtype,
)
from mbs.domain.receipt_dispositions import (
    PostingKind as PostingKind,
)
from mbs.domain.receipt_dispositions import (
    PostingStatus as PostingStatus,
)
from mbs.domain.receipt_dispositions import (
    validate_disposition_pair as validate_disposition_pair,
)
from mbs.items import item_id_for_date
from mbs.models import (
    AuditLog,
    ReceiptCorrection,
    ReceiptExpenseDraft,
    ReceiptLineApproval,
    ReceiptRoutingRecord,
    StoreItem,
)
from mbs.receipts.ocr import BusinessDisposition
from mbs.repositories.receipts import ReceiptRepository

repository = ReceiptRepository()


@dataclass(frozen=True)
class ApprovalResult:
    approval: ReceiptLineApproval
    idempotent: bool
    remembered_rule_differs: bool = False


def remember_classification(
    store_item: StoreItem,
    disposition: BusinessDisposition,
    subtype: DispositionSubtype,
    *,
    overwrite: bool,
) -> bool:
    """Remember a first decision; return True when an existing rule differs and was kept."""
    if store_item.last_disposition is None or overwrite:
        store_item.last_disposition = disposition.value
        store_item.last_disposition_subtype = subtype.value
        return False
    return (store_item.last_disposition, store_item.last_disposition_subtype) != (
        disposition.value,
        subtype.value,
    )


def approve_receipt_item(
    session: Session,
    receipt_item_id: int,
    reviewer_id: int,
    disposition: BusinessDisposition,
    source_event_id: str | None = None,
    disposition_subtype: DispositionSubtype | None = None,
    update_remembered_rule: bool = False,
) -> ApprovalResult:
    subtype = disposition_subtype or DispositionSubtype.NONE
    validate_disposition_pair(disposition, subtype)

    item = repository.get_line(session, receipt_item_id)
    if item is None:
        raise ValueError("Receipt item not found")
    receipt = repository.get_receipt(session, item.receipt_pk, active_only=True, lock=True)
    if receipt is None:
        raise ValueError("Receipt item not found")
    item = repository.get_line(session, receipt_item_id, lock=True, refresh=True)
    if item is None:
        raise ValueError("Receipt item not found")
    if item.is_excluded:
        raise ValueError("Excluded receipt lines cannot be approved")
    existing = repository.latest_approval(session, receipt_item_id, lock=False)
    if existing is not None:
        if (
            existing.disposition != disposition.value
            or existing.disposition_subtype != subtype.value
        ):
            raise ValueError("Receipt item already approved with another disposition")
        return ApprovalResult(existing, True)
    event_id = source_event_id or f"receipt-item:{receipt_item_id}:approval"
    event_approval = repository.approval_event(session, event_id)
    if event_approval is not None:
        if (
            event_approval.receipt_item_id == receipt_item_id
            and event_approval.disposition == disposition.value
            and event_approval.disposition_subtype == subtype.value
        ):
            return ApprovalResult(event_approval, True)
        raise ValueError("Approval source event ID is already used")
    line_subtotal = repository.active_line_subtotal(session, receipt.receipt_pk) or Decimal("0")
    expected_subtotal = receipt.subtotal
    if expected_subtotal is None:
        expected_subtotal = receipt.total - (receipt.tax or Decimal("0"))
    is_mismatched = line_subtotal.quantize(Decimal("0.01")) != expected_subtotal.quantize(
        Decimal("0.01")
    )
    if receipt.receipt_document.get("total_mismatch") is True or is_mismatched:
        raise ValueError("Receipt totals must reconcile before approval")
    if disposition is BusinessDisposition.PERSONAL_NON_BUSINESS:
        posting_kind = PostingKind.NO_POST
        posting_status = PostingStatus.NO_POST
    elif disposition is BusinessDisposition.ORDINARY_BUSINESS_PURCHASE:
        posting_kind = PostingKind(subtype.value)
        posting_status = PostingStatus.ROUTED
    elif disposition is BusinessDisposition.RECIPE_INGREDIENT:
        posting_kind = PostingKind.INGREDIENT_PURCHASE
        posting_status = PostingStatus.ROUTED
    elif disposition is BusinessDisposition.CAPITAL_ASSET_EQUIPMENT:
        posting_kind = PostingKind.CAPITAL_ASSET
        posting_status = PostingStatus.ROUTED
    else:
        raise ValueError("Receipt item must have a reviewed business disposition")
    if posting_kind is not PostingKind.NO_POST:
        if item.store_item_id is None or item.item_id is None:
            raise ValueError("Receipt line requires a store product identifier before posting")
        store_item = repository.get_store_item(session, item.store_item_id)
        resolved_item_id = (
            item_id_for_date(session, item.store_item_id, receipt.receipt_date)
            if store_item is not None
            else None
        )
        canonical_item = repository.get_item(session, item.item_id)
        if (
            store_item is None
            or resolved_item_id != item.item_id
            or not store_item.mapping_confirmed
            or canonical_item is None
            or not canonical_item.is_active
        ):
            raise ValueError("Receipt store item mapping must be confirmed before posting")
    requires_package = disposition is BusinessDisposition.RECIPE_INGREDIENT or (
        disposition is BusinessDisposition.ORDINARY_BUSINESS_PURCHASE
        and subtype is DispositionSubtype.STOCKED_SUPPLY
    )
    if requires_package and any(
        value is None for value in (item.package_count, item.pack_size, item.pack_unit)
    ):
        raise ValueError("Reviewed package count, size, and unit are required before approval")
    approval = ReceiptLineApproval(
        receipt_item_id=receipt_item_id,
        approval_version=1,
        reviewer_id=reviewer_id,
        disposition=disposition.value,
        disposition_subtype=subtype.value,
        posting_kind=posting_kind.value,
        posting_status=posting_status.value,
        source_event_id=event_id,
    )
    rule_differs = False
    try:
        with repository.savepoint(session):
            item.business_disposition = disposition.value
            item.disposition_subtype = subtype.value
            repository.add(session, approval)
            if posting_kind is not PostingKind.NO_POST:
                routing_record = ReceiptRoutingRecord(
                    receipt_item_id=item.id,
                    approved_version=approval.approval_version,
                    destination_kind=posting_kind.value,
                    destination_identity=item.item_id,
                    source_event_key=_routing_event_key(event_id, posting_kind),
                    status="PENDING",
                )
                repository.add(session, routing_record)
                repository.flush(session)
                if subtype is DispositionSubtype.DIRECT_EXPENSE:
                    repository.add(
                        session,
                        ReceiptExpenseDraft(
                            receipt_item_id=item.id,
                            routing_record_id=routing_record.id,
                            store_id=receipt.store_id,
                            item_id=item.item_id,
                            description=item.description,
                            amount=item.line_total,
                            status="PENDING",
                        ),
                    )
            store_item = (
                repository.get_store_item(session, item.store_item_id)
                if item.store_item_id is not None
                else None
            )
            if store_item is not None:
                rule_differs = remember_classification(
                    store_item, disposition, subtype, overwrite=update_remembered_rule
                )
            repository.add(
                session,
                AuditLog(
                    event_type="RECEIPT_LINE_APPROVED",
                    actor=str(reviewer_id),
                    entity_type="ReceiptItem",
                    entity_id=str(receipt_item_id),
                    details=f"{posting_kind.value}; subtype={subtype.value}",
                ),
            )
            repository.flush(session)
    except IntegrityError as error:
        existing = repository.latest_approval(session, receipt_item_id, lock=False)
        event_approval = repository.approval_event(session, event_id)
        if existing is not None:
            if (
                existing.disposition == disposition.value
                and existing.disposition_subtype == subtype.value
            ):
                return ApprovalResult(existing, True)
            raise ValueError("Receipt item already approved with another disposition") from error
        if event_approval is not None:
            if (
                event_approval.receipt_item_id == receipt_item_id
                and event_approval.disposition == disposition.value
                and event_approval.disposition_subtype == subtype.value
            ):
                return ApprovalResult(event_approval, True)
            raise ValueError("Approval source event ID is already used") from error
        raise
    return ApprovalResult(approval, False, rule_differs)


def reclassify_expense_routing(
    session: Session,
    receipt_item_id: int,
    reviewer_id: int,
    disposition: BusinessDisposition,
    disposition_subtype: DispositionSubtype,
    reason: str,
    source_event_id: str,
    update_remembered_rule: bool = False,
) -> ApprovalResult:
    normalized_reason = reason.strip()
    event_id = source_event_id.strip()
    if not normalized_reason or not event_id:
        raise ValueError("Reroute reason and source event ID are required")
    if len(normalized_reason) > 2000 or len(event_id) > 255:
        raise ValueError("Reroute reason or source event ID exceeds the allowed length")
    if disposition is BusinessDisposition.ORDINARY_BUSINESS_PURCHASE:
        if disposition_subtype not in {
            DispositionSubtype.STOCKED_SUPPLY,
            DispositionSubtype.DIRECT_SELL_RESTOCK,
        }:
            raise ValueError("Expense reroutes must target a stock or resale destination")
        posting_kind = PostingKind(disposition_subtype.value)
    elif (
        disposition is BusinessDisposition.RECIPE_INGREDIENT
        and disposition_subtype is DispositionSubtype.NONE
    ):
        posting_kind = PostingKind.INGREDIENT_PURCHASE
    else:
        raise ValueError("Expense reroutes must target a stock or resale destination")

    item = repository.get_line(session, receipt_item_id)
    if item is None:
        raise ValueError("Receipt item not found")
    receipt = repository.get_receipt(session, item.receipt_pk, active_only=True, lock=True)
    if receipt is None:
        raise ValueError("Receipt item not found")
    item = repository.get_line(session, receipt_item_id, lock=True, refresh=True)
    if item is None:
        raise ValueError("Receipt item not found")

    correction_event_id = "reroute:" + hashlib.sha256(event_id.encode()).hexdigest()
    request_document: dict[str, object] = {
        "source_event_id": event_id,
        "receipt_item_id": receipt_item_id,
        "disposition": disposition.value,
        "disposition_subtype": disposition_subtype.value,
    }
    prior_change = repository.correction_event(session, correction_event_id)
    if prior_change is not None:
        if (
            prior_change.receipt_pk != receipt.receipt_pk
            or prior_change.actor_id != reviewer_id
            or prior_change.reason != normalized_reason
            or prior_change.request_document != request_document
        ):
            raise ValueError("Reroute source event ID is already used")
        prior_approval = repository.approval_event(session, event_id)
        if prior_approval is None:
            raise RuntimeError("Reroute audit event has no approval revision")
        return ApprovalResult(prior_approval, True)

    current = repository.latest_approval(session, receipt_item_id, lock=True)
    if (
        current is None
        or current.disposition != BusinessDisposition.ORDINARY_BUSINESS_PURCHASE.value
        or current.disposition_subtype != DispositionSubtype.DIRECT_EXPENSE.value
    ):
        raise ValueError("Only an expense-routed line can be changed to stock or resale")
    existing_event = repository.approval_event(session, event_id)
    if existing_event is not None:
        raise ValueError("Reroute source event ID is already used")

    old_route = repository.expense_route(
        session, receipt_item_id, current.approval_version, PostingKind.DIRECT_EXPENSE.value
    )
    if old_route is None or old_route.status not in {"PENDING", "POSTED"}:
        raise ValueError("The prior expense route is not eligible for a reroute hold")
    previous_route_status = old_route.status
    expense_draft = repository.expense_draft(session, old_route.id)
    previous_expense_status = expense_draft.status if expense_draft is not None else None
    store_item_id = item.store_item_id
    store_item = (
        repository.get_store_item(session, store_item_id) if store_item_id is not None else None
    )
    resolved_item_id = (
        item_id_for_date(session, store_item_id, receipt.receipt_date)
        if store_item is not None and store_item_id is not None
        else None
    )
    canonical_item = repository.get_item(session, item.item_id) if item.item_id else None
    if (
        store_item is None
        or resolved_item_id != item.item_id
        or not store_item.mapping_confirmed
        or canonical_item is None
        or not canonical_item.is_active
    ):
        raise ValueError("Receipt store item mapping must be confirmed before posting")

    lines = repository.lines(session, receipt.receipt_pk)
    line_index = next(index for index, line in enumerate(lines) if line.id == item.id)
    before_document = deepcopy(receipt.receipt_document or {})
    after_document = deepcopy(before_document)
    document_items = after_document.get("items")
    if not isinstance(document_items, list) or line_index >= len(document_items):
        raise ValueError("Receipt snapshot does not contain the approved line")
    document_line = document_items[line_index]
    if not isinstance(document_line, dict):
        raise ValueError("Receipt snapshot line is invalid")
    document_line["business_disposition"] = disposition.value
    document_line["disposition_subtype"] = disposition_subtype.value

    approval_version = current.approval_version + 1
    next_approval = ReceiptLineApproval(
        receipt_item_id=receipt_item_id,
        approval_version=approval_version,
        reviewer_id=reviewer_id,
        disposition=disposition.value,
        disposition_subtype=disposition_subtype.value,
        posting_kind=posting_kind.value,
        posting_status=PostingStatus.HELD.value,
        source_event_id=event_id,
    )
    now = datetime.now(UTC)
    rule_differs = False
    with repository.savepoint(session):
        old_route.status = "HELD"
        if expense_draft is not None and expense_draft.status == "PENDING":
            expense_draft.status = "HELD"
        new_route = ReceiptRoutingRecord(
            receipt_item_id=receipt_item_id,
            approved_version=approval_version,
            destination_kind=posting_kind.value,
            destination_identity=item.item_id,
            source_event_key=_routing_event_key(event_id, posting_kind),
            status="HELD",
            supersedes_routing_record_id=old_route.id,
        )
        item.business_disposition = disposition.value
        item.disposition_subtype = disposition_subtype.value
        receipt.receipt_document = after_document
        receipt.receipt_document_version += 1
        receipt.reviewed_by = reviewer_id
        receipt.reviewed_at = now
        rule_differs = remember_classification(
            store_item, disposition, disposition_subtype, overwrite=update_remembered_rule
        )
        repository.add_all(
            session,
            [
                next_approval,
                new_route,
                ReceiptCorrection(
                    receipt_pk=receipt.receipt_pk,
                    actor_id=reviewer_id,
                    reason=normalized_reason,
                    source_event_id=correction_event_id,
                    request_document=request_document,
                    before_document=before_document,
                    after_document=after_document,
                    document_version=receipt.receipt_document_version,
                ),
            ],
        )
        repository.add(
            session,
            AuditLog(
                event_type="RECEIPT_EXPENSE_REROUTE_HELD",
                actor=str(reviewer_id),
                entity_type="ReceiptItem",
                entity_id=str(receipt_item_id),
                details=json.dumps(
                    {
                        "source_event_id": event_id,
                        "reason": normalized_reason,
                        "prior_routing_record_id": old_route.id,
                        "prior_routing_status": previous_route_status,
                        "prior_expense_draft_status": previous_expense_status,
                        "new_destination": posting_kind.value,
                        "new_approval_version": approval_version,
                    },
                    sort_keys=True,
                ),
            ),
        )
        repository.flush(session)
    return ApprovalResult(next_approval, False, rule_differs)


def _routing_event_key(source_event_id: str, posting_kind: PostingKind) -> str:
    digest = hashlib.sha256(f"{source_event_id}:{posting_kind.value}".encode()).hexdigest()
    return f"receipt-route:{digest}"
