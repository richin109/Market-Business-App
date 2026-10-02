from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from mbs.items import item_id_for_date, register_store_item
from mbs.models import (
    AuditLog,
    Receipt,
    ReceiptCorrection,
    ReceiptItem,
    ReceiptSource,
    ReceiptUpload,
    StoreItem,
)


class SourceDecision(StrEnum):
    COPY = "COPY"
    SUPPLEMENT = "SUPPLEMENT"
    REJECT = "REJECT"


@dataclass(frozen=True)
class SourceDecisionResult:
    source: ReceiptSource
    added_line_count: int
    idempotent: bool = False
    held: bool = False


def decide_receipt_source(
    session: Session,
    receipt_pk: str,
    source_id: int,
    reviewer_id: int,
    decision: SourceDecision,
    reason: str,
    source_event_id: str,
    confirmed_repeated_line_indexes: Sequence[int] = (),
) -> SourceDecisionResult:
    normalized_reason = reason.strip()
    event_id = source_event_id.strip()
    if not normalized_reason or not event_id:
        raise ValueError("Source decision reason and event ID are required")
    if len(normalized_reason) > 2000 or len(event_id) > 255:
        raise ValueError("Source decision reason or event ID exceeds the allowed length")
    confirmed_indexes = tuple(sorted(set(confirmed_repeated_line_indexes)))
    if any(type(index) is not int or index < 0 for index in confirmed_indexes):
        raise ValueError("Repeated source line indexes must be non-negative integers")
    if decision is not SourceDecision.SUPPLEMENT and confirmed_indexes:
        raise ValueError("Repeated-line confirmation applies only to SUPPLEMENT decisions")

    source = session.scalar(
        select(ReceiptSource)
        .where(ReceiptSource.id == source_id, ReceiptSource.receipt_pk == receipt_pk)
        .with_for_update()
    )
    if source is None:
        raise ValueError("Receipt source not found")
    if source.decision_event_id == event_id:
        if (
            source.association_kind != decision.value
            or source.decision_reason != normalized_reason
            or source.decision_actor_id != reviewer_id
            or tuple(source.confirmed_repeated_line_indexes or ()) != confirmed_indexes
        ):
            raise ValueError("Source decision event ID was reused with another request")
        return SourceDecisionResult(
            source,
            _source_line_count(source) if decision is SourceDecision.SUPPLEMENT else 0,
            idempotent=True,
        )
    if source.hold_event_id == event_id:
        if (
            decision is not SourceDecision.SUPPLEMENT
            or source.decision_reason != normalized_reason
            or source.decision_actor_id != reviewer_id
            or tuple(source.confirmed_repeated_line_indexes or ()) != confirmed_indexes
        ):
            raise ValueError("Source decision event ID was reused with another request")
        return SourceDecisionResult(source, 0, idempotent=True, held=True)
    if source.association_kind != "PENDING":
        raise ValueError("Receipt source has already been decided")
    event_source = session.scalar(
        select(ReceiptSource).where(
            or_(
                ReceiptSource.decision_event_id == event_id,
                ReceiptSource.hold_event_id == event_id,
            )
        )
    )
    if event_source is not None:
        raise ValueError("Source decision event ID is already used")

    receipt = session.scalar(
        select(Receipt)
        .where(Receipt.receipt_pk == receipt_pk, Receipt.deleted_at.is_(None))
        .with_for_update()
    )
    if receipt is None:
        raise ValueError("Receipt not found")
    if source.extracted_document.get("receipt_id") != receipt.receipt_id:
        raise ValueError("Candidate source identity does not match this receipt")
    source_items = source.extracted_document.get("items")
    if not isinstance(source_items, list):
        raise ValueError("Source extraction does not contain a valid item list")
    if any(index >= len(source_items) for index in confirmed_indexes):
        raise ValueError("Repeated source line index is out of range")
    source.confirmed_repeated_line_indexes = (
        list(confirmed_indexes) if decision is SourceDecision.SUPPLEMENT else None
    )

    upload = session.scalar(
        select(ReceiptUpload).where(ReceiptUpload.upload_pk == source.upload_pk).with_for_update()
    )
    if upload is None:
        raise ValueError("Receipt source upload not found")

    if decision is SourceDecision.SUPPLEMENT:
        for field in ("subtotal", "tax", "total"):
            source_amount = source.extracted_document.get(field)
            receipt_amount = getattr(receipt, field)
            if (
                source_amount is not None
                and receipt_amount is not None
                and _money(Decimal(str(source_amount))) != _money(receipt_amount)
            ):
                return _hold_source(
                    session,
                    source,
                    reviewer_id,
                    event_id,
                    normalized_reason,
                    f"Source {field} conflicts with the accepted receipt header",
                    {"field": field},
                )
        supplemental_lines = _extracted_lines(source)
        existing_lines = session.scalars(
            select(ReceiptItem)
            .where(ReceiptItem.receipt_pk == receipt_pk, ReceiptItem.is_excluded.is_(False))
            .order_by(ReceiptItem.id)
        ).all()
        combined_subtotal = sum((line.line_total for line in existing_lines), Decimal("0")) + sum(
            (line["line_total"] for line in supplemental_lines), Decimal("0")
        )
        if receipt.subtotal is None or _money(combined_subtotal) != _money(receipt.subtotal):
            return _hold_source(
                session,
                source,
                reviewer_id,
                event_id,
                normalized_reason,
                "Combined source line amounts do not reconcile to the receipt item subtotal",
                {
                    "combined_subtotal": str(_money(combined_subtotal)),
                    "receipt_subtotal": str(_money(receipt.subtotal))
                    if receipt.subtotal is not None
                    else None,
                },
            )
        repeated_indexes = repeated_source_line_indexes(
            existing_lines,
            source_items,
            _store_items_for_source_lines(session, existing_lines),
        )
        unexpected_confirmations = set(confirmed_indexes) - set(repeated_indexes)
        if unexpected_confirmations:
            raise ValueError("Only repeated source lines can be explicitly confirmed")
        missing_confirmations = set(repeated_indexes) - set(confirmed_indexes)
        if missing_confirmations:
            raise ValueError(
                "Reviewer must explicitly confirm each repeated source line as a new occurrence"
            )
        before_document = deepcopy(receipt.receipt_document)
        after_document = deepcopy(receipt.receipt_document)
        canonical_items = after_document.get("items")
        if not isinstance(canonical_items, list):
            raise ValueError("Receipt snapshot does not contain a valid item list")
        for item_index, (source_line, canonical_line) in enumerate(
            zip(supplemental_lines, source_items, strict=True)
        ):
            if not isinstance(canonical_line, dict):
                raise ValueError("Source extraction line is invalid")
            store_product_id = canonical_line.get("store_product_id")
            store_item = (
                register_store_item(
                    session,
                    receipt.store_id,
                    str(store_product_id),
                    str(canonical_line["description"]),
                    str(canonical_line["upc"]) if canonical_line.get("upc") is not None else None,
                    effective_from=receipt.receipt_date,
                )
                if store_product_id is not None
                else None
            )
            item_id = (
                item_id_for_date(session, store_item.store_item_id, receipt.receipt_date)
                if store_item is not None
                else None
            )
            source_page = int(canonical_line.get("source_page") or 1)
            source_line_number = int(canonical_line.get("source_line_number") or 1)
            raw_items = source.raw_ocr_document.get("items")
            raw_item = (
                raw_items[item_index]
                if isinstance(raw_items, list)
                and len(raw_items) > item_index
                and isinstance(raw_items[item_index], dict)
                else None
            )
            session.add(
                ReceiptItem(
                    receipt_pk=receipt.receipt_pk,
                    description=str(canonical_line["description"]),
                    upc=(
                        str(canonical_line["upc"])
                        if canonical_line.get("upc") is not None
                        else None
                    ),
                    quantity=_optional_decimal(canonical_line.get("quantity")),
                    weight_lb=_optional_decimal(canonical_line.get("weight_lb")),
                    unit_price=_optional_decimal(canonical_line.get("unit_price")),
                    line_total=source_line["line_total"],
                    category=str(canonical_line["category"]),
                    business_disposition=str(canonical_line["business_disposition"]),
                    raw_ocr_item=raw_item,
                    source_id=source.id,
                    source_page=source_page,
                    source_line_number=source_line_number,
                    store_item_id=store_item.store_item_id if store_item is not None else None,
                    item_id=item_id,
                )
            )
            canonical_items.append(deepcopy(canonical_line))

        next_version = receipt.receipt_document_version + 1
        after_document["items"] = canonical_items
        after_document["total_mismatch"] = False
        receipt.receipt_document = after_document
        receipt.receipt_document_version = next_version
        session.add(
            ReceiptCorrection(
                receipt_pk=receipt_pk,
                actor_id=reviewer_id,
                reason=normalized_reason,
                source_event_id="source-association:"
                + hashlib.sha256(event_id.encode()).hexdigest(),
                request_document={
                    "source_id": source.id,
                    "decision": decision.value,
                    "source_event_id": event_id,
                    "confirmed_repeated_line_indexes": list(confirmed_indexes),
                },
                before_document=before_document or {},
                after_document=after_document,
                document_version=next_version,
            )
        )
        source.association_kind = "SUPPLEMENT"
        source.hold_reason = None
        added_line_count = len(supplemental_lines)
    elif decision is SourceDecision.COPY:
        source.association_kind = "COPY"
        added_line_count = 0
    elif decision is SourceDecision.REJECT:
        source.association_kind = "REJECTED"
        added_line_count = 0
    else:
        raise ValueError("Unsupported source decision")

    now = datetime.now(UTC)
    source.decision_event_id = event_id
    source.decision_actor_id = reviewer_id
    source.decision_reason = normalized_reason
    source.decided_at = now
    upload.processing_status = "SUCCEEDED" if decision is SourceDecision.SUPPLEMENT else "DUPLICATE"
    upload.duplicate_status = {
        SourceDecision.SUPPLEMENT: "SUPPLEMENT_ACCEPTED",
        SourceDecision.COPY: "OVERLAPPING_COPY_CONFIRMED",
        SourceDecision.REJECT: "SOURCE_REJECTED",
    }[decision]
    session.add(
        AuditLog(
            event_type="RECEIPT_SOURCE_DECIDED",
            actor=str(reviewer_id),
            entity_type="ReceiptSource",
            entity_id=str(source.id),
            details=json.dumps(
                {
                    "source_event_id": event_id,
                    "decision": decision.value,
                    "reason": normalized_reason,
                    "added_line_count": added_line_count,
                    "confirmed_repeated_line_indexes": list(confirmed_indexes),
                },
                sort_keys=True,
            ),
        )
    )
    session.flush()
    return SourceDecisionResult(source, added_line_count)


def _extracted_lines(source: ReceiptSource) -> list[dict[str, Any]]:
    items = source.extracted_document.get("items")
    if not isinstance(items, list):
        raise ValueError("Source extraction does not contain a valid item list")
    result = []
    for item in items:
        if not isinstance(item, dict) or item.get("line_total") is None:
            raise ValueError("Source extraction line is missing its line total")
        result.append({**item, "line_total": Decimal(str(item["line_total"]))})
    return result


def _source_line_count(source: ReceiptSource) -> int:
    items = source.extracted_document.get("items")
    return len(items) if isinstance(items, list) else 0


def repeated_source_line_indexes(
    existing_lines: Sequence[ReceiptItem],
    source_items: object,
    store_items: Mapping[str, StoreItem],
) -> tuple[int, ...]:
    if not isinstance(source_items, list):
        return ()
    repeated: list[int] = []
    for index, candidate in enumerate(source_items):
        if not isinstance(candidate, dict):
            continue
        candidate_description = _normalized_product_text(candidate.get("description"))
        candidate_upc = _normalized_product_text(candidate.get("upc"))
        candidate_store_product_id = _normalized_product_text(candidate.get("store_product_id"))
        for line in existing_lines:
            if line.is_excluded:
                continue
            store_item = (
                store_items.get(line.store_item_id) if line.store_item_id is not None else None
            )
            if (
                (
                    candidate_description
                    and candidate_description == _normalized_product_text(line.description)
                )
                or (candidate_upc and candidate_upc == _normalized_product_text(line.upc))
                or (
                    candidate_store_product_id
                    and store_item is not None
                    and candidate_store_product_id
                    == _normalized_product_text(store_item.store_product_id)
                )
            ):
                repeated.append(index)
                break
    return tuple(repeated)


def _store_items_for_source_lines(
    session: Session, lines: Sequence[ReceiptItem]
) -> dict[str, StoreItem]:
    store_item_ids = {line.store_item_id for line in lines if line.store_item_id is not None}
    if not store_item_ids:
        return {}
    return {
        store_item.store_item_id: store_item
        for store_item in session.scalars(
            select(StoreItem).where(StoreItem.store_item_id.in_(store_item_ids))
        )
    }


def _normalized_product_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return re.sub(r"\s+", " ", value).strip().casefold()


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _hold_source(
    session: Session,
    source: ReceiptSource,
    reviewer_id: int,
    event_id: str,
    reason: str,
    hold_reason: str,
    details: dict[str, object],
) -> SourceDecisionResult:
    source.hold_reason = hold_reason
    source.hold_event_id = event_id
    source.decision_actor_id = reviewer_id
    source.decision_reason = reason
    session.add(
        AuditLog(
            event_type="RECEIPT_SOURCE_SUPPLEMENT_HELD",
            actor=str(reviewer_id),
            entity_type="ReceiptSource",
            entity_id=str(source.id),
            details=json.dumps(
                {
                    "source_event_id": event_id,
                    "reason": reason,
                    "hold_reason": hold_reason,
                    **details,
                },
                sort_keys=True,
            ),
        )
    )
    return SourceDecisionResult(source, 0, held=True)
