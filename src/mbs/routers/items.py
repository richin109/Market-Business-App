from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import Response

from mbs.db import get_session
from mbs.items import (
    assign_reviewed_store_product_identifier,
    confirm_store_item_mapping,
    merge_canonical_items,
    set_item_active,
    set_item_common_name,
    set_store_item_common_name,
    suggest_item_mappings,
)
from mbs.media_assets import MediaAssetService
from mbs.models import (
    AuditLog,
    AuthSession,
    Item,
    MediaAsset,
    MediaAssetLink,
    Receipt,
    ReceiptItem,
    Store,
    StoreItem,
    User,
)
from mbs.routers.dependencies import (
    current_session_user,
    get_media_asset_service,
    manager_csrf_session,
    manager_session,
)
from mbs.routers.query import LIKE_ESCAPE, contains_pattern
from mbs.settings import read_setting

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


ImageOwnerKind = Literal["ITEM", "STORE_ITEM"]
ImageVariant = Literal["thumbnail", "display", "original"]


def _lock_image_owner(
    session: Session, owner_kind: ImageOwnerKind, owner_id: str, *, lock: bool = True
) -> Item | StoreItem:
    if owner_kind == "ITEM":
        item_query = select(Item).where(Item.item_id == owner_id)
        owner = session.scalar(item_query.with_for_update() if lock else item_query)
        if owner is None or not owner.is_active:
            raise HTTPException(status_code=404, detail="Image owner not found")
        return owner
    store_item_query = select(StoreItem).where(StoreItem.store_item_id == owner_id)
    store_item = session.scalar(store_item_query.with_for_update() if lock else store_item_query)
    if store_item is None:
        raise HTTPException(status_code=404, detail="Image owner not found")
    return store_item


def _image_owner_primary(
    session: Session, owner_kind: ImageOwnerKind, owner_id: str, *, lock: bool = True
) -> MediaAssetLink | None:
    query = select(MediaAssetLink).where(
        MediaAssetLink.owner_kind == owner_kind,
        MediaAssetLink.owner_id == owner_id,
        MediaAssetLink.status == "CONFIRMED",
        MediaAssetLink.is_primary.is_(True),
        MediaAssetLink.detached_at.is_(None),
    )
    return session.scalar(query.with_for_update() if lock else query)


@router.get("/image-owners/{owner_kind}/{owner_id}/images")
def list_owner_images(
    owner_kind: ImageOwnerKind,
    owner_id: str,
    _current: tuple[User, AuthSession] = Depends(current_session_user),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    owner = _lock_image_owner(session, owner_kind, owner_id, lock=False)
    links = session.execute(
        select(MediaAssetLink, MediaAsset)
        .join(MediaAsset, MediaAsset.asset_sha256 == MediaAssetLink.asset_sha256)
        .where(
            MediaAssetLink.owner_kind == owner_kind,
            MediaAssetLink.owner_id == owner_id,
            MediaAssetLink.status == "CONFIRMED",
            MediaAssetLink.detached_at.is_(None),
        )
        .order_by(MediaAssetLink.sort_order, MediaAssetLink.id)
    ).all()
    primary_link = next(
        (link for link, asset in links if link.is_primary and asset.ingest_status == "READY"),
        None,
    )
    fallback_kind: str | None = None
    fallback_owner_id: str | None = None
    if primary_link is None and isinstance(owner, StoreItem) and owner.mapping_confirmed:
        fallback_kind, fallback_owner_id = "ITEM", owner.item_id
        primary_link = _image_owner_primary(session, "ITEM", owner.item_id, lock=False)
    if primary_link is None:
        fallback_kind = None
        fallback_owner_id = None
    return {
        "owner_kind": owner_kind,
        "owner_id": owner_id,
        "resolved_primary": (
            {
                "owner_kind": fallback_kind or owner_kind,
                "owner_id": fallback_owner_id or owner_id,
                "link_id": primary_link.id,
                "thumbnail_url": (
                    f"/api/v1/image-owners/{fallback_kind or owner_kind}/"
                    f"{fallback_owner_id or owner_id}/images/{primary_link.id}/thumbnail"
                ),
            }
            if primary_link is not None
            else None
        ),
        "placeholder": primary_link is None,
        "images": [
            {
                "link_id": link.id,
                "asset_sha256": asset.asset_sha256,
                "is_primary": link.is_primary,
                "sort_order": link.sort_order,
                "source_id": link.source_id,
                "source_page": link.source_page,
                "ingest_status": asset.ingest_status,
                "thumbnail_url": (
                    f"/api/v1/image-owners/{owner_kind}/{owner_id}/images/{link.id}/thumbnail"
                ),
                "display_url": (
                    f"/api/v1/image-owners/{owner_kind}/{owner_id}/images/{link.id}/display"
                ),
            }
            for link, asset in links
            if asset.ingest_status == "READY"
        ],
    }


@router.post("/image-owners/{owner_kind}/{owner_id}/images")
async def upload_owner_image(
    owner_kind: ImageOwnerKind,
    owner_id: str,
    request: Request,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    service: MediaAssetService = Depends(get_media_asset_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    _lock_image_owner(session, owner_kind, owner_id)
    try:
        max_bytes = int(read_setting(session, "image_max_bytes") or "0")
    except ValueError as error:
        raise HTTPException(status_code=503, detail="Image size setting is invalid") from error
    if max_bytes <= 0:
        raise HTTPException(status_code=503, detail="Image size setting is invalid")
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
        asset = service.stage(session, bytes(body), media_type, user.id)
        service.promote(session, asset.asset_sha256)
    except ValueError as error:
        raise HTTPException(status_code=415, detail=str(error)) from error
    duplicate = session.scalar(
        select(MediaAssetLink).where(
            MediaAssetLink.owner_kind == owner_kind,
            MediaAssetLink.owner_id == owner_id,
            MediaAssetLink.asset_sha256 == asset.asset_sha256,
            MediaAssetLink.status == "CONFIRMED",
            MediaAssetLink.detached_at.is_(None),
        )
    )
    if duplicate is not None:
        session.commit()
        return {
            "link_id": duplicate.id,
            "asset_sha256": asset.asset_sha256,
            "idempotent": True,
            "replace_prompt_required": False,
            "is_primary": duplicate.is_primary,
        }
    primary = _image_owner_primary(session, owner_kind, owner_id)
    link = MediaAssetLink(
        asset_sha256=asset.asset_sha256,
        owner_kind=owner_kind,
        owner_id=owner_id,
        status="CONFIRMED",
        is_primary=primary is None,
        sort_order=(
            (
                session.scalar(
                    select(func.max(MediaAssetLink.sort_order)).where(
                        MediaAssetLink.owner_kind == owner_kind,
                        MediaAssetLink.owner_id == owner_id,
                        MediaAssetLink.status == "CONFIRMED",
                        MediaAssetLink.detached_at.is_(None),
                    )
                )
                or -1
            )
            + 1
        ),
        created_by=user.id,
    )
    try:
        with session.begin_nested():
            session.add(link)
            session.add(
                AuditLog(
                    event_type="ITEM_IMAGE_UPLOADED",
                    actor=str(user.id),
                    entity_type=owner_kind,
                    entity_id=owner_id,
                    details=f"asset_sha256={asset.asset_sha256}; is_primary={primary is None}",
                )
            )
            session.flush()
    except IntegrityError as error:
        concurrent_duplicate = session.scalar(
            select(MediaAssetLink).where(
                MediaAssetLink.owner_kind == owner_kind,
                MediaAssetLink.owner_id == owner_id,
                MediaAssetLink.asset_sha256 == asset.asset_sha256,
                MediaAssetLink.status == "CONFIRMED",
                MediaAssetLink.detached_at.is_(None),
            )
        )
        if concurrent_duplicate is not None:
            session.commit()
            return {
                "link_id": concurrent_duplicate.id,
                "asset_sha256": asset.asset_sha256,
                "idempotent": True,
                "replace_prompt_required": False,
                "is_primary": concurrent_duplicate.is_primary,
            }
        raise HTTPException(
            status_code=409, detail="Image gallery changed; retry upload"
        ) from error
    session.commit()
    return {
        "link_id": link.id,
        "asset_sha256": asset.asset_sha256,
        "idempotent": False,
        "replace_prompt_required": primary is not None,
        "is_primary": link.is_primary,
    }


@router.get("/image-owners/{owner_kind}/{owner_id}/images/{link_id}/{variant}")
def read_owner_image(
    owner_kind: ImageOwnerKind,
    owner_id: str,
    link_id: int,
    variant: ImageVariant,
    _current: tuple[User, AuthSession] = Depends(current_session_user),  # noqa: B008
    service: MediaAssetService = Depends(get_media_asset_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> Response:
    row = session.execute(
        select(MediaAssetLink, MediaAsset)
        .join(MediaAsset, MediaAsset.asset_sha256 == MediaAssetLink.asset_sha256)
        .where(
            MediaAssetLink.id == link_id,
            MediaAssetLink.owner_kind == owner_kind,
            MediaAssetLink.owner_id == owner_id,
            MediaAssetLink.status == "CONFIRMED",
            MediaAssetLink.detached_at.is_(None),
            MediaAsset.ingest_status == "READY",
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Image not found")
    _, asset = row
    file_key, content_type = {
        "thumbnail": (asset.thumbnail_file_key, asset.thumbnail_media_type),
        "display": (asset.display_file_key, asset.display_media_type),
        "original": (asset.original_file_key, asset.original_media_type),
    }[variant]
    try:
        content = service.read_protected_file(file_key)
    except (FileNotFoundError, OSError, ValueError) as error:
        raise HTTPException(status_code=404, detail="Protected image unavailable") from error
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
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    _lock_image_owner(session, owner_kind, owner_id)
    link = session.scalar(
        select(MediaAssetLink)
        .where(
            MediaAssetLink.id == link_id,
            MediaAssetLink.owner_kind == owner_kind,
            MediaAssetLink.owner_id == owner_id,
            MediaAssetLink.status == "CONFIRMED",
            MediaAssetLink.detached_at.is_(None),
        )
        .with_for_update()
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Image not found")
    primary = _image_owner_primary(session, owner_kind, owner_id)
    if primary is not None and primary.id != link.id and not payload.replace_primary:
        return {"link_id": link.id, "replace_prompt_required": True}
    try:
        with session.begin_nested():
            if primary is not None and primary.id != link.id:
                primary.is_primary = False
            link.is_primary = True
            session.add(
                AuditLog(
                    event_type="ITEM_IMAGE_PRIMARY_CHANGED",
                    actor=str(user.id),
                    entity_type=owner_kind,
                    entity_id=owner_id,
                    details=(
                        f"link_id={link.id}; replaced_link_id={primary.id if primary else None}"
                    ),
                )
            )
            session.flush()
    except IntegrityError as error:
        raise HTTPException(
            status_code=409, detail="Primary image changed; refresh the gallery"
        ) from error
    session.commit()
    return {
        "link_id": link.id,
        "is_primary": True,
        "idempotent": primary is not None and primary.id == link.id,
    }


@router.put("/image-owners/{owner_kind}/{owner_id}/images/order")
def reorder_owner_images(
    owner_kind: ImageOwnerKind,
    owner_id: str,
    payload: ImageOrderRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    _lock_image_owner(session, owner_kind, owner_id)
    links = session.scalars(
        select(MediaAssetLink)
        .where(
            MediaAssetLink.owner_kind == owner_kind,
            MediaAssetLink.owner_id == owner_id,
            MediaAssetLink.status == "CONFIRMED",
            MediaAssetLink.detached_at.is_(None),
        )
        .order_by(MediaAssetLink.id)
        .with_for_update()
    ).all()
    by_id = {link.id: link for link in links}
    if len(payload.link_ids) != len(set(payload.link_ids)) or set(payload.link_ids) != set(by_id):
        raise HTTPException(
            status_code=409,
            detail="Image order must include every active gallery image once",
        )
    for index, link_id in enumerate(payload.link_ids):
        by_id[link_id].sort_order = index
    session.add(
        AuditLog(
            event_type="ITEM_IMAGE_GALLERY_REORDERED",
            actor=str(user.id),
            entity_type=owner_kind,
            entity_id=owner_id,
            details=f"ordered_link_ids={payload.link_ids}",
        )
    )
    session.commit()
    return {"owner_kind": owner_kind, "owner_id": owner_id, "link_ids": payload.link_ids}


@router.delete("/image-owners/{owner_kind}/{owner_id}/images/{link_id}")
def detach_owner_image(
    owner_kind: ImageOwnerKind,
    owner_id: str,
    link_id: int,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    _lock_image_owner(session, owner_kind, owner_id)
    link = session.scalar(
        select(MediaAssetLink)
        .where(
            MediaAssetLink.id == link_id,
            MediaAssetLink.owner_kind == owner_kind,
            MediaAssetLink.owner_id == owner_id,
            MediaAssetLink.status == "CONFIRMED",
            MediaAssetLink.detached_at.is_(None),
        )
        .with_for_update()
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Image not found")
    was_primary = link.is_primary
    link.is_primary = False
    link.detached_at = datetime.now(UTC)
    next_primary = None
    if was_primary:
        next_primary = session.scalar(
            select(MediaAssetLink)
            .where(
                MediaAssetLink.owner_kind == owner_kind,
                MediaAssetLink.owner_id == owner_id,
                MediaAssetLink.status == "CONFIRMED",
                MediaAssetLink.detached_at.is_(None),
                MediaAssetLink.id != link_id,
            )
            .order_by(MediaAssetLink.sort_order, MediaAssetLink.id)
            .with_for_update()
        )
        if next_primary is not None:
            next_primary.is_primary = True
    session.add(
        AuditLog(
            event_type="ITEM_IMAGE_DETACHED",
            actor=str(user.id),
            entity_type=owner_kind,
            entity_id=owner_id,
            details=(
                f"link_id={link.id}; promoted_link_id={next_primary.id if next_primary else None}"
            ),
        )
    )
    session.commit()
    return {
        "link_id": link.id,
        "detached": True,
        "promoted_link_id": next_primary.id if next_primary else None,
    }


@router.get("/items/page", include_in_schema=False)
def item_mapping_page(
    request: Request,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> Response:
    rows = session.execute(
        select(StoreItem, Item, Store, func.max(Receipt.receipt_date).label("last_purchase_date"))
        .join(Item, Item.item_id == StoreItem.item_id)
        .join(Store, Store.store_id == StoreItem.store_id)
        .outerjoin(ReceiptItem, ReceiptItem.store_item_id == StoreItem.store_item_id)
        .outerjoin(
            Receipt,
            and_(Receipt.receipt_pk == ReceiptItem.receipt_pk, Receipt.deleted_at.is_(None)),
        )
        .group_by(StoreItem.store_item_id, Item.item_id, Store.store_id)
        .order_by(Store.display_name, StoreItem.latest_description, StoreItem.store_item_id)
    ).all()
    items = [
        {
            "store_item_id": store_item.store_item_id,
            "item_id": item.item_id,
            "common_name": item.common_name,
            "store_common_name": store_item.common_name,
            "store_name": store.display_name,
            "store_product_id": store_item.store_product_id,
            "description": store_item.latest_description,
            "upc": store_item.upc,
            "mapping_confirmed": store_item.mapping_confirmed,
            "is_active": item.is_active,
            "last_purchase_date": last_purchase_date,
        }
        for store_item, item, store, last_purchase_date in rows
    ]
    canonical_items = session.scalars(
        select(Item).where(Item.is_active.is_(True)).order_by(Item.common_name, Item.item_id)
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="item_mapping.html",
        context={"store_items": items, "canonical_items": canonical_items},
    )


@router.get("/items")
def list_items(
    query: str | None = None,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> list[dict[str, object]]:
    statement = select(Item).order_by(Item.common_name, Item.item_id)
    if query:
        statement = statement.where(
            Item.common_name.ilike(contains_pattern(query), escape=LIKE_ESCAPE)
        )
    items = session.scalars(statement).all()
    store_item_counts = {
        item_id: count
        for item_id, count in session.execute(
            select(StoreItem.item_id, func.count(StoreItem.store_item_id)).group_by(
                StoreItem.item_id
            )
        )
    }
    return [
        {
            "item_id": item.item_id,
            "common_name": item.common_name,
            "is_active": item.is_active,
            "is_store_observed": item.is_store_observed,
            "superseded_by_item_id": item.superseded_by_item_id,
            "store_item_count": store_item_counts.get(item.item_id, 0),
        }
        for item in items
    ]


@router.post("/receipt-items/{receipt_item_id}/store-product-id")
def review_store_product_identifier(
    receipt_item_id: int,
    payload: ReviewedIdentifierRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        store_item = assign_reviewed_store_product_identifier(
            session,
            receipt_item_id,
            payload.store_product_id,
            user.id,
            payload.source_event_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    session.commit()
    return {
        "store_item_id": store_item.store_item_id,
        "item_id": store_item.item_id,
        "mapping_confirmed": store_item.mapping_confirmed,
    }


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
    session: Session = Depends(get_session),  # noqa: B008
) -> list[dict[str, object]]:
    statement = (
        select(
            StoreItem,
            Item,
            Store.display_name,
            func.max(Receipt.receipt_date).label("last_purchase_date"),
        )
        .join(Item, Item.item_id == StoreItem.item_id)
        .join(Store, Store.store_id == StoreItem.store_id)
        .outerjoin(ReceiptItem, ReceiptItem.store_item_id == StoreItem.store_item_id)
        .outerjoin(
            Receipt,
            and_(Receipt.receipt_pk == ReceiptItem.receipt_pk, Receipt.deleted_at.is_(None)),
        )
        .group_by(StoreItem.store_item_id, Item.item_id, Store.store_id)
        .order_by(Store.display_name, StoreItem.latest_description)
    )
    if unmapped_only:
        statement = statement.where(StoreItem.mapping_confirmed.is_(False))
    if query:
        term = contains_pattern(query)
        statement = statement.where(
            StoreItem.latest_description.ilike(term, escape=LIKE_ESCAPE)
            | StoreItem.store_product_id.ilike(term, escape=LIKE_ESCAPE)
            | StoreItem.common_name.ilike(term, escape=LIKE_ESCAPE)
            | Item.common_name.ilike(term, escape=LIKE_ESCAPE)
            | Store.display_name.ilike(term, escape=LIKE_ESCAPE)
        )
    rows = session.execute(statement).all()
    return [
        {
            "store_item_id": store_item.store_item_id,
            "store_id": store_item.store_id,
            "store_name": store_name,
            "store_product_id": store_item.store_product_id,
            "description": store_item.latest_description,
            "upc": store_item.upc,
            "common_name": store_item.common_name,
            "item_id": item.item_id,
            "item_common_name": item.common_name,
            "mapping_confirmed": store_item.mapping_confirmed,
            "last_purchase_date": (
                last_purchase_date.isoformat() if last_purchase_date is not None else None
            ),
        }
        for store_item, item, store_name, last_purchase_date in rows
    ]


@router.get("/items/{item_id}")
def get_item(
    item_id: str,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    mappings = session.scalars(
        select(StoreItem).where(StoreItem.item_id == item_id).order_by(StoreItem.store_id)
    ).all()
    return {
        "item_id": item.item_id,
        "common_name": item.common_name,
        "is_active": item.is_active,
        "is_store_observed": item.is_store_observed,
        "superseded_by_item_id": item.superseded_by_item_id,
        "store_items": [
            {
                "store_item_id": store_item.store_item_id,
                "store_id": store_item.store_id,
                "store_product_id": store_item.store_product_id,
                "description": store_item.latest_description,
            }
            for store_item in mappings
        ],
    }


@router.put("/items/{item_id}")
def update_item(
    item_id: str,
    payload: ItemUpdateRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    if not payload.model_fields_set:
        raise HTTPException(status_code=422, detail="At least one item field must be provided")
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    try:
        if "common_name" in payload.model_fields_set:
            set_item_common_name(session, item_id, payload.common_name, user.id)
        if payload.is_active is not None:
            item = set_item_active(session, item_id, payload.is_active, user.id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return {"item_id": item.item_id, "common_name": item.common_name, "is_active": item.is_active}


@router.put("/store-items/{store_item_id}")
def update_store_item(
    store_item_id: str,
    payload: StoreItemUpdateRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    if "common_name" not in payload.model_fields_set:
        raise HTTPException(status_code=422, detail="common_name must be provided")
    try:
        store_item = set_store_item_common_name(
            session, store_item_id, payload.common_name, user.id
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    session.commit()
    return {
        "store_item_id": store_item.store_item_id,
        "common_name": store_item.common_name,
    }


@router.post("/items/map")
def map_store_item(
    payload: ItemMapRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        store_item = confirm_store_item_mapping(
            session,
            payload.store_item_id,
            payload.item_id,
            user.id,
            effective_from=payload.effective_from,
            reason=payload.reason,
            source_event_id=payload.source_event_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if payload.store_common_name is not None:
        set_store_item_common_name(
            session, payload.store_item_id, payload.store_common_name, user.id
        )
    session.commit()
    return {
        "store_item_id": store_item.store_item_id,
        "item_id": store_item.item_id,
        "mapping_confirmed": store_item.mapping_confirmed,
    }


@router.post("/items/split")
def split_store_item(
    payload: ItemSplitRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    store_item = session.get(StoreItem, payload.store_item_id)
    if store_item is None:
        raise HTTPException(status_code=404, detail="Store item not found")
    item = Item(common_name=payload.common_name, is_store_observed=True)
    session.add(item)
    session.flush()
    try:
        mapped = confirm_store_item_mapping(
            session,
            store_item.store_item_id,
            item.item_id,
            user.id,
            effective_from=payload.effective_from,
            reason=payload.reason,
            source_event_id=payload.source_event_id,
            operation="SPLIT",
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    session.commit()
    return {"store_item_id": mapped.store_item_id, "item_id": mapped.item_id}


@router.post("/items/merge")
def merge_items(
    payload: ItemMergeRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        target = merge_canonical_items(
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
    session.commit()
    return {"item_id": target.item_id, "common_name": target.common_name}
