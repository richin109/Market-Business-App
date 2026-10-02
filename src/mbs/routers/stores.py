from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session
from starlette.responses import Response

from mbs.db import get_session
from mbs.models import (
    AuditLog,
    AuthSession,
    Receipt,
    Store,
    StoreAliasKey,
    StoreAliasSpelling,
    User,
)
from mbs.routers.dependencies import manager_csrf_session, manager_session
from mbs.routers.query import LIKE_ESCAPE, contains_pattern
from mbs.store_admin import StoreAdministrationConflict, merge_stores, split_store_aliases
from mbs.stores import StoreResolutionRequired, add_store_alias

router = APIRouter(prefix="/api/v1/stores", tags=["stores"])
templates = Jinja2Templates(directory=str(Path(__file__).parents[1] / "templates"))


class StoreUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None
    confirm_duplicate_name: bool = False


class StoreAliasRequest(BaseModel):
    raw_alias: str = Field(min_length=1, max_length=255)
    location_signature: str | None = Field(default=None, max_length=500)


class StoreMergeRequest(BaseModel):
    source_store_id: str = Field(min_length=1, max_length=36)
    target_store_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(min_length=1, max_length=1000)
    source_event_id: str = Field(min_length=1, max_length=255)


class StoreSplitRequest(BaseModel):
    source_store_id: str = Field(min_length=1, max_length=36)
    alias_keys: list[str] = Field(min_length=1, max_length=100)
    new_display_name: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=1000)
    source_event_id: str = Field(min_length=1, max_length=255)


@router.get("/page", include_in_schema=False)
def stores_page(
    request: Request,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> Response:
    rows = session.execute(
        select(
            Store,
            func.count(Receipt.receipt_pk).label("receipt_count"),
            func.max(Receipt.receipt_date).label("last_purchase_date"),
        )
        .outerjoin(Receipt, and_(Receipt.store_id == Store.store_id, Receipt.deleted_at.is_(None)))
        .group_by(Store.store_id)
        .order_by(Store.display_name, Store.store_id)
    ).all()
    aliases_by_store: dict[str, list[dict[str, str]]] = {}
    for store_id, normalized_key, raw_alias in session.execute(
        select(StoreAliasKey.store_id, StoreAliasKey.normalized_key, StoreAliasSpelling.raw_alias)
        .outerjoin(
            StoreAliasSpelling,
            StoreAliasSpelling.normalized_key == StoreAliasKey.normalized_key,
        )
        .order_by(StoreAliasKey.normalized_key, StoreAliasSpelling.raw_alias)
    ):
        if raw_alias is not None:
            aliases_by_store.setdefault(store_id, []).append(
                {"normalized_key": normalized_key, "raw_alias": raw_alias}
            )
    rendered_stores: list[dict[str, object]] = []
    for store, receipt_count, last_purchase_date in rows:
        aliases = aliases_by_store.get(store.store_id, [])
        rendered_stores.append(
            {
                "store_id": store.store_id,
                "display_name": store.display_name,
                "is_active": store.is_active,
                "alias_count": len({alias["normalized_key"] for alias in aliases}),
                "receipt_count": receipt_count,
                "last_purchase_date": last_purchase_date,
                "aliases": aliases,
            }
        )
    return templates.TemplateResponse(
        request=request,
        name="stores.html",
        context={"stores": rendered_stores},
    )


@router.get("")
def list_stores(
    query: str | None = None,
    active_only: bool = False,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> list[dict[str, object]]:
    statement = (
        select(
            Store,
            func.count(func.distinct(StoreAliasKey.normalized_key)).label("alias_count"),
            func.count(func.distinct(Receipt.receipt_pk)).label("receipt_count"),
            func.max(Receipt.receipt_date).label("last_purchase_date"),
        )
        .outerjoin(StoreAliasKey, StoreAliasKey.store_id == Store.store_id)
        .outerjoin(Receipt, and_(Receipt.store_id == Store.store_id, Receipt.deleted_at.is_(None)))
        .group_by(Store.store_id)
        .order_by(Store.is_active.desc(), Store.display_name, Store.store_id)
    )
    if query:
        statement = statement.where(
            Store.display_name.ilike(contains_pattern(query), escape=LIKE_ESCAPE)
        )
    if active_only:
        statement = statement.where(Store.is_active.is_(True))
    rows = session.execute(statement).all()
    return [
        {
            "store_id": store.store_id,
            "display_name": store.display_name,
            "is_active": store.is_active,
            "superseded_by_store_id": store.superseded_by_store_id,
            "alias_count": alias_count,
            "receipt_count": receipt_count,
            "last_purchase_date": (
                last_purchase_date.isoformat() if last_purchase_date is not None else None
            ),
        }
        for store, alias_count, receipt_count, last_purchase_date in rows
    ]


@router.get("/{store_id}")
def get_store(
    store_id: str,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    store = session.get(Store, store_id)
    if store is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
    aliases = session.execute(
        select(StoreAliasKey.normalized_key, StoreAliasSpelling.raw_alias)
        .outerjoin(
            StoreAliasSpelling,
            StoreAliasSpelling.normalized_key == StoreAliasKey.normalized_key,
        )
        .where(StoreAliasKey.store_id == store_id)
        .order_by(StoreAliasKey.normalized_key, StoreAliasSpelling.raw_alias)
    ).all()
    return {
        "store_id": store.store_id,
        "display_name": store.display_name,
        "is_active": store.is_active,
        "superseded_by_store_id": store.superseded_by_store_id,
        "aliases": [
            {"normalized_key": normalized_key, "raw_alias": raw_alias}
            for normalized_key, raw_alias in aliases
        ],
    }


@router.put("/{store_id}")
def update_store(
    store_id: str,
    payload: StoreUpdateRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    store = session.scalar(select(Store).where(Store.store_id == store_id).with_for_update())
    if store is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
    if store.superseded_by_store_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A superseded store cannot be edited",
        )
    if payload.display_name is None and payload.is_active is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one store field must be provided",
        )
    old_name = store.display_name
    old_active = store.is_active
    if payload.display_name is not None:
        display_name = payload.display_name.strip()
        if not display_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Name is required",
            )
        duplicates = session.scalars(
            select(Store).where(
                Store.store_id != store_id,
                Store.is_active.is_(True),
            )
        ).all()
        duplicate_exists = any(
            other.display_name.casefold() == display_name.casefold() for other in duplicates
        )
        if duplicate_exists and not payload.confirm_duplicate_name:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Another active store uses this display name; explicit confirmation is required"
                ),
            )
        store.display_name = display_name
    if payload.is_active is not None:
        store.is_active = payload.is_active
    if old_name != store.display_name or old_active != store.is_active:
        session.add(
            AuditLog(
                event_type="STORE_UPDATED",
                actor=str(user.id),
                entity_type="Store",
                entity_id=store.store_id,
                details=(
                    f"display_name={old_name!r}->{store.display_name!r}; "
                    f"is_active={old_active}->{store.is_active}"
                ),
            )
        )
    session.commit()
    return {
        "store_id": store.store_id,
        "display_name": store.display_name,
        "is_active": store.is_active,
    }


@router.post("/{store_id}/aliases")
def add_alias(
    store_id: str,
    payload: StoreAliasRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    store = session.get(Store, store_id)
    if store is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
    try:
        alias_key, created = add_store_alias(
            session, store, payload.raw_alias, payload.location_signature
        )
    except StoreResolutionRequired as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    session.add(
        AuditLog(
            event_type="STORE_ALIAS_ADDED" if created else "STORE_ALIAS_CONFIRMED",
            actor=str(user.id),
            entity_type="Store",
            entity_id=store.store_id,
            details=(
                f"raw_alias={payload.raw_alias!r}; normalized_key={alias_key.normalized_key}; "
                f"created={created}"
            ),
        )
    )
    session.commit()
    return {
        "store_id": store.store_id,
        "normalized_key": alias_key.normalized_key,
        "raw_alias": payload.raw_alias.strip(),
        "created": created,
    }


@router.post("/merge")
def merge_store_records(
    payload: StoreMergeRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        target, idempotent = merge_stores(
            session,
            payload.source_store_id,
            payload.target_store_id,
            user.id,
            payload.reason,
            payload.source_event_id,
        )
    except StoreAdministrationConflict as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    session.commit()
    return {
        "store_id": target.store_id,
        "display_name": target.display_name,
        "idempotent": idempotent,
    }


@router.post("/split")
def split_store_records(
    payload: StoreSplitRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        target, idempotent = split_store_aliases(
            session,
            payload.source_store_id,
            payload.alias_keys,
            user.id,
            payload.reason,
            payload.source_event_id,
            new_display_name=payload.new_display_name,
        )
    except StoreAdministrationConflict as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    session.commit()
    return {
        "store_id": target.store_id,
        "display_name": target.display_name,
        "idempotent": idempotent,
    }
