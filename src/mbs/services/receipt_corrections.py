from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbs.domain.receipt_corrections import (
    CorrectionStatus,
    _normalize_item_additions,
    _normalize_item_updates,
    _normalized_description,
    _receipt_id,
    _request_document,
    _validate_disposition_pair,
)
from mbs.errors import NotFoundError
from mbs.items import item_id_for_date, register_store_item, remember_store_item_package
from mbs.models import AuditLog, Receipt, ReceiptCorrection, ReceiptCorrectionHold, ReceiptItem
from mbs.repositories.receipt_corrections import ReceiptCorrectionRepository
from mbs.services.receipt_correction_state import _apply_header, _document, _proposed_values

repository = ReceiptCorrectionRepository()


@dataclass(frozen=True)
class CorrectionResult:
    status: CorrectionStatus
    receipt: Receipt
    hold: ReceiptCorrectionHold | None = None
    idempotent: bool = False


def review_receipt(
    session: Session,
    receipt_pk: str,
    reviewer_id: int,
    reason: str,
    source_event_id: str,
    header_updates: dict[str, Any] | None = None,
    item_updates: dict[int, dict[str, Any]] | None = None,
    item_additions: Sequence[Mapping[str, Any]] | None = None,
    item_exclusions: Sequence[int] | None = None,
    remember_package_default_indexes: Sequence[int] = (),
) -> CorrectionResult:
    normalized_reason = reason.strip()
    normalized_event_id = source_event_id.strip()
    if not normalized_reason or not normalized_event_id:
        raise ValueError("Correction reason and source event ID are required")
    item_changes = _normalize_item_updates(item_updates or {})
    additions = _normalize_item_additions(item_additions or ())
    excluded_ids = tuple(sorted(set(item_exclusions or ())))
    remembered_indexes = tuple(sorted(set(remember_package_default_indexes)))
    request_document = _request_document(
        header_updates or {}, item_changes, additions, excluded_ids, remembered_indexes
    )
    receipt = repository.get_receipt(session, receipt_pk, active_only=True, lock=True)
    if receipt is None:
        raise NotFoundError("Receipt not found")
    prior_event = repository.correction_event(session, normalized_event_id)
    if prior_event is not None:
        if (
            prior_event.receipt_pk != receipt_pk
            or prior_event.actor_id != reviewer_id
            or prior_event.reason != normalized_reason
            or prior_event.request_document != request_document
        ):
            raise ValueError("Correction source event ID is already used")
        return CorrectionResult(CorrectionStatus.UPDATED, receipt, idempotent=True)
    items = repository.lines(session, receipt_pk)
    items_by_id = {item.id: item for item in items}
    if any(item_id not in items_by_id for item_id in excluded_ids):
        raise IndexError("Receipt item to exclude does not belong to this receipt")
    if any(items_by_id[item_id].is_excluded for item_id in excluded_ids):
        raise ValueError("Receipt item is already excluded")
    if any(not 0 <= index < len(items) for index in remembered_indexes):
        raise IndexError("Remembered package line index is out of range")
    if any(index not in item_changes for index in remembered_indexes):
        raise ValueError("Remembered package defaults require a corrected receipt line")
    store_item_ids = {item.store_item_id for item in items if item.store_item_id is not None}
    existing_product_ids = (
        {
            store_item.store_item_id: store_item.store_product_id
            for store_item in repository.store_items(session, store_item_ids)
        }
        if store_item_ids
        else {}
    )
    for addition in additions:
        source_id = addition.get("source_id")
        if source_id is None:
            if receipt.source_type != "MANUAL":
                raise ValueError("Added OCR receipt lines require source provenance")
            continue
        source = repository.accepted_source(session, source_id, receipt_pk)
        if source is None:
            raise ValueError("Added receipt line source is not accepted for this receipt")
        if addition.get("source_page") is None or addition.get("source_line_number") is None:
            raise ValueError("Added receipt lines require source page and line provenance")
    for addition_index, addition in enumerate(additions):
        for item in items:
            if item.is_excluded or item.id in excluded_ids:
                continue
            same_source_line = (
                addition.get("source_id") == item.source_id
                and addition.get("source_page") == item.source_page
                and addition.get("source_line_number") == item.source_line_number
            )
            if same_source_line and addition.get("source_id") is not None:
                raise ValueError("This source line occurrence is already present")
            same_upc = (
                addition.get("upc") is not None
                and item.upc is not None
                and str(addition["upc"]).strip() == item.upc.strip()
            )
            same_description = _normalized_description(addition["description"]) == (
                _normalized_description(item.description)
            )
            same_store_product_id = (
                addition.get("store_product_id") is not None
                and item.store_item_id is not None
                and existing_product_ids.get(item.store_item_id) == addition.get("store_product_id")
            )
            if (same_upc or same_description or same_store_product_id) and not addition[
                "confirm_repeated_occurrence"
            ]:
                raise ValueError(
                    "Reviewer must explicitly confirm this repeated product as a new occurrence"
                )
        for previous_addition in additions[:addition_index]:
            same_source_line = (
                addition.get("source_id") == previous_addition.get("source_id")
                and addition.get("source_page") == previous_addition.get("source_page")
                and addition.get("source_line_number")
                == previous_addition.get("source_line_number")
            )
            if same_source_line and addition.get("source_id") is not None:
                raise ValueError("This source line occurrence is already present")
            same_upc = (
                addition.get("upc") is not None
                and previous_addition.get("upc") is not None
                and str(addition["upc"]).strip() == str(previous_addition["upc"]).strip()
            )
            same_description = _normalized_description(addition["description"]) == (
                _normalized_description(previous_addition["description"])
            )
            same_store_product_id = addition.get("store_product_id") is not None and addition.get(
                "store_product_id"
            ) == previous_addition.get("store_product_id")
            if (same_upc or same_description or same_store_product_id) and not addition[
                "confirm_repeated_occurrence"
            ]:
                raise ValueError(
                    "Reviewer must explicitly confirm this repeated product as a new occurrence"
                )
    for index, updates in item_changes.items():
        if not 0 <= index < len(items):
            raise IndexError(f"Receipt item index out of range: {index}")
        for field in updates:
            if field not in {
                "description",
                "upc",
                "package_count",
                "pack_size",
                "pack_unit",
                "unit_price",
                "category",
                "business_disposition",
                "disposition_subtype",
            }:
                raise ValueError(f"Unsupported receipt item field: {field}")
            proposed_disposition = updates.get(
                "business_disposition", items[index].business_disposition
            )
            proposed_subtype = updates.get("disposition_subtype", items[index].disposition_subtype)
            _validate_disposition_pair(proposed_disposition, proposed_subtype)
        package_count = updates.get("package_count", items[index].package_count)
        unit_price = updates.get("unit_price", items[index].unit_price)
        if ("package_count" in updates or "unit_price" in updates) and (
            package_count is not None and unit_price is not None
        ):
            updates["line_total"] = (package_count * unit_price).quantize(Decimal("0.01"))
    proposed = _proposed_values(receipt, header_updates or {})
    proposed_receipt_id = _receipt_id(
        proposed["store"],
        proposed["receipt_date"],
        proposed["receipt_time"],
        proposed["transaction_number"],
    )
    if (item_changes or additions or excluded_ids) and proposed_receipt_id != receipt.receipt_id:
        raise ValueError("Correct receipt identity separately from receipt-line changes")
    after_document = _document(
        proposed,
        items,
        item_changes,
        set(excluded_ids),
        additions,
        normalized_reason,
    )
    prior_hold = repository.hold_event(session, normalized_event_id)
    if prior_hold is not None:
        if (
            prior_hold.receipt_pk != receipt_pk
            or prior_hold.reviewer_id != reviewer_id
            or prior_hold.reason != normalized_reason
            or prior_hold.proposed_receipt_id != proposed_receipt_id
            or prior_hold.proposed_document != after_document
        ):
            raise ValueError("Correction source event ID is already used")
        return CorrectionResult(
            CorrectionStatus.HELD_FOR_ADMIN, receipt, prior_hold, idempotent=True
        )
    if repository.first_approval_id(session, receipt_pk) is not None:
        raise ValueError("Approved receipts require a linked reversal or replacement workflow")

    collision = repository.receipt_collision(session, proposed_receipt_id, receipt_pk)
    if collision is not None:
        hold = _create_hold(
            session,
            receipt,
            reviewer_id,
            normalized_reason,
            normalized_event_id,
            proposed_receipt_id,
            after_document,
        )
        return CorrectionResult(CorrectionStatus.HELD_FOR_ADMIN, receipt, hold)

    before_document = deepcopy(receipt.receipt_document)
    next_version = receipt.receipt_document_version + 1
    try:
        with repository.savepoint(session):
            _apply_header(receipt, proposed, proposed_receipt_id)
            for index, updates in item_changes.items():
                for field, value in updates.items():
                    setattr(items[index], field, value)
            for index in remembered_indexes:
                line = items[index]
                if line.store_item_id is None or line.pack_size is None or line.pack_unit is None:
                    raise ValueError(
                        "Remembering a package requires a store item, pack size, and pack unit"
                    )
                remember_store_item_package(
                    session,
                    line.store_item_id,
                    line.pack_size,
                    line.pack_unit,
                    reviewer_id,
                    normalized_reason,
                )
            for item_id in excluded_ids:
                items_by_id[item_id].is_excluded = True
                items_by_id[item_id].exclusion_reason = normalized_reason
            for addition in additions:
                store_product_id = addition["store_product_id"]
                identifier_source: Literal["MERCHANT", "USER_ENTERED", "MANUAL"] = "USER_ENTERED"
                if receipt.source_type == "MANUAL":
                    if store_product_id is None:
                        store_product_id = f"MANUAL:{uuid4()}"
                    if store_product_id.startswith("MANUAL:"):
                        identifier_source = "MANUAL"
                elif store_product_id is not None and store_product_id.startswith("MANUAL:"):
                    raise ValueError("MANUAL identifiers are reserved for manual receipts")
                store_item = (
                    register_store_item(
                        session,
                        receipt.store_id,
                        store_product_id,
                        addition["description"],
                        addition["upc"],
                        identifier_source,
                        actor_id=reviewer_id,
                        effective_from=receipt.receipt_date,
                    )
                    if store_product_id is not None
                    else None
                )
                if addition["remember_package_as_default"]:
                    if (
                        store_item is None
                        or addition["pack_size"] is None
                        or addition["pack_unit"] is None
                    ):
                        raise ValueError(
                            "Remembering a package requires an identified item, pack size, and unit"
                        )
                    remember_store_item_package(
                        session,
                        store_item.store_item_id,
                        addition["pack_size"],
                        addition["pack_unit"],
                        reviewer_id,
                        normalized_reason,
                    )
                repository.add(
                    session,
                    ReceiptItem(
                        receipt_pk=receipt_pk,
                        description=addition["description"],
                        upc=addition.get("upc"),
                        package_count=addition["package_count"],
                        pack_size=addition.get("pack_size"),
                        pack_unit=addition.get("pack_unit"),
                        unit_price=addition["unit_price"],
                        line_total=addition["line_total"],
                        category=addition["category"],
                        business_disposition="UNCLASSIFIED",
                        disposition_subtype="NONE",
                        raw_ocr_item=None,
                        source_id=addition.get("source_id"),
                        source_page=addition.get("source_page"),
                        source_line_number=addition.get("source_line_number"),
                        store_item_id=(
                            store_item.store_item_id if store_item is not None else None
                        ),
                        item_id=(
                            item_id_for_date(
                                session, store_item.store_item_id, receipt.receipt_date
                            )
                            if store_item is not None
                            else None
                        ),
                    ),
                )
            receipt.reviewed_by = reviewer_id
            receipt.reviewed_at = datetime.now(UTC)
            receipt.receipt_document = after_document
            receipt.receipt_document_version = next_version
            repository.add(
                session,
                ReceiptCorrection(
                    receipt_pk=receipt_pk,
                    actor_id=reviewer_id,
                    reason=normalized_reason,
                    source_event_id=normalized_event_id,
                    request_document=request_document,
                    before_document=before_document,
                    after_document=after_document,
                    document_version=next_version,
                ),
            )
            repository.add(
                session,
                AuditLog(
                    event_type="RECEIPT_CORRECTED",
                    actor=str(reviewer_id),
                    entity_type="Receipt",
                    entity_id=receipt_pk,
                    details=f"version={next_version}; reason={normalized_reason}",
                ),
            )
            repository.flush(session)
    except IntegrityError as error:
        prior_event = repository.correction_event(session, normalized_event_id)
        if prior_event is not None:
            if (
                prior_event.receipt_pk != receipt_pk
                or prior_event.actor_id != reviewer_id
                or prior_event.reason != normalized_reason
                or prior_event.request_document != request_document
            ):
                raise ValueError("Correction source event ID is already used") from error
            return CorrectionResult(CorrectionStatus.UPDATED, receipt, idempotent=True)
        collision = repository.receipt_collision(session, proposed_receipt_id, receipt_pk)
        if collision is None:
            raise
        hold = _create_hold(
            session,
            receipt,
            reviewer_id,
            normalized_reason,
            normalized_event_id,
            proposed_receipt_id,
            after_document,
        )
        return CorrectionResult(CorrectionStatus.HELD_FOR_ADMIN, receipt, hold)
    return CorrectionResult(CorrectionStatus.UPDATED, receipt)


def _create_hold(
    session: Session,
    receipt: Receipt,
    reviewer_id: int,
    reason: str,
    source_event_id: str,
    proposed_receipt_id: str,
    proposed_document: dict[str, object],
) -> ReceiptCorrectionHold:
    try:
        with repository.savepoint(session):
            hold = ReceiptCorrectionHold(
                receipt_pk=receipt.receipt_pk,
                proposed_receipt_id=proposed_receipt_id,
                proposed_document=proposed_document,
                reviewer_id=reviewer_id,
                reason=reason,
                source_event_id=source_event_id,
            )
            repository.add(session, hold)
            repository.add(
                session,
                AuditLog(
                    event_type="RECEIPT_CORRECTION_HELD",
                    actor=str(reviewer_id),
                    entity_type="Receipt",
                    entity_id=receipt.receipt_pk,
                    details=f"proposed_receipt_id={proposed_receipt_id}; reason={reason}",
                ),
            )
            repository.flush(session)
    except IntegrityError as error:
        existing = repository.hold_event(session, source_event_id)
        if (
            existing is None
            or existing.receipt_pk != receipt.receipt_pk
            or existing.reviewer_id != reviewer_id
            or existing.reason != reason
            or existing.proposed_receipt_id != proposed_receipt_id
            or existing.proposed_document != proposed_document
        ):
            raise ValueError("Correction source event ID is already used") from error
        return existing
    return hold
