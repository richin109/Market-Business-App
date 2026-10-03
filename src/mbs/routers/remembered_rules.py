from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request, status
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.responses import Response

from mbs.db import get_session
from mbs.models import AuthSession, User
from mbs.receipts.approval import DispositionSubtype
from mbs.receipts.ocr import BusinessDisposition
from mbs.routers.dependencies import domain_http_error, manager_csrf_session, manager_session
from mbs.services.remembered_rules import (
    change_remembered_rule,
    remembered_rules_context,
    remembered_rules_response,
    remove_remembered_rule,
)

router = APIRouter(prefix="/api/v1/remembered-rules", tags=["remembered-rules"])
templates = Jinja2Templates(directory=str(Path(__file__).parents[1] / "templates"))


class RememberedRuleCorrection(BaseModel):
    disposition: BusinessDisposition
    disposition_subtype: DispositionSubtype = DispositionSubtype.NONE
    reason: str = Field(min_length=1, max_length=2000)


class RememberedRuleClear(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


@router.get("/page", include_in_schema=False)
def rules_page(
    request: Request,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="remembered_rules.html",
        context=remembered_rules_context(session),
    )


@router.get("")
def list_rules(
    store_id: str | None = None,
    _current: tuple[User, AuthSession] = Depends(manager_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> list[dict[str, object]]:
    return remembered_rules_response(session, store_id)


@router.put("/{store_item_id}")
def correct_rule(
    store_item_id: str,
    payload: RememberedRuleCorrection,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        return change_remembered_rule(
            session,
            store_item_id,
            payload.disposition,
            payload.disposition_subtype,
            user.id,
            payload.reason,
        )
    except ValueError as error:
        raise domain_http_error(error, status.HTTP_400_BAD_REQUEST) from error


@router.delete("/{store_item_id}")
def clear_rule(
    store_item_id: str,
    payload: RememberedRuleClear,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    user, _ = current
    try:
        return remove_remembered_rule(session, store_item_id, user.id, payload.reason)
    except ValueError as error:
        raise domain_http_error(error, status.HTTP_400_BAD_REQUEST) from error
