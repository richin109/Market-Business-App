from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement
from starlette.responses import Response

from mbs.db import get_session
from mbs.models import (
    AuditLog,
    AuthSession,
    Item,
    MediaAsset,
    MediaAssetLink,
    Receipt,
    ReceiptCorrectionHold,
    ReceiptItem,
    ReceiptLineApproval,
    ReceiptRoutingRecord,
    ReceiptSource,
    ReceiptUpload,
    Store,
    StoreItem,
    User,
)
from mbs.receipts.approval import (
    ApprovalResult,
    DispositionSubtype,
    approve_receipt_item,
    reclassify_expense_routing,
    validate_disposition_pair,
)
from mbs.receipts.corrections import (
    HoldResolutionAction,
    resolve_correction_hold,
    review_receipt,
)
from mbs.receipts.lifecycle import soft_delete_receipt
from mbs.receipts.manual import create_manual_receipt
from mbs.receipts.ocr import BusinessDisposition
from mbs.receipts.rules import RememberedItemRule, RuleMatchKind, find_item_rule
from mbs.receipts.sources import (
    SourceDecision,
    decide_receipt_source,
    repeated_source_line_indexes,
)
from mbs.receipts.tasks import dispatch_pending_receipt_uploads
from mbs.receipts.units import UNIT_ALIASES
from mbs.receipts.upload import ReceiptUploadService, UploadStatus
from mbs.routers.dependencies import (
    BoundedUpload,
    admin_csrf_session,
    admin_session,
    authorized_upload_body,
    current_session_user,
    domain_http_error,
    get_receipt_upload_service,
    manager_csrf_session,
    manager_session,
)

router = APIRouter(prefix="/api/v1", tags=["receipts"])
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory=str(Path(__file__).parents[1] / "templates"))


class ReceiptItemAdditionRequest(BaseModel):
    description: str = Field(min_length=1, max_length=255)
    category: str = Field(default="Other", min_length=1, max_length=50)
    store_product_id: str | None = Field(default=None, max_length=255)
    package_count: Decimal = Field(gt=0)
    pack_size: Decimal | None = Field(default=None, gt=0)
    pack_unit: str | None = Field(default=None, max_length=30)
    unit_price: Decimal = Field(ge=0)
    upc: str | None = Field(default=None, max_length=50)
    source_id: int | None = Field(default=None, gt=0)
    source_page: int | None = Field(default=None, gt=0)
    source_line_number: int | None = Field(default=None, gt=0)
    confirm_repeated_occurrence: bool = False
    remember_package_as_default: bool = False


class ReceiptCorrectionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    source_event_id: str = Field(min_length=1, max_length=255)
    header_updates: dict[str, object] = Field(default_factory=dict)
    item_updates: dict[int, dict[str, object]] = Field(default_factory=dict)
    item_additions: list[ReceiptItemAdditionRequest] = Field(default_factory=list, max_length=50)
    item_exclusions: list[int] = Field(default_factory=list, max_length=100)
    remember_package_default_indexes: list[int] = Field(default_factory=list, max_length=100)


class CorrectionHoldResolutionRequest(BaseModel):
    action: HoldResolutionAction
    reason: str = Field(min_length=1, max_length=2000)
    new_transaction_number: str | None = Field(default=None, max_length=100)


class NearMatchResolutionRequest(BaseModel):
    process_as_new: bool


class ReceiptDeleteRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class ReceiptApprovalRequest(BaseModel):
    disposition: BusinessDisposition
    disposition_subtype: DispositionSubtype
    source_event_id: str = Field(min_length=1, max_length=255)
    update_remembered_rule: bool = False


class ReceiptRerouteRequest(ReceiptApprovalRequest):
    reason: str = Field(min_length=1, max_length=2000)


class ReceiptSourceDecisionRequest(BaseModel):
    decision: SourceDecision
    reason: str = Field(min_length=1, max_length=2000)
    source_event_id: str = Field(min_length=1, max_length=255)
    confirmed_repeated_line_indexes: list[int] = Field(default_factory=list, max_length=100)


class ReceiptImageCandidateDecisionRequest(BaseModel):
    decision: Literal["CONFIRM", "REJECT"]
    reason: str | None = Field(default=None, max_length=2000)
    receipt_item_id: int | None = Field(default=None, gt=0)
    replace_primary: bool | None = None


class ManualReceiptLineRequest(BaseModel):
    description: str = Field(min_length=1, max_length=255)
    store_product_id: str | None = Field(default=None, max_length=255)
    upc: str | None = Field(default=None, max_length=50)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    line_total: Decimal = Field(ge=0)
    category: str = Field(min_length=1, max_length=50)
    business_disposition: BusinessDisposition
    disposition_subtype: DispositionSubtype = DispositionSubtype.NONE

    @model_validator(mode="after")
    def validate_subtype(self) -> ManualReceiptLineRequest:
        validate_disposition_pair(self.business_disposition, self.disposition_subtype)
        return self


class ManualReceiptRequest(BaseModel):
    source_event_id: str = Field(min_length=1, max_length=255)
    store_id: str = Field(min_length=1, max_length=36)
    receipt_date: date
    vendor_reference: str | None = Field(default=None, max_length=100)
    receipt_time: time | None = None
    subtotal: Decimal | None = Field(default=None, ge=0)
    tax: Decimal | None = Field(default=None, ge=0)
    total: Decimal = Field(ge=0)
    payment_method: str | None = Field(default=None, max_length=50)
    items: list[ManualReceiptLineRequest] = Field(min_length=1, max_length=100)


@router.get("/receipts/manual/page", include_in_schema=False)
def manual_receipt_page(
    request: Request,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> Response:
    stores = session.scalars(
        select(Store)
        .where(Store.is_active.is_(True), Store.superseded_by_store_id.is_(None))
        .order_by(Store.display_name, Store.store_id)
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="manual_receipt.html",
        context={"stores": stores},
    )


@router.post("/receipts/manual", status_code=status.HTTP_201_CREATED)
def enter_manual_receipt(
    payload: ManualReceiptRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        receipt = create_manual_receipt(
            session,
            user,
            store_id=payload.store_id,
            receipt_date=payload.receipt_date,
            vendor_reference=payload.vendor_reference,
            receipt_time=payload.receipt_time,
            subtotal=payload.subtotal,
            tax=payload.tax,
            total=payload.total,
            payment_method=payload.payment_method,
            lines=[line.model_dump() for line in payload.items],
            source_event_id=payload.source_event_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    receipt_items = session.scalars(
        select(ReceiptItem)
        .where(ReceiptItem.receipt_pk == receipt.receipt_pk)
        .order_by(ReceiptItem.id)
    ).all()
    store_items = _store_items_for_lines(session, receipt_items)
    return {
        "receipt_pk": receipt.receipt_pk,
        "receipt_id": receipt.receipt_id,
        "source_type": receipt.source_type,
        "item_count": len(payload.items),
        "items": _manual_item_responses(receipt_items, store_items),
    }


@router.get("/receipts")
def list_receipts(
    store: str | None = None,
    store_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = 50,
    _current: tuple[User, AuthSession] = Depends(current_session_user),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> list[dict[str, object]]:
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pagination")
    filters: list[ColumnElement[bool]] = [Receipt.deleted_at.is_(None)]
    if store is not None:
        filters.append(Receipt.store == store)
    if store_id is not None:
        filters.append(Receipt.store_id == store_id)
    if date_from is not None:
        filters.append(Receipt.receipt_date >= date_from)
    if date_to is not None:
        filters.append(Receipt.receipt_date <= date_to)
    item_counts = (
        select(ReceiptItem.receipt_pk, func.count(ReceiptItem.id).label("item_count"))
        .where(ReceiptItem.is_excluded.is_(False))
        .group_by(ReceiptItem.receipt_pk)
        .subquery()
    )
    receipt_rows = session.execute(
        select(Receipt, func.coalesce(item_counts.c.item_count, 0))
        .outerjoin(item_counts, item_counts.c.receipt_pk == Receipt.receipt_pk)
        .where(*filters)
        .order_by(Receipt.receipt_date.desc(), Receipt.receipt_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [
        {
            "receipt_pk": receipt.receipt_pk,
            "receipt_id": receipt.receipt_id,
            "store": receipt.store,
            "store_id": receipt.store_id,
            "purchase_date": receipt.receipt_date.isoformat(),
            "item_count": item_count,
        }
        for receipt, item_count in receipt_rows
    ]


@router.get("/receipts/{receipt_pk}")
def get_receipt(
    receipt_pk: str,
    _current: tuple[User, AuthSession] = Depends(current_session_user),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    receipt = session.scalar(
        select(Receipt).where(Receipt.receipt_pk == receipt_pk, Receipt.deleted_at.is_(None))
    )
    if receipt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    items = session.scalars(
        select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt_pk).order_by(ReceiptItem.id)
    ).all()
    store_items = _store_items_for_lines(session, items)
    sources = session.scalars(
        select(ReceiptSource)
        .where(ReceiptSource.receipt_pk == receipt_pk)
        .order_by(ReceiptSource.id)
    ).all()
    return _receipt_response(receipt, items, store_items, sources)


@router.delete("/receipts/{receipt_pk}")
def delete_receipt(
    receipt_pk: str,
    payload: ReceiptDeleteRequest,
    current: tuple[User, AuthSession] = Depends(admin_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        deleted = soft_delete_receipt(session, receipt_pk, user.id, payload.reason)
    except ValueError as error:
        raise domain_http_error(error, status.HTTP_409_CONFLICT) from error
    session.commit()
    return {"receipt_pk": receipt_pk, "deleted": True, "idempotent": not deleted}


@router.get("/receipts/{receipt_pk}/sources/{source_id}/content")
def get_receipt_source_content(
    receipt_pk: str,
    source_id: int,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    service: ReceiptUploadService = Depends(get_receipt_upload_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> Response:
    source_row = session.execute(
        select(ReceiptSource, ReceiptUpload)
        .join(ReceiptUpload, ReceiptUpload.upload_pk == ReceiptSource.upload_pk)
        .join(Receipt, Receipt.receipt_pk == ReceiptSource.receipt_pk)
        .where(
            ReceiptSource.id == source_id,
            ReceiptSource.receipt_pk == receipt_pk,
            Receipt.deleted_at.is_(None),
        )
    ).one_or_none()
    if source_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Receipt source not found"
        )
    _, upload = source_row
    if upload.media_type not in {"application/pdf", "image/jpeg", "image/png"}:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)
    try:
        content = service.read_protected_source(upload.file_key)
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Protected source is unavailable"
        ) from error
    except (OSError, RuntimeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Source viewing unavailable"
        ) from error
    return Response(
        content,
        media_type=upload.media_type,
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "Content-Disposition": "inline; filename=receipt-source",
            "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "same-origin",
        },
    )


@router.get("/receipts/{receipt_pk}/items")
def get_receipt_items(
    receipt_pk: str,
    _current: tuple[User, AuthSession] = Depends(current_session_user),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> list[dict[str, object]]:
    receipt = session.scalar(
        select(Receipt).where(Receipt.receipt_pk == receipt_pk, Receipt.deleted_at.is_(None))
    )
    if receipt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    items = session.scalars(
        select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt_pk).order_by(ReceiptItem.id)
    ).all()
    store_items = _store_items_for_lines(session, items)
    response_items: list[dict[str, object]] = []
    for item in items:
        store_item = store_items.get(item.store_item_id) if item.store_item_id is not None else None
        response_items.append(
            {
                **_item_response(item, store_item, receipt.source_type),
                "remembered_disposition": (
                    store_item.last_disposition if store_item is not None else None
                ),
                "remembered_disposition_subtype": (
                    store_item.last_disposition_subtype if store_item is not None else None
                ),
            }
        )
    return response_items


@router.post("/receipts/{receipt_pk}/sources/{source_id}/decision")
def decide_receipt_source_route(
    receipt_pk: str,
    source_id: int,
    payload: ReceiptSourceDecisionRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        result = decide_receipt_source(
            session,
            receipt_pk,
            source_id,
            user.id,
            payload.decision,
            payload.reason,
            payload.source_event_id,
            payload.confirmed_repeated_line_indexes,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    session.commit()
    return {
        "receipt_pk": receipt_pk,
        "source_id": source_id,
        "association_kind": result.source.association_kind,
        "added_line_count": result.added_line_count,
        "held": result.held,
        "hold_reason": result.source.hold_reason,
        "idempotent": result.idempotent,
    }


@router.get(
    "/receipts/{receipt_pk}/image-candidates/{candidate_id}/thumbnail",
    include_in_schema=False,
)
def get_receipt_image_candidate_thumbnail(
    receipt_pk: str,
    candidate_id: int,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    service: ReceiptUploadService = Depends(get_receipt_upload_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> Response:
    row = session.execute(
        select(MediaAssetLink, MediaAsset)
        .join(MediaAsset, MediaAsset.asset_sha256 == MediaAssetLink.asset_sha256)
        .join(ReceiptSource, ReceiptSource.id == MediaAssetLink.source_id)
        .join(Receipt, Receipt.receipt_pk == ReceiptSource.receipt_pk)
        .where(
            MediaAssetLink.id == candidate_id,
            MediaAssetLink.owner_kind == "RECEIPT_LINE_CANDIDATE",
            ReceiptSource.receipt_pk == receipt_pk,
            ReceiptSource.association_kind != "REJECTED",
            Receipt.deleted_at.is_(None),
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image candidate not found"
        )
    _, asset = row
    if asset.ingest_status != "READY":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image candidate is not ready",
        )
    try:
        content = service.read_protected_source(asset.thumbnail_file_key)
    except (OSError, RuntimeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Protected image candidate is unavailable",
        ) from error
    return Response(
        content,
        media_type=asset.thumbnail_media_type,
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "same-origin",
        },
    )


@router.post("/receipts/{receipt_pk}/image-candidates/{candidate_id}/decision")
def decide_receipt_image_candidate(
    receipt_pk: str,
    candidate_id: int,
    payload: ReceiptImageCandidateDecisionRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    receipt = session.scalar(
        select(Receipt)
        .where(Receipt.receipt_pk == receipt_pk, Receipt.deleted_at.is_(None))
        .with_for_update()
    )
    if receipt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image candidate not found"
        )
    candidate = session.scalar(
        select(MediaAssetLink)
        .join(ReceiptSource, ReceiptSource.id == MediaAssetLink.source_id)
        .where(
            MediaAssetLink.id == candidate_id,
            MediaAssetLink.owner_kind == "RECEIPT_LINE_CANDIDATE",
            ReceiptSource.receipt_pk == receipt_pk,
            ReceiptSource.association_kind != "REJECTED",
        )
        .with_for_update()
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image candidate not found"
        )
    if payload.decision == "REJECT":
        reason = (payload.reason or "").strip()
        if not reason:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A rejection reason is required",
            )
        if candidate.status == "REJECTED":
            return {"candidate_id": candidate.id, "status": candidate.status, "idempotent": True}
        if candidate.status != "PENDING":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Candidate is already confirmed"
            )
        candidate.status = "REJECTED"
        candidate.rejection_reason = reason
        session.add(
            AuditLog(
                event_type="RECEIPT_IMAGE_CANDIDATE_REJECTED",
                actor=str(user.id),
                entity_type="MediaAssetLink",
                entity_id=str(candidate.id),
                details=f"source_id={candidate.source_id}; reason_required=true",
            )
        )
        session.commit()
        return {"candidate_id": candidate.id, "status": candidate.status, "idempotent": False}

    if candidate.status == "CONFIRMED":
        return {"candidate_id": candidate.id, "status": candidate.status, "idempotent": True}
    if candidate.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Rejected candidate cannot be confirmed",
        )
    current_line = (
        session.scalar(
            select(ReceiptItem)
            .where(
                ReceiptItem.id == candidate.receipt_item_id,
                ReceiptItem.receipt_pk == receipt_pk,
            )
            .with_for_update()
        )
        if candidate.receipt_item_id is not None
        else None
    )
    if current_line is not None and payload.receipt_item_id not in {None, current_line.id}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An associated image candidate cannot be reassigned to another line",
        )
    receipt_item_id = payload.receipt_item_id or candidate.receipt_item_id
    line: ReceiptItem | None = current_line
    if receipt_item_id is not None and (line is None or line.id != receipt_item_id):
        line = session.scalar(
            select(ReceiptItem)
            .where(
                ReceiptItem.id == receipt_item_id,
                ReceiptItem.receipt_pk == receipt_pk,
            )
            .with_for_update()
        )
    if line is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Choose a receipt line before confirming this image",
        )
    store_item = (
        session.scalar(
            select(StoreItem).where(StoreItem.store_item_id == line.store_item_id).with_for_update()
        )
        if line.store_item_id is not None
        else None
    )
    if line.store_item_id is not None and store_item is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The receipt line's store item is unavailable",
        )
    owner_kind: str
    owner_id: str | None
    if store_item is not None and store_item.mapping_confirmed and line.item_id is not None:
        owner_kind, owner_id = "ITEM", line.item_id
    elif store_item is not None:
        owner_kind, owner_id = "STORE_ITEM", store_item.store_item_id
    else:
        owner_kind, owner_id = "ITEM", line.item_id
    if owner_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Map this receipt line before confirming its image",
        )
    owner_model = Item if owner_kind == "ITEM" else StoreItem
    owner_key = "item_id" if owner_kind == "ITEM" else "store_item_id"
    owner = session.scalar(
        select(owner_model)
        .where(getattr(owner_model, owner_key) == str(owner_id))
        .with_for_update()
    )
    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The receipt line's item mapping is unavailable",
        )
    primary = session.scalar(
        select(MediaAssetLink)
        .where(
            MediaAssetLink.owner_kind == owner_kind,
            MediaAssetLink.owner_id == str(owner_id),
            MediaAssetLink.status == "CONFIRMED",
            MediaAssetLink.is_primary.is_(True),
            MediaAssetLink.detached_at.is_(None),
        )
        .with_for_update()
    )
    same_asset = session.scalar(
        select(MediaAssetLink)
        .where(
            MediaAssetLink.owner_kind == owner_kind,
            MediaAssetLink.owner_id == str(owner_id),
            MediaAssetLink.asset_sha256 == candidate.asset_sha256,
            MediaAssetLink.status == "CONFIRMED",
            MediaAssetLink.detached_at.is_(None),
        )
        .with_for_update()
    )
    if same_asset is None and primary is not None and payload.replace_primary is None:
        session.rollback()
        return {
            "candidate_id": candidate_id,
            "replace_prompt_required": True,
            "primary_label": owner_kind,
        }
    replace_primary = payload.replace_primary is True
    becomes_primary = (
        same_asset.is_primary if same_asset is not None else primary is None or replace_primary
    )
    try:
        with session.begin_nested():
            if primary is not None and same_asset is None and replace_primary:
                primary.is_primary = False
            if same_asset is not None and primary is None:
                same_asset.is_primary = True
            candidate.status = "CONFIRMED"
            if candidate.receipt_item_id is None:
                candidate.receipt_item_id = line.id
            if same_asset is None:
                session.add(
                    MediaAssetLink(
                        asset_sha256=candidate.asset_sha256,
                        owner_kind=owner_kind,
                        owner_id=str(owner_id),
                        status="CONFIRMED",
                        is_primary=becomes_primary,
                        source_id=candidate.source_id,
                        receipt_item_id=line.id,
                        source_page=candidate.source_page,
                        source_region=candidate.source_region,
                        created_by=user.id,
                    )
                )
            session.add(
                AuditLog(
                    event_type="RECEIPT_IMAGE_CANDIDATE_CONFIRMED",
                    actor=str(user.id),
                    entity_type="MediaAssetLink",
                    entity_id=str(candidate.id),
                    details=(
                        f"receipt_item_id={line.id}; owner_kind={owner_kind}; "
                        f"is_primary={becomes_primary}"
                    ),
                )
            )
            session.flush()
    except IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The primary image changed; refresh and review this candidate again",
        ) from error
    session.commit()
    return {
        "candidate_id": candidate.id,
        "status": candidate.status,
        "is_primary": becomes_primary,
        "idempotent": False,
    }


@router.get("/receipts/{receipt_pk}/review", include_in_schema=False)
def receipt_review_page(
    receipt_pk: str,
    request: Request,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> Response:
    receipt = session.scalar(
        select(Receipt).where(Receipt.receipt_pk == receipt_pk, Receipt.deleted_at.is_(None))
    )
    if receipt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    raw_extraction = receipt.raw_ocr_document.get("extraction")
    raw_confidences = (
        raw_extraction.get("field_confidence") if isinstance(raw_extraction, dict) else None
    )
    low_confidence_fields: set[str] = set()
    if isinstance(raw_confidences, dict):
        for field, value in raw_confidences.items():
            try:
                if Decimal(str(value)) < Decimal("0.62"):
                    low_confidence_fields.add(str(field))
            except (InvalidOperation, ValueError):
                continue
    raw_missing_fields = (
        raw_extraction.get("missing_fields") if isinstance(raw_extraction, dict) else None
    )
    missing_fields = (
        {field for field in raw_missing_fields if isinstance(field, str)}
        if isinstance(raw_missing_fields, list)
        else set()
    )
    attention_fields = low_confidence_fields | missing_fields
    lines = session.scalars(
        select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt_pk).order_by(ReceiptItem.id)
    ).all()
    store_items = _store_items_for_lines(session, lines)
    item_ids = {line.item_id for line in lines if line.item_id is not None}
    canonical_items = {
        item.item_id: item
        for item in session.scalars(select(Item).where(Item.item_id.in_(item_ids)))
    }
    line_ids = [line.id for line in lines]
    approvals = {
        approval.receipt_item_id: approval
        for approval in session.scalars(
            select(ReceiptLineApproval)
            .where(ReceiptLineApproval.receipt_item_id.in_(line_ids))
            .order_by(ReceiptLineApproval.approval_version)
        )
    }
    source_rows = session.execute(
        select(ReceiptSource, ReceiptUpload)
        .join(ReceiptUpload, ReceiptUpload.upload_pk == ReceiptSource.upload_pk)
        .where(ReceiptSource.receipt_pk == receipt_pk)
        .order_by(ReceiptSource.id)
    ).all()
    source_views: list[dict[str, object]] = []
    for source, upload in source_rows:
        source_items = source.extracted_document.get("items")
        repeated_indexes = (
            repeated_source_line_indexes(lines, source_items, store_items)
            if source.association_kind == "PENDING"
            else ()
        )
        repeated_lines: list[dict[str, object]] = []
        if isinstance(source_items, list):
            for source_line_index in repeated_indexes:
                candidate = source_items[source_line_index]
                if isinstance(candidate, dict):
                    repeated_lines.append(
                        {
                            "index": source_line_index,
                            "description": candidate.get("description", "Unlabelled line"),
                            "store_product_id": candidate.get("store_product_id"),
                            "upc": candidate.get("upc"),
                            "source_page": candidate.get("source_page") or 1,
                            "source_line_number": candidate.get("source_line_number")
                            or source_line_index + 1,
                        }
                    )
        source_views.append(
            {
                "id": source.id,
                "kind": source.association_kind,
                "media_type": upload.media_type,
                "page_count": max(upload.page_count or 1, 1),
                "content_url": (f"/api/v1/receipts/{receipt_pk}/sources/{source.id}/content"),
                "repeated_lines": repeated_lines,
            }
        )
    candidates_by_line: dict[int, list[dict[str, object]]] = {}
    unassigned_image_candidates: list[dict[str, object]] = []
    source_ids = [source.id for source, _ in source_rows]
    if source_ids:
        candidate_rows = session.execute(
            select(MediaAssetLink, MediaAsset)
            .join(MediaAsset, MediaAsset.asset_sha256 == MediaAssetLink.asset_sha256)
            .join(ReceiptSource, ReceiptSource.id == MediaAssetLink.source_id)
            .where(
                MediaAssetLink.owner_kind == "RECEIPT_LINE_CANDIDATE",
                MediaAssetLink.source_id.in_(source_ids),
                ReceiptSource.association_kind != "REJECTED",
            )
            .order_by(MediaAssetLink.id)
        ).all()
        for candidate, _asset in candidate_rows:
            candidate_view: dict[str, object] = {
                "id": candidate.id,
                "source_id": candidate.source_id,
                "status": candidate.status,
                "reason": candidate.rejection_reason,
                "page": candidate.source_page,
                "region": candidate.source_region,
                "thumbnail_url": (
                    f"/api/v1/receipts/{receipt_pk}/image-candidates/{candidate.id}/thumbnail"
                ),
            }
            if candidate.receipt_item_id in line_ids:
                candidates_by_line.setdefault(candidate.receipt_item_id, []).append(candidate_view)
            else:
                unassigned_image_candidates.append(candidate_view)
    review_lines: list[dict[str, object]] = []
    remembered_items = {
        remembered.store_item_id: remembered
        for remembered in session.scalars(
            select(StoreItem).where(
                StoreItem.store_id == receipt.store_id,
                StoreItem.last_disposition.is_not(None),
            )
        )
        if remembered.last_disposition is not None
    }
    remembered_rules = tuple(
        RememberedItemRule(
            store_item_id=remembered.store_item_id,
            vendor=receipt.store,
            description=remembered.latest_description,
            disposition=BusinessDisposition(remembered.last_disposition),
            upc=remembered.upc,
        )
        for remembered in remembered_items.values()
        if remembered.last_disposition is not None
    )
    for line in lines:
        store_item = store_items.get(line.store_item_id) if line.store_item_id is not None else None
        canonical_item = canonical_items.get(line.item_id) if line.item_id is not None else None
        approval = approvals.get(line.id)
        primary = line.business_disposition
        subtype = line.disposition_subtype
        rule_suggestion: str | None = None
        if primary == BusinessDisposition.UNCLASSIFIED.value and store_item is not None:
            primary = store_item.last_disposition or primary
            subtype = store_item.last_disposition_subtype or "NONE"
        if (
            primary == BusinessDisposition.UNCLASSIFIED.value
            and approval is None
            and not line.is_excluded
        ):
            rule_match = find_item_rule(
                remembered_rules, receipt.store, line.description, line.upc, line.store_item_id
            )
            if rule_match is not None:
                labels = sorted({rule.disposition.value for rule in rule_match.candidates})
                upc_rule = (
                    rule_match.rule
                    if rule_match.kind is RuleMatchKind.EXACT
                    and rule_match.rule is not None
                    and line.upc is not None
                    and rule_match.rule.upc == line.upc
                    else None
                )
                if upc_rule is not None:
                    remembered_item = remembered_items[upc_rule.store_item_id]
                    primary = upc_rule.disposition.value
                    subtype = remembered_item.last_disposition_subtype or "NONE"
                prefix = (
                    "Matches a remembered item: "
                    if rule_match.kind is RuleMatchKind.EXACT
                    else "Ambiguous remembered matches: "
                )
                rule_suggestion = prefix + ", ".join(
                    label.replace("_", " ").title() for label in labels
                )
        review_lines.append(
            {
                "id": line.id,
                "description": line.description,
                "image_candidates": candidates_by_line.get(line.id, []),
                "rule_suggestion": rule_suggestion,
                "display_name": (
                    (store_item.common_name if store_item is not None else None)
                    or (canonical_item.common_name if canonical_item is not None else None)
                    or line.description
                ),
                "store_product_id": (
                    store_item.store_product_id if store_item is not None else None
                ),
                "identifier_source": (
                    store_item.identifier_source if store_item is not None else None
                ),
                "mapping_confirmed": (
                    store_item.mapping_confirmed if store_item is not None else False
                ),
                "category": line.category,
                "quantity": str(line.quantity) if line.quantity is not None else None,
                "weight_lb": str(line.weight_lb) if line.weight_lb is not None else None,
                "package_count": (
                    str(line.package_count) if line.package_count is not None else None
                ),
                "pack_size": str(line.pack_size) if line.pack_size is not None else None,
                "pack_unit": line.pack_unit,
                "remembered_pack_size": (
                    str(store_item.remembered_pack_size)
                    if store_item is not None and store_item.remembered_pack_size is not None
                    else None
                ),
                "remembered_pack_unit": (
                    store_item.remembered_pack_unit if store_item is not None else None
                ),
                "package_suggestion": (
                    line.pack_size is None
                    and store_item is not None
                    and store_item.remembered_pack_size is not None
                    and store_item.remembered_pack_unit is not None
                ),
                "has_store_item": store_item is not None,
                "store_item_id": line.store_item_id,
                "package_review_warning": (
                    line.package_count is None or line.pack_size is None or line.pack_unit is None
                ),
                "low_confidence": (
                    "items" in low_confidence_fields
                    or (line.ocr_confidence is not None and line.ocr_confidence < Decimal("0.62"))
                ),
                "upc": line.upc,
                "unit_price": str(line.unit_price) if line.unit_price is not None else None,
                "line_total": str(line.line_total),
                "is_excluded": line.is_excluded,
                "exclusion_reason": line.exclusion_reason,
                "business_disposition": primary,
                "disposition_subtype": subtype,
                "approved": approval is not None,
                "posting_status": approval.posting_status if approval is not None else None,
                "posting_kind": approval.posting_kind if approval is not None else None,
            }
        )
    return templates.TemplateResponse(
        request=request,
        name="receipt_review.html",
        context={
            "receipt": receipt,
            "lines": review_lines,
            "sources": source_views,
            "unassigned_image_candidates": unassigned_image_candidates,
            "dispositions": [item.value for item in BusinessDisposition],
            "corrections_locked": bool(approvals),
            "unit_aliases": UNIT_ALIASES,
            "attention_fields": attention_fields,
            "total_mismatch": receipt.receipt_document.get("total_mismatch") is True,
            "can_add_line": receipt.source_type == "MANUAL"
            or any(source["kind"] in {"PRIMARY", "SUPPLEMENT"} for source in source_views),
        },
    )


@router.post("/receipts/{receipt_pk}/items/{receipt_item_id}/approval")
def approve_receipt_line(
    receipt_pk: str,
    receipt_item_id: int,
    payload: ReceiptApprovalRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    line_exists = session.scalar(
        select(ReceiptItem.id).where(
            ReceiptItem.id == receipt_item_id,
            ReceiptItem.receipt_pk == receipt_pk,
        )
    )
    if line_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt item not found")
    try:
        result = approve_receipt_item(
            session,
            receipt_item_id,
            user.id,
            payload.disposition,
            payload.source_event_id,
            payload.disposition_subtype,
            payload.update_remembered_rule,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    session.commit()
    return _approval_response(session, receipt_item_id, result)


def _approval_response(
    session: Session, receipt_item_id: int, result: ApprovalResult
) -> dict[str, object]:
    routing_record = session.scalar(
        select(ReceiptRoutingRecord).where(
            ReceiptRoutingRecord.receipt_item_id == receipt_item_id,
            ReceiptRoutingRecord.destination_kind == result.approval.posting_kind,
            ReceiptRoutingRecord.approved_version == result.approval.approval_version,
        )
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


@router.post("/receipts/{receipt_pk}/items/{receipt_item_id}/reroute")
def reroute_receipt_line(
    receipt_pk: str,
    receipt_item_id: int,
    payload: ReceiptRerouteRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    line_exists = session.scalar(
        select(ReceiptItem.id).where(
            ReceiptItem.id == receipt_item_id,
            ReceiptItem.receipt_pk == receipt_pk,
        )
    )
    if line_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt item not found")
    try:
        result = reclassify_expense_routing(
            session,
            receipt_item_id,
            user.id,
            payload.disposition,
            payload.disposition_subtype,
            payload.reason,
            payload.source_event_id,
            payload.update_remembered_rule,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    session.commit()
    return _approval_response(session, receipt_item_id, result)


@router.post("/receipts/{receipt_pk}/corrections")
def correct_receipt(
    receipt_pk: str,
    payload: ReceiptCorrectionRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        result = review_receipt(
            session,
            receipt_pk,
            user.id,
            reason=payload.reason,
            source_event_id=payload.source_event_id,
            header_updates=payload.header_updates,
            item_updates=payload.item_updates,
            item_additions=[addition.model_dump() for addition in payload.item_additions],
            item_exclusions=payload.item_exclusions,
            remember_package_default_indexes=payload.remember_package_default_indexes,
        )
    except ValueError as error:
        raise domain_http_error(error, status.HTTP_400_BAD_REQUEST) from error
    except IndexError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    session.commit()
    return {
        "status": result.status.value,
        "receipt_pk": result.receipt.receipt_pk,
        "receipt_id": result.receipt.receipt_id,
        "document_version": result.receipt.receipt_document_version,
        "hold_id": result.hold.id if result.hold is not None else None,
        "idempotent": result.idempotent,
    }


@router.get("/receipt-correction-holds")
def list_receipt_correction_holds(
    _current: tuple[User, AuthSession] = Depends(admin_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> list[dict[str, object]]:
    holds = session.scalars(
        select(ReceiptCorrectionHold)
        .where(ReceiptCorrectionHold.status == "PENDING")
        .order_by(ReceiptCorrectionHold.id)
    ).all()
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


@router.post("/receipt-correction-holds/{hold_id}/resolve")
def resolve_receipt_correction_hold(
    hold_id: int,
    payload: CorrectionHoldResolutionRequest,
    current: tuple[User, AuthSession] = Depends(admin_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        hold = resolve_correction_hold(
            session,
            hold_id,
            user.id,
            payload.action,
            payload.reason,
            payload.new_transaction_number,
        )
    except ValueError as error:
        raise domain_http_error(error, status.HTTP_400_BAD_REQUEST) from error
    session.commit()
    return {"id": hold.id, "status": hold.status, "action": hold.resolution_action}


@router.post("/receipts/upload")
def upload_receipt(
    upload: BoundedUpload = Depends(authorized_upload_body),  # noqa: B008
    service: ReceiptUploadService = Depends(get_receipt_upload_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    try:
        result = service.upload(session, upload.source, upload.media_type, upload.uploaded_by)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    if result.status is UploadStatus.SCAN_PENDING:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=result.status)
    if result.status is UploadStatus.MALWARE_REJECTED:
        session.commit()  # keep the rejection audit row
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.status)
    session.commit()
    if result.upload_pk is not None and result.status is UploadStatus.QUEUED:
        service.index_committed_upload(session, result.upload_pk)
    if result.status in {UploadStatus.QUEUED, UploadStatus.EXACT_DUPLICATE}:
        _request_outbox_dispatch()
    return {
        "upload_pk": result.upload_pk,
        "source_sha256": result.source_sha256,
        "status": result.status.value,
        "file_key": result.file_key,
        "matched_source_sha256": result.matched_source_sha256,
        "idempotent": result.idempotent,
    }


@router.post("/receipt-uploads/{upload_pk}/resolve-near-match")
def resolve_near_match(
    upload_pk: str,
    payload: NearMatchResolutionRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    service: ReceiptUploadService = Depends(get_receipt_upload_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        result = service.resolve_possible_duplicate(
            session, upload_pk, user.id, payload.process_as_new
        )
    except ValueError as error:
        raise domain_http_error(error, status.HTTP_400_BAD_REQUEST) from error
    session.commit()
    if result.status is UploadStatus.QUEUED:
        if result.upload_pk is not None:
            service.index_committed_upload(session, result.upload_pk)
        _request_outbox_dispatch()
    return {
        "upload_pk": result.upload_pk,
        "status": result.status.value,
        "idempotent": result.idempotent,
    }


def _request_outbox_dispatch() -> None:
    try:
        dispatch_pending_receipt_uploads.delay()
    except Exception:
        # The committed outbox row remains pending for the periodic publisher.
        logger.warning("Receipt outbox dispatch request failed", exc_info=True)
        return


def _receipt_response(
    receipt: Receipt,
    items: Sequence[ReceiptItem],
    store_items: dict[str, StoreItem],
    sources: Sequence[ReceiptSource] = (),
) -> dict[str, object]:
    return {
        "receipt_pk": receipt.receipt_pk,
        "receipt_id": receipt.receipt_id,
        "source_type": receipt.source_type,
        "store_id": receipt.store_id,
        "store": receipt.store,
        "purchase_date": receipt.receipt_date.isoformat(),
        "purchase_time": receipt.receipt_time.isoformat(),
        "transaction_number": receipt.transaction_number,
        "subtotal": str(receipt.subtotal) if receipt.subtotal is not None else None,
        "tax": str(receipt.tax) if receipt.tax is not None else None,
        "total": str(receipt.total),
        "payment_method": receipt.payment_method,
        "sources": [
            {
                "source_id": source.id,
                "source_sha256": source.source_sha256,
                "association_kind": source.association_kind,
                "confirmed_repeated_line_indexes": (source.confirmed_repeated_line_indexes or []),
            }
            for source in sources
        ],
        "items": [
            _item_response(
                item,
                store_items.get(item.store_item_id) if item.store_item_id is not None else None,
                receipt.source_type,
            )
            for item in items
        ],
    }


def _item_response(
    item: ReceiptItem,
    store_item: StoreItem | None = None,
    receipt_source_type: str = "OCR",
) -> dict[str, object]:
    return {
        "description": item.description,
        "upc": item.upc,
        "quantity": str(item.quantity) if item.quantity is not None else None,
        "weight_lb": str(item.weight_lb) if item.weight_lb is not None else None,
        "package_count": str(item.package_count) if item.package_count is not None else None,
        "pack_size": str(item.pack_size) if item.pack_size is not None else None,
        "pack_unit": item.pack_unit,
        "unit_price": str(item.unit_price) if item.unit_price is not None else None,
        "line_total": str(item.line_total),
        "category": item.category,
        "business_disposition": item.business_disposition,
        "disposition_subtype": item.disposition_subtype,
        "source_id": item.source_id,
        "source_page": item.source_page,
        "source_line_number": item.source_line_number,
        "is_excluded": item.is_excluded,
        "exclusion_reason": item.exclusion_reason,
        "store_product_id": store_item.store_product_id if store_item is not None else None,
        "identifier_source": (
            "MANUAL"
            if store_item is not None and store_item.identifier_source == "MANUAL"
            else "USER_ENTERED"
            if store_item is not None and receipt_source_type == "MANUAL"
            else "OCR"
            if store_item is not None
            else None
        ),
        "common_name": store_item.common_name if store_item is not None else None,
    }


def _store_items_for_lines(session: Session, items: Sequence[ReceiptItem]) -> dict[str, StoreItem]:
    store_item_ids = {item.store_item_id for item in items if item.store_item_id is not None}
    if not store_item_ids:
        return {}
    return {
        store_item.store_item_id: store_item
        for store_item in session.scalars(
            select(StoreItem).where(StoreItem.store_item_id.in_(store_item_ids))
        )
    }


def _manual_item_responses(
    items: Sequence[ReceiptItem], store_items: dict[str, StoreItem]
) -> list[dict[str, str]]:
    responses: list[dict[str, str]] = []
    for item in items:
        if item.store_item_id is None:
            continue
        store_item = store_items.get(item.store_item_id)
        if store_item is None:
            continue
        responses.append(
            {
                "description": item.description,
                "store_product_id": store_item.store_product_id,
                "identifier_source": (
                    "MANUAL" if store_item.identifier_source == "MANUAL" else "USER_ENTERED"
                ),
            }
        )
    return responses
