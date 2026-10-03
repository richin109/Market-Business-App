from __future__ import annotations

import logging
from datetime import date, time
from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.responses import Response

from mbs.db import get_session
from mbs.errors import ConflictError, NotFoundError, UnavailableError, UnsupportedMediaError
from mbs.models import (
    AuthSession,
    User,
)
from mbs.receipts.approval import (
    DispositionSubtype,
    validate_disposition_pair,
)
from mbs.receipts.corrections import (
    HoldResolutionAction,
)
from mbs.receipts.dispatch import request_outbox_dispatch as _request_outbox_dispatch
from mbs.receipts.ocr import BusinessDisposition
from mbs.receipts.sources import (
    SourceDecision,
)
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
from mbs.services import receipt_commands, receipt_images
from mbs.services.receipt_reads import (
    list_receipt_responses,
    manual_receipt_stores,
    receipt_items_response,
    receipt_response,
)
from mbs.services.receipt_review import receipt_review_context
from mbs.services.receipt_upload_commands import (
    ReceiptUploadBatch,
    resolve_near_match_and_complete,
    upload_and_complete,
)

router = APIRouter(prefix="/api/v1", tags=["receipts"])
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory=str(Path(__file__).parents[1] / "templates"))
MAX_BATCH_FILES = 50
MAX_BATCH_BYTES = 50_000_000
MAX_BATCH_REQUEST_BYTES = MAX_BATCH_BYTES + 1_000_000


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
    return templates.TemplateResponse(
        request=request,
        name="manual_receipt.html",
        context={"stores": manual_receipt_stores(session)},
    )


@router.get("/receipts/upload/page", include_in_schema=False)
def receipt_upload_page(
    request: Request,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
) -> Response:
    return templates.TemplateResponse(request=request, name="receipt_upload.html", context={})


@router.post("/receipts/upload-batch")
async def upload_receipt_batch(
    request: Request,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    service: ReceiptUploadService = Depends(get_receipt_upload_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    content_length = request.headers.get("content-length")
    if content_length is None:
        raise HTTPException(status_code=411, detail="Content-Length is required for batch upload")
    try:
        declared_length = int(content_length)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Content-Length"
        ) from error
    if declared_length > MAX_BATCH_REQUEST_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Batch request exceeds its limit"
        )

    form = await request.form(max_files=MAX_BATCH_FILES, max_fields=0, max_part_size=1024)
    files = [
        (key, value) for key, value in form.multi_items() if isinstance(value, StarletteUploadFile)
    ]
    if len(files) != len(form.multi_items()) or any(key != "files" for key, _ in files):
        await form.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Batch upload accepts only repeated files fields",
        )
    if not files:
        await form.close()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files selected")

    batch = ReceiptUploadBatch(service, user.id, MAX_BATCH_BYTES)
    try:
        for index, (_, file) in enumerate(files, start=1):
            filename = Path((file.filename or f"file-{index}").replace("\\", "/")).name
            if file.size is not None and file.size > service.max_file_bytes:
                batch.reject_file(filename, "TOO_LARGE", "File exceeds the per-file size limit")
                continue
            source = await file.read(service.max_file_bytes + 1)
            batch.add_file(session, filename, source, file.content_type or "")
        batch.commit(session)
    finally:
        await form.close()

    return batch.finish(session, _request_outbox_dispatch)


@router.post("/receipts/manual", status_code=status.HTTP_201_CREATED)
def enter_manual_receipt(
    payload: ManualReceiptRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        return receipt_commands.enter_manual_receipt(session, user, payload.model_dump())
    except ValueError as error:
        raise domain_http_error(error, 422) from error


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
    return list_receipt_responses(session, store, store_id, date_from, date_to, page, page_size)


@router.get("/receipts/{receipt_pk}")
def get_receipt(
    receipt_pk: str,
    _current: tuple[User, AuthSession] = Depends(current_session_user),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    try:
        return receipt_response(session, receipt_pk)
    except NotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.delete("/receipts/{receipt_pk}")
def delete_receipt(
    receipt_pk: str,
    payload: ReceiptDeleteRequest,
    current: tuple[User, AuthSession] = Depends(admin_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        return receipt_commands.delete_receipt(session, user, receipt_pk, payload.model_dump())
    except ValueError as error:
        raise domain_http_error(error, 409) from error


@router.get("/receipts/{receipt_pk}/sources/{source_id}/content")
def get_receipt_source_content(
    receipt_pk: str,
    source_id: int,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    service: ReceiptUploadService = Depends(get_receipt_upload_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> Response:
    try:
        content, media_type = receipt_images.get_receipt_source_content(
            session, service, receipt_pk, source_id
        )
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except UnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except UnsupportedMediaError as error:
        raise HTTPException(status_code=415, detail=str(error)) from error
    return Response(
        content,
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "same-origin",
            "Content-Disposition": "inline; filename=receipt-source",
        },
    )


@router.get("/receipts/{receipt_pk}/items")
def get_receipt_items(
    receipt_pk: str,
    _current: tuple[User, AuthSession] = Depends(current_session_user),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> list[dict[str, object]]:
    try:
        return receipt_items_response(session, receipt_pk)
    except NotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


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
        return receipt_commands.decide_receipt_source_route(
            session, user, receipt_pk, source_id, payload.model_dump()
        )
    except ValueError as error:
        raise domain_http_error(error, 409) from error


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
    try:
        content, media_type = receipt_images.get_receipt_image_candidate_thumbnail(
            session, service, receipt_pk, candidate_id
        )
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except UnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except UnsupportedMediaError as error:
        raise HTTPException(status_code=415, detail=str(error)) from error
    return Response(
        content,
        media_type=media_type,
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
    try:
        return receipt_images.decide_receipt_image_candidate(
            session, user, receipt_pk, candidate_id, payload.model_dump()
        )
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/receipts/{receipt_pk}/review", include_in_schema=False)
def receipt_review_page(
    receipt_pk: str,
    request: Request,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> Response:
    try:
        context = receipt_review_context(session, receipt_pk)
    except NotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return templates.TemplateResponse(request=request, name="receipt_review.html", context=context)


@router.post("/receipts/{receipt_pk}/items/{receipt_item_id}/approval")
def approve_receipt_line(
    receipt_pk: str,
    receipt_item_id: int,
    payload: ReceiptApprovalRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        return receipt_commands.approve_receipt_line(
            session, user, receipt_pk, receipt_item_id, payload.model_dump()
        )
    except ValueError as error:
        raise domain_http_error(error, 409) from error


@router.post("/receipts/{receipt_pk}/items/{receipt_item_id}/reroute")
def reroute_receipt_line(
    receipt_pk: str,
    receipt_item_id: int,
    payload: ReceiptRerouteRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        return receipt_commands.reroute_receipt_line(
            session, user, receipt_pk, receipt_item_id, payload.model_dump()
        )
    except ValueError as error:
        raise domain_http_error(error, 409) from error


@router.post("/receipts/{receipt_pk}/corrections")
def correct_receipt(
    receipt_pk: str,
    payload: ReceiptCorrectionRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        return receipt_commands.correct_receipt(session, user, receipt_pk, payload.model_dump())
    except ValueError as error:
        raise domain_http_error(error, 400) from error
    except IndexError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/receipt-correction-holds")
def list_receipt_correction_holds(
    _current: tuple[User, AuthSession] = Depends(admin_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> list[dict[str, object]]:
    return receipt_commands.list_receipt_correction_holds(session)


@router.post("/receipt-correction-holds/{hold_id}/resolve")
def resolve_receipt_correction_hold(
    hold_id: int,
    payload: CorrectionHoldResolutionRequest,
    current: tuple[User, AuthSession] = Depends(admin_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        return receipt_commands.resolve_receipt_correction_hold(
            session, user, hold_id, payload.model_dump()
        )
    except ValueError as error:
        raise domain_http_error(error, 400) from error


@router.post("/receipts/upload")
def upload_receipt(
    upload: BoundedUpload = Depends(authorized_upload_body),  # noqa: B008
    service: ReceiptUploadService = Depends(get_receipt_upload_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    try:
        result = upload_and_complete(
            session,
            service,
            upload.source,
            upload.media_type,
            upload.uploaded_by,
            _request_outbox_dispatch,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    if result.status is UploadStatus.SCAN_PENDING:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=result.status)
    if result.status is UploadStatus.MALWARE_REJECTED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.status)
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
        result = resolve_near_match_and_complete(
            session,
            service,
            upload_pk,
            user.id,
            payload.process_as_new,
            _request_outbox_dispatch,
        )
    except ValueError as error:
        raise domain_http_error(error, status.HTTP_400_BAD_REQUEST) from error
    return {
        "upload_pk": result.upload_pk,
        "status": result.status.value,
        "idempotent": result.idempotent,
    }
