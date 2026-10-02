from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbs.errors import NotFoundError
from mbs.items import (
    item_id_for_date,
    register_store_item,
    remember_store_item_package,
)
from mbs.models import (
    AuditLog,
    Receipt,
    ReceiptCorrection,
    ReceiptCorrectionHold,
    ReceiptItem,
    ReceiptLineApproval,
    ReceiptSource,
    StoreItem,
)
from mbs.receipts.persistence import _decimal_string
from mbs.receipts.units import normalize_unit_alias


class CorrectionStatus(StrEnum):
    UPDATED = "UPDATED"
    HELD_FOR_ADMIN = "HELD_FOR_ADMIN"


class HoldResolutionAction(StrEnum):
    KEEP = "KEEP"
    REKEY = "REKEY"
    REJECT = "REJECT"


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
    receipt = session.scalar(
        select(Receipt)
        .where(Receipt.receipt_pk == receipt_pk, Receipt.deleted_at.is_(None))
        .with_for_update()
    )
    if receipt is None:
        raise NotFoundError("Receipt not found")
    prior_event = session.scalar(
        select(ReceiptCorrection).where(ReceiptCorrection.source_event_id == normalized_event_id)
    )
    if prior_event is not None:
        if (
            prior_event.receipt_pk != receipt_pk
            or prior_event.actor_id != reviewer_id
            or prior_event.reason != normalized_reason
            or prior_event.request_document != request_document
        ):
            raise ValueError("Correction source event ID is already used")
        return CorrectionResult(CorrectionStatus.UPDATED, receipt, idempotent=True)
    items = session.scalars(
        select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt_pk).order_by(ReceiptItem.id)
    ).all()
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
            for store_item in session.scalars(
                select(StoreItem).where(StoreItem.store_item_id.in_(store_item_ids))
            )
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
        source = session.scalar(
            select(ReceiptSource).where(
                ReceiptSource.id == source_id,
                ReceiptSource.receipt_pk == receipt_pk,
                ReceiptSource.association_kind.in_(("PRIMARY", "SUPPLEMENT")),
            )
        )
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
    prior_hold = session.scalar(
        select(ReceiptCorrectionHold).where(
            ReceiptCorrectionHold.source_event_id == normalized_event_id
        )
    )
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
    if (
        session.scalar(
            select(ReceiptLineApproval.id)
            .join(ReceiptItem, ReceiptItem.id == ReceiptLineApproval.receipt_item_id)
            .where(ReceiptItem.receipt_pk == receipt_pk)
            .limit(1)
        )
        is not None
    ):
        raise ValueError("Approved receipts require a linked reversal or replacement workflow")

    collision = session.scalar(
        select(Receipt).where(
            Receipt.receipt_id == proposed_receipt_id,
            Receipt.receipt_pk != receipt_pk,
        )
    )
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
        with session.begin_nested():
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
                session.add(
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
                    )
                )
            receipt.reviewed_by = reviewer_id
            receipt.reviewed_at = datetime.now(UTC)
            receipt.receipt_document = after_document
            receipt.receipt_document_version = next_version
            session.add(
                ReceiptCorrection(
                    receipt_pk=receipt_pk,
                    actor_id=reviewer_id,
                    reason=normalized_reason,
                    source_event_id=normalized_event_id,
                    request_document=request_document,
                    before_document=before_document,
                    after_document=after_document,
                    document_version=next_version,
                )
            )
            session.add(
                AuditLog(
                    event_type="RECEIPT_CORRECTED",
                    actor=str(reviewer_id),
                    entity_type="Receipt",
                    entity_id=receipt_pk,
                    details=f"version={next_version}; reason={normalized_reason}",
                )
            )
            session.flush()
    except IntegrityError as error:
        prior_event = session.scalar(
            select(ReceiptCorrection).where(
                ReceiptCorrection.source_event_id == normalized_event_id
            )
        )
        if prior_event is not None:
            if (
                prior_event.receipt_pk != receipt_pk
                or prior_event.actor_id != reviewer_id
                or prior_event.reason != normalized_reason
                or prior_event.request_document != request_document
            ):
                raise ValueError("Correction source event ID is already used") from error
            return CorrectionResult(CorrectionStatus.UPDATED, receipt, idempotent=True)
        collision = session.scalar(
            select(Receipt).where(
                Receipt.receipt_id == proposed_receipt_id,
                Receipt.receipt_pk != receipt_pk,
            )
        )
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


def _apply_header(receipt: Receipt, values: dict[str, Any], receipt_id: str) -> None:
    receipt.store = values["store"]
    receipt.receipt_date = values["receipt_date"]
    receipt.receipt_time = values["receipt_time"]
    receipt.transaction_number = values["transaction_number"]
    receipt.subtotal = values["subtotal"]
    receipt.tax = values["tax"]
    receipt.total = values["total"]
    receipt.payment_method = values["payment_method"]
    receipt.receipt_id = receipt_id


def _request_document(
    header_updates: dict[str, Any],
    item_updates: dict[int, dict[str, Any]],
    item_additions: Sequence[dict[str, Any]],
    item_exclusions: Sequence[int],
    remember_package_default_indexes: Sequence[int],
) -> dict[str, object]:
    return {
        "header_updates": {
            field: _request_value(value) for field, value in sorted(header_updates.items())
        },
        "item_updates": {
            str(index): {field: _request_value(value) for field, value in sorted(updates.items())}
            for index, updates in sorted(item_updates.items())
        },
        "item_additions": [
            {field: _request_value(value) for field, value in sorted(addition.items())}
            for addition in item_additions
        ],
        "item_exclusions": list(item_exclusions),
        "remember_package_default_indexes": list(remember_package_default_indexes),
    }


def _request_value(value: Any) -> object:
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return _decimal_string(value)
    return value


def _normalize_item_updates(
    item_updates: dict[int, dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    return {
        index: {field: _item_value(field, value) for field, value in updates.items()}
        for index, updates in item_updates.items()
    }


def _normalize_item_additions(
    additions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for addition in additions:
        description = str(addition.get("description", "")).strip()
        if not description or len(description) > 255:
            raise ValueError("Added receipt line requires a description of at most 255 characters")
        package_count = _item_value("package_count", addition.get("package_count"))
        unit_price = _item_value("unit_price", addition.get("unit_price"))
        if package_count is None or package_count <= 0 or unit_price is None or unit_price < 0:
            raise ValueError("Added receipt lines require a positive package count and unit price")
        pack_size = _item_value("pack_size", addition.get("pack_size"))
        if pack_size is not None and pack_size <= 0:
            raise ValueError("Pack size must be positive")
        pack_unit = _item_value("pack_unit", addition.get("pack_unit"))
        store_product_id_value = addition.get("store_product_id")
        store_product_id = (
            str(store_product_id_value).strip() if store_product_id_value is not None else None
        )
        if store_product_id == "" or (store_product_id is not None and len(store_product_id) > 255):
            raise ValueError("Store product identifier must contain at most 255 characters")
        source_id = addition.get("source_id")
        source_page = addition.get("source_page")
        source_line_number = addition.get("source_line_number")
        confirmation = addition.get("confirm_repeated_occurrence", False)
        if not isinstance(confirmation, bool):
            raise ValueError("Repeated occurrence confirmation must be boolean")
        remember_as_default = addition.get("remember_package_as_default", False)
        if not isinstance(remember_as_default, bool):
            raise ValueError("Remember package as default must be boolean")
        if source_id is None and (source_page is not None or source_line_number is not None):
            raise ValueError("Source page and line require a source association")
        if source_id is not None and (
            not isinstance(source_page, int)
            or source_page < 1
            or not isinstance(source_line_number, int)
            or source_line_number < 1
        ):
            raise ValueError("Source page and line positions must be positive integers")
        normalized.append(
            {
                "description": description,
                "upc": addition.get("upc"),
                "store_product_id": store_product_id,
                "package_count": package_count,
                "pack_size": pack_size,
                "pack_unit": pack_unit,
                "unit_price": unit_price,
                "line_total": (package_count * unit_price).quantize(Decimal("0.01")),
                "category": str(addition.get("category") or "Other"),
                "source_id": source_id,
                "source_page": source_page,
                "source_line_number": source_line_number,
                "confirm_repeated_occurrence": confirmation,
                "remember_package_as_default": remember_as_default,
            }
        )
    return normalized


def _normalized_description(value: str) -> str:
    return " ".join(value.casefold().split())


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
        with session.begin_nested():
            hold = ReceiptCorrectionHold(
                receipt_pk=receipt.receipt_pk,
                proposed_receipt_id=proposed_receipt_id,
                proposed_document=proposed_document,
                reviewer_id=reviewer_id,
                reason=reason,
                source_event_id=source_event_id,
            )
            session.add(hold)
            session.add(
                AuditLog(
                    event_type="RECEIPT_CORRECTION_HELD",
                    actor=str(reviewer_id),
                    entity_type="Receipt",
                    entity_id=receipt.receipt_pk,
                    details=f"proposed_receipt_id={proposed_receipt_id}; reason={reason}",
                )
            )
            session.flush()
    except IntegrityError as error:
        existing = session.scalar(
            select(ReceiptCorrectionHold).where(
                ReceiptCorrectionHold.source_event_id == source_event_id
            )
        )
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
    hold = session.scalar(
        select(ReceiptCorrectionHold).where(ReceiptCorrectionHold.id == hold_id).with_for_update()
    )
    if hold is None:
        raise NotFoundError("Correction hold not found")
    if hold.status != "PENDING":
        raise ValueError("Correction hold is already resolved")
    receipt = session.scalar(
        select(Receipt).where(Receipt.receipt_pk == hold.receipt_pk).with_for_update()
    )
    if receipt is None:
        raise NotFoundError("Receipt not found")

    now = datetime.now(UTC)
    if action is HoldResolutionAction.REKEY:
        if new_transaction_number is None or not new_transaction_number.strip():
            raise ValueError("Re-key requires a new transaction number")
        if (
            session.scalar(
                select(ReceiptLineApproval.id)
                .join(ReceiptItem, ReceiptItem.id == ReceiptLineApproval.receipt_item_id)
                .where(ReceiptItem.receipt_pk == receipt.receipt_pk)
                .limit(1)
            )
            is not None
        ):
            raise ValueError("Approved receipts require a linked reversal or replacement workflow")
        proposed_document = hold.proposed_document
        proposed_items = proposed_document.get("items")
        if not isinstance(proposed_items, list) or len(proposed_items) != len(
            session.scalars(
                select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
            ).all()
        ):
            raise ValueError("Correction proposal does not match the receipt items")
        items = session.scalars(
            select(ReceiptItem)
            .where(ReceiptItem.receipt_pk == receipt.receipt_pk)
            .order_by(ReceiptItem.id)
        ).all()
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
            session.scalar(
                select(Receipt.receipt_pk).where(
                    Receipt.receipt_id == proposed_receipt_id,
                    Receipt.receipt_pk != receipt.receipt_pk,
                )
            )
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
            with session.begin_nested():
                _apply_header(receipt, proposed, proposed_receipt_id)
                for index, updates in item_updates.items():
                    for field, value in updates.items():
                        setattr(items[index], field, value)
                receipt.receipt_document = after_document
                receipt.receipt_document_version = next_version
                receipt.reviewed_by = admin_id
                receipt.reviewed_at = now
                session.add(
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
                    )
                )
                session.add(
                    AuditLog(
                        event_type="RECEIPT_CORRECTED",
                        actor=str(admin_id),
                        entity_type="Receipt",
                        entity_id=receipt.receipt_pk,
                        details=f"version={next_version}; reason={normalized_reason}",
                    )
                )
                session.flush()
        except IntegrityError as error:
            collision = session.scalar(
                select(Receipt.receipt_pk).where(
                    Receipt.receipt_id == proposed_receipt_id,
                    Receipt.receipt_pk != receipt.receipt_pk,
                )
            )
            if collision is not None:
                raise ValueError("New receipt identity is already in use") from error
            raise
        hold.status = HoldResolutionAction.REKEY.value
    elif action is HoldResolutionAction.KEEP:
        hold.status = HoldResolutionAction.KEEP.value
    elif action is HoldResolutionAction.REJECT:
        if (
            session.scalar(
                select(ReceiptLineApproval.id)
                .join(ReceiptItem, ReceiptItem.id == ReceiptLineApproval.receipt_item_id)
                .where(ReceiptItem.receipt_pk == receipt.receipt_pk)
                .limit(1)
            )
            is not None
        ):
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
    session.add(
        AuditLog(
            event_type="RECEIPT_CORRECTION_HOLD_RESOLVED",
            actor=str(admin_id),
            entity_type="ReceiptCorrectionHold",
            entity_id=str(hold.id),
            details=f"action={action.value}; reason={normalized_reason}",
        )
    )
    session.flush()
    return hold


def _item_value(field: str, value: Any) -> Any:
    decimal_fields = {
        "quantity",
        "weight_lb",
        "package_count",
        "pack_size",
        "unit_price",
        "line_total",
    }
    if field in decimal_fields and value is not None:
        return Decimal(str(value))
    if field == "pack_unit" and value is not None:
        normalized = normalize_unit_alias(str(value))
        if normalized is None:
            raise ValueError("Pack unit must match a supported unit alias")
        return normalized
    return value


def _proposed_values(receipt: Receipt, updates: dict[str, Any]) -> dict[str, Any]:
    values = {
        "store": receipt.store,
        "receipt_date": receipt.receipt_date,
        "receipt_time": receipt.receipt_time,
        "transaction_number": receipt.transaction_number,
        "subtotal": receipt.subtotal,
        "tax": receipt.tax,
        "total": receipt.total,
        "payment_method": receipt.payment_method,
    }
    for field, value in updates.items():
        if field not in values:
            raise ValueError(f"Unsupported receipt header field: {field}")
        if field == "receipt_date" and isinstance(value, str):
            value = date.fromisoformat(value)
        if field == "receipt_time" and isinstance(value, str):
            value = time.fromisoformat(value)
        if field in {"subtotal", "tax", "total"} and value is not None:
            value = Decimal(str(value))
        values[field] = value
    return values


def _receipt_id(store: str, receipt_date: date, receipt_time: time, transaction_number: str) -> str:
    return f"{store}|{receipt_date.isoformat()}|{receipt_time.isoformat()}|{transaction_number}"


def _document(
    values: dict[str, Any],
    items: Sequence[ReceiptItem],
    item_updates: dict[int, dict[str, Any]],
    excluded_ids: set[int] | None = None,
    item_additions: Sequence[dict[str, Any]] = (),
    exclusion_reason: str | None = None,
) -> dict[str, object]:
    excluded_ids = excluded_ids or set()
    item_documents = []
    for index, item in enumerate(items):
        item_fields = (
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
            "source_id",
            "source_page",
            "source_line_number",
        )
        item_values = {field: getattr(item, field) for field in item_fields}
        item_values.update(item_updates.get(index, {}))
        item_values["is_excluded"] = item.is_excluded or item.id in excluded_ids
        item_values["exclusion_reason"] = (
            exclusion_reason if item.id in excluded_ids else item.exclusion_reason
        )
        item_documents.append(
            {
                field: _decimal_string(value) if isinstance(value, Decimal) else value
                for field, value in item_values.items()
            }
        )
    item_documents.extend(
        {
            field: _decimal_string(value) if isinstance(value, Decimal) else value
            for field, value in {
                **{
                    field: value
                    for field, value in addition.items()
                    if field
                    not in {
                        "confirm_repeated_occurrence",
                        "remember_package_as_default",
                    }
                },
                "quantity": None,
                "weight_lb": None,
                "business_disposition": "UNCLASSIFIED",
                "disposition_subtype": "NONE",
                "is_excluded": False,
                "exclusion_reason": None,
            }.items()
        }
        for addition in item_additions
    )
    line_subtotal = sum(
        (
            Decimal(str(item_document["line_total"]))
            for item_document in item_documents
            if item_document["line_total"] is not None and not item_document["is_excluded"]
        ),
        Decimal("0"),
    )
    expected_subtotal = values["subtotal"]
    if expected_subtotal is None:
        expected_subtotal = values["total"] - (values["tax"] or Decimal("0"))
    return {
        "receipt_id": _receipt_id(
            values["store"],
            values["receipt_date"],
            values["receipt_time"],
            values["transaction_number"],
        ),
        "store": values["store"],
        "date": values["receipt_date"].isoformat(),
        "time": values["receipt_time"].isoformat(),
        "transaction_number": values["transaction_number"],
        "subtotal": _decimal_string(values["subtotal"]),
        "tax": _decimal_string(values["tax"]),
        "total": _decimal_string(values["total"]),
        "payment_method": values["payment_method"],
        "total_mismatch": (
            line_subtotal.quantize(Decimal("0.01")) != expected_subtotal.quantize(Decimal("0.01"))
        ),
        "items": item_documents,
    }


def _validate_disposition_pair(disposition: object, subtype: object) -> None:
    ordinary_subtypes = {"DIRECT_EXPENSE", "STOCKED_SUPPLY", "DIRECT_SELL_RESTOCK"}
    if disposition == "ORDINARY_BUSINESS_PURCHASE":
        if subtype not in ordinary_subtypes:
            raise ValueError("Ordinary Business Purchase requires a legal disposition subtype")
    elif disposition in {
        "UNCLASSIFIED",
        "PERSONAL_NON_BUSINESS",
        "RECIPE_INGREDIENT",
        "CAPITAL_ASSET_EQUIPMENT",
    }:
        if subtype != "NONE":
            raise ValueError("This business disposition requires subtype NONE")
    else:
        raise ValueError("Unsupported receipt business disposition")
