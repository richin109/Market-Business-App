from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from mbs.auth import (
    SESSION_ABSOLUTE_TIMEOUT,
    AccountLocked,
    LoginRateLimited,
)
from mbs.db import get_session
from mbs.errors import NotFoundError
from mbs.models import AuthSession, User
from mbs.routers.dependencies import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    admin_csrf_session,
    admin_session,
    csrf_session_user,
    current_session_user,
)
from mbs.services.auth import (
    list_users as read_users,
)
from mbs.services.auth import (
    login_and_create_session,
    logout_session,
    request_admin_reset,
)
from mbs.services.auth import (
    reset_password as change_password,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
COOKIE_MAX_AGE_SECONDS = int(SESSION_ABSOLUTE_TIMEOUT.total_seconds())


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


class ResetRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=1, max_length=1024)


class AdminResetRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)


@router.post("/login")
def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, str]:
    try:
        authenticated = login_and_create_session(
            session,
            payload.username,
            payload.password,
            client_ip=request.client.host if request.client else None,
        )
    except LoginRateLimited as error:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS) from error
    except AccountLocked as error:
        raise HTTPException(status_code=status.HTTP_423_LOCKED) from error
    if authenticated is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    user, session_token, csrf_token = authenticated
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=COOKIE_MAX_AGE_SECONDS,
        httponly=False,
        secure=True,
        samesite="strict",
    )
    return {"csrf_token": csrf_token, "role": user.role}


@router.get("/me")
def current_user(
    current: tuple[User, AuthSession] = Depends(current_session_user),  # noqa: B008
) -> dict[str, str | int]:
    user, _ = current
    return {"id": user.id, "username": user.username, "role": user.role}


@router.post("/logout")
def logout(
    response: Response,
    current: tuple[User, AuthSession] = Depends(csrf_session_user),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, str]:
    _, auth_session = current
    logout_session(session, auth_session)
    response.delete_cookie(SESSION_COOKIE)
    response.delete_cookie(CSRF_COOKIE)
    return {"status": "ok"}


@router.post("/admin/reset")
def admin_reset(
    payload: AdminResetRequest,
    current: tuple[User, AuthSession] = Depends(admin_csrf_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, str]:
    admin, _ = current
    try:
        return {"reset_token": request_admin_reset(session, admin, payload.username)}
    except NotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.post("/reset")
def reset_password(
    payload: ResetRequest,
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, str]:
    try:
        change_password(session, payload.token, payload.new_password)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return {"status": "ok"}


@router.get("/admin/users")
def list_users(
    _current: tuple[User, AuthSession] = Depends(admin_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> list[dict[str, str | int]]:
    return read_users(session)
