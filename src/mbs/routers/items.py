from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.responses import Response

from mbs.db import get_session
from mbs.errors import NotFoundError
from mbs.item_images import (
    ImageGalleryConflictError,
    ImageOwnerKind,
    ItemImageGalleryService,
    get_item_image_gallery_service,
)
from mbs.items import suggest_item_mappings
from mbs.media_assets import MediaAssetService
from mbs.models import (
    AuthSession,
    User,
)
from mbs.routers.dependencies import (
    current_session_user,
    get_media_asset_service,
    manager_csrf_session,
    manager_session,
)
from mbs.services.item_commands import ItemCommandService, get_item_command_service
from mbs.services.item_reads import ItemReadService, get_item_read_service

router = APIRouter(prefix="/api/v1", tags=["items"])
templates = Jinja2Templates(directory=str(Path(__file__).parents[1] / "templates"))


class ItemUpdateRequest(BaseModel):
    common_name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


class StoreItemUpdateRequest(BaseModel):
    common_name: str | None = Field(default=None, max_length=255)


class ItemMapRequest(BaseModel):
    store_item_id: str = Field(min_length=1, max_length=36)
    item_id: str = Field(min_length=1, max_length=36)
    store_common_name: str | None = Field(default=None, max_length=255)
    effective_from: date
    reason: str = Field(min_length=1, max_length=1000)
    source_event_id: str = Field(min_length=1, max_length=255)


class ItemSplitRequest(BaseModel):
    store_item_id: str = Field(min_length=1, max_length=36)
    common_name: str | None = Field(default=None, max_length=255)
    effective_from: date
    reason: str = Field(min_length=1, max_length=1000)
    source_event_id: str = Field(min_length=1, max_length=255)


class ItemMergeRequest(BaseModel):
    source_item_id: str = Field(min_length=1, max_length=36)
    target_item_id: str = Field(min_length=1, max_length=36)
    effective_from: date
    reason: str = Field(min_length=1, max_length=1000)
    source_event_id: str = Field(min_length=1, max_length=255)


class ReviewedIdentifierRequest(BaseModel):
    store_product_id: str = Field(min_length=1, max_length=255)
    source_event_id: str = Field(min_length=1, max_length=255)


class ImagePrimaryRequest(BaseModel):
    replace_primary: bool = False


class ImageOrderRequest(BaseModel):
    link_ids: list[int] = Field(min_length=1, max_length=100)


ImageVariant = Literal["thumbnail", "display", "original"]


@router.get("/image-owners/{owner_kind}/{owner_id}/images")
def list_owner_images(
    owner_kind: ImageOwnerKind,
    owner_id: str,
    gallery: ItemImageGalleryService = Depends(get_item_image_gallery_service),  # noqa: B008
    _current: tuple[User, AuthSession] = Depends(current_session_user),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    try:
        return gallery.list_images(session, owner_kind, owner_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/image-owners/{owner_kind}/{owner_id}/images")
async def upload_owner_image(
    owner_kind: ImageOwnerKind,
    owner_id: str,
    request: Request,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    service: MediaAssetService = Depends(get_media_asset_service),  # noqa: B008
    gallery: ItemImageGalleryService = Depends(get_item_image_gallery_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        gallery.require_owner(session, owner_kind, owner_id, lock=True)
        max_bytes = gallery.max_upload_bytes(session)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=503, detail="Image size setting is invalid") from error
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(
                    status_code=413, detail="Image exceeds the configured size limit"
                )
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from error
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > max_bytes:
            raise HTTPException(status_code=413, detail="Image exceeds the configured size limit")
        body.extend(chunk)
    media_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0].strip()
    try:
        return gallery.upload_image(
            session, service, owner_kind, owner_id, bytes(body), media_type, user.id
        )
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ImageGalleryConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=415, detail=str(error)) from error


@router.get("/image-owners/{owner_kind}/{owner_id}/images/{link_id}/{variant}")
def read_owner_image(
    owner_kind: ImageOwnerKind,
    owner_id: str,
    link_id: int,
    variant: ImageVariant,
    _current: tuple[User, AuthSession] = Depends(current_session_user),  # noqa: B008
    service: MediaAssetService = Depends(get_media_asset_service),  # noqa: B008
    gallery: ItemImageGalleryService = Depends(get_item_image_gallery_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> Response:
    try:
        content, content_type = gallery.read_image(
            session, service, owner_kind, owner_id, link_id, variant
        )
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(
        content,
        media_type=content_type,
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "same-origin",
        },
    )


@router.post("/image-owners/{owner_kind}/{owner_id}/images/{link_id}/primary")
def set_owner_image_primary(
    owner_kind: ImageOwnerKind,
    owner_id: str,
    link_id: int,
    payload: ImagePrimaryRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    gallery: ItemImageGalleryService = Depends(get_item_image_gallery_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        return gallery.set_primary(
            session, owner_kind, owner_id, link_id, user.id, payload.replace_primary
        )
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ImageGalleryConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.put("/image-owners/{owner_kind}/{owner_id}/images/order")
def reorder_owner_images(
    owner_kind: ImageOwnerKind,
    owner_id: str,
    payload: ImageOrderRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    gallery: ItemImageGalleryService = Depends(get_item_image_gallery_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        return gallery.reorder(session, owner_kind, owner_id, payload.link_ids, user.id)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ImageGalleryConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.delete("/image-owners/{owner_kind}/{owner_id}/images/{link_id}")
def detach_owner_image(
    owner_kind: ImageOwnerKind,
    owner_id: str,
    link_id: int,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    gallery: ItemImageGalleryService = Depends(get_item_image_gallery_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        return gallery.detach(session, owner_kind, owner_id, link_id, user.id)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/items/page", include_in_schema=False)
def item_mapping_page(
    request: Request,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    service: ItemReadService = Depends(get_item_read_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="item_mapping.html",
        context=service.mapping_context(session),
    )


@router.get("/items")
def list_items(
    query: str | None = None,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    service: ItemReadService = Depends(get_item_read_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> list[dict[str, object]]:
    return service.list_items(session, query)


@router.post("/receipt-items/{receipt_item_id}/store-product-id")
def review_store_product_identifier(
    receipt_item_id: int,
    payload: ReviewedIdentifierRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    service: ItemCommandService = Depends(get_item_command_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        return service.review_identifier(
            session,
            receipt_item_id,
            payload.store_product_id,
            user.id,
            payload.source_event_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/items/mapping-suggestions")
def get_mapping_suggestions(
    store_item_id: str,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> list[dict[str, object]]:
    try:
        return suggest_item_mappings(session, store_item_id)
    except KeyError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/store-items")
def list_store_items(
    query: str | None = None,
    unmapped_only: bool = False,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    service: ItemReadService = Depends(get_item_read_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> list[dict[str, object]]:
    return service.list_store_items(session, query, unmapped_only)


@router.get("/items/{item_id}")
def get_item(
    item_id: str,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    service: ItemReadService = Depends(get_item_read_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    try:
        return service.get_item(session, item_id)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.put("/items/{item_id}")
def update_item(
    item_id: str,
    payload: ItemUpdateRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    service: ItemCommandService = Depends(get_item_command_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    if not payload.model_fields_set:
        raise HTTPException(status_code=422, detail="At least one item field must be provided")
    try:
        return service.update_item(
            session,
            item_id,
            payload.common_name,
            "common_name" in payload.model_fields_set,
            payload.is_active,
            user.id,
        )
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.put("/store-items/{store_item_id}")
def update_store_item(
    store_item_id: str,
    payload: StoreItemUpdateRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    service: ItemCommandService = Depends(get_item_command_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    if "common_name" not in payload.model_fields_set:
        raise HTTPException(status_code=422, detail="common_name must be provided")
    try:
        return service.update_store_item(session, store_item_id, payload.common_name, user.id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/items/map")
def map_store_item(
    payload: ItemMapRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    service: ItemCommandService = Depends(get_item_command_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        return service.map_item(
            session,
            payload.store_item_id,
            payload.item_id,
            user.id,
            payload.effective_from,
            payload.reason,
            payload.source_event_id,
            payload.store_common_name,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/items/split")
def split_store_item(
    payload: ItemSplitRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    service: ItemCommandService = Depends(get_item_command_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        return service.split_item(
            session,
            payload.store_item_id,
            payload.common_name,
            user.id,
            payload.effective_from,
            payload.reason,
            payload.source_event_id,
        )
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/items/merge")
def merge_items(
    payload: ItemMergeRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    service: ItemCommandService = Depends(get_item_command_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        return service.merge_items(
            session,
            payload.source_item_id,
            payload.target_item_id,
            user.id,
            payload.reason,
            payload.source_event_id,
            payload.effective_from,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
