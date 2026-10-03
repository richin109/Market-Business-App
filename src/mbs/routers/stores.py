from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.responses import Response

from mbs.db import get_session
from mbs.domain.stores import StoreAdministrationConflict, StoreResolutionRequired
from mbs.errors import NotFoundError
from mbs.models import (
    AuthSession,
    User,
)
from mbs.routers.dependencies import manager_csrf_session, manager_session
from mbs.services.store_directory import StoreDirectoryService, get_store_directory_service

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
    service: StoreDirectoryService = Depends(get_store_directory_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="stores.html",
        context=service.page_context(session),
    )


@router.get("")
def list_stores(
    query: str | None = None,
    active_only: bool = False,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    service: StoreDirectoryService = Depends(get_store_directory_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> list[dict[str, object]]:
    return service.list_stores(session, query, active_only)


@router.get("/{store_id}")
def get_store(
    store_id: str,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    service: StoreDirectoryService = Depends(get_store_directory_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    try:
        return service.get_store(session, store_id)
    except NotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.put("/{store_id}")
def update_store(
    store_id: str,
    payload: StoreUpdateRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    service: StoreDirectoryService = Depends(get_store_directory_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        return service.update_store(
            session,
            store_id,
            payload.display_name,
            payload.is_active,
            payload.confirm_duplicate_name,
            user.id,
        )
    except NotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except StoreAdministrationConflict as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error


@router.post("/{store_id}/aliases")
def add_alias(
    store_id: str,
    payload: StoreAliasRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    service: StoreDirectoryService = Depends(get_store_directory_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        return service.add_alias(
            session, store_id, payload.raw_alias, payload.location_signature, user.id
        )
    except NotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except StoreResolutionRequired as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post("/merge")
def merge_store_records(
    payload: StoreMergeRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    service: StoreDirectoryService = Depends(get_store_directory_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        return service.merge_stores(
            session,
            payload.source_store_id,
            payload.target_store_id,
            user.id,
            payload.reason,
            payload.source_event_id,
        )
    except StoreAdministrationConflict as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post("/split")
def split_store_records(
    payload: StoreSplitRequest,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    service: StoreDirectoryService = Depends(get_store_directory_service),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        return service.split_stores(
            session,
            payload.source_store_id,
            payload.alias_keys,
            user.id,
            payload.reason,
            payload.source_event_id,
            payload.new_display_name,
        )
    except StoreAdministrationConflict as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
