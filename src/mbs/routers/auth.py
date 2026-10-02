from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs.auth import (
    SESSION_ABSOLUTE_TIMEOUT,
    AccountLocked,
    LoginRateLimited,
    authenticate,
    consume_reset,
    create_session,
    issue_admin_reset,
    revoke_session,
)
from mbs.db import get_session
from mbs.models import AuthSession, User
from mbs.routers.dependencies import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    admin_csrf_session,
    admin_session,
    csrf_session_user,
    current_session_user,
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
        user = authenticate(
            session,
            payload.username,
            payload.password,
            client_ip=request.client.host if request.client else None,
        )
    except LoginRateLimited as error:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS) from error
    except AccountLocked as error:
        raise HTTPException(status_code=status.HTTP_423_LOCKED) from error
    if user is None:
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    session_token, csrf_token = create_session(session, user)
    session.commit()
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
    revoke_session(session, auth_session)
    session.commit()
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
    target = session.scalar(select(User).where(User.username == payload.username.strip()))
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    reset_token = issue_admin_reset(session, admin, target)
    session.commit()
    return {"reset_token": reset_token}


@router.post("/reset")
def reset_password(
    payload: ResetRequest,
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, str]:
    try:
        consume_reset(session, payload.token, payload.new_password)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    session.commit()
    return {"status": "ok"}


@router.get("/admin/users")
def list_users(
    _current: tuple[User, AuthSession] = Depends(admin_session),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> list[dict[str, str | int]]:
    return [
        {"id": listed.id, "username": listed.username, "role": listed.role}
        for listed in session.scalars(select(User).order_by(User.id))
    ]
