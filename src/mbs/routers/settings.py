from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from mbs.db import get_session
from mbs.domain.settings import MAX_RETENTION_DAYS
from mbs.models import AuthSession, User
from mbs.routers.dependencies import admin_csrf_session, admin_session, domain_http_error
from mbs.services.settings import change_retention_settings, read_retention_settings

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


class RetentionUpdate(BaseModel):
    """Omitted fields stay unchanged; an explicit null clears the period."""

    receipt_source_retention_days: int | None = Field(default=None, ge=1, le=MAX_RETENTION_DAYS)
    receipt_raw_retention_days: int | None = Field(default=None, ge=1, le=MAX_RETENTION_DAYS)
    reason: str = Field(min_length=1, max_length=2000)


@router.get("/retention")
def get_retention(
    _current: tuple[User, AuthSession] = Depends(admin_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, int | None]:
    return read_retention_settings(session)


@router.put("/retention")
def put_retention(
    payload: RetentionUpdate,
    current: tuple[User, AuthSession] = Depends(admin_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, int | None]:
    user, _ = current
    updates = {
        key: getattr(payload, key)
        for key in payload.model_fields_set - {"reason"}
        if key.endswith("_retention_days")
    }
    try:
        return change_retention_settings(session, updates, user.id, payload.reason)
    except ValueError as error:
        raise domain_http_error(error, status.HTTP_400_BAD_REQUEST) from error
