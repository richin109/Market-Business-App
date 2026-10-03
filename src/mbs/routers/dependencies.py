from __future__ import annotations

from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from mbs.auth import Role, require_role, verify_csrf
from mbs.db import get_session
from mbs.errors import NotFoundError
from mbs.media_assets import MediaAssetService
from mbs.models import AuthSession, User
from mbs.receipts.upload import ReceiptUploadService
from mbs.services.auth import resolve_request_session

SESSION_COOKIE = "mbs_session"
CSRF_COOKIE = "mbs_csrf"


@dataclass(frozen=True)
class BoundedUpload:
    source: bytes
    media_type: str
    uploaded_by: int


def current_session_user(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    session: Session = Depends(get_session),  # noqa: B008
) -> tuple[User, AuthSession]:
    if session_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    resolved = resolve_request_session(session, session_token)
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    return resolved


def csrf_session_user(
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    current: tuple[User, AuthSession] = Depends(current_session_user),  # noqa: B008
) -> tuple[User, AuthSession]:
    user, auth_session = current
    if csrf_token is None or not verify_csrf(auth_session, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
    return user, auth_session


def domain_http_error(error: ValueError, default_status: int) -> HTTPException:
    code = status.HTTP_404_NOT_FOUND if isinstance(error, NotFoundError) else default_status
    return HTTPException(status_code=code, detail=str(error))


def _require_roles(user: User, *roles: Role) -> None:
    try:
        require_role(user, *roles)
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error


def manager_session(
    current: tuple[User, AuthSession] = Depends(current_session_user),  # noqa: B008
) -> tuple[User, AuthSession]:
    _require_roles(current[0], Role.ADMIN, Role.MANAGER)
    return current


def manager_csrf_session(
    current: tuple[User, AuthSession] = Depends(csrf_session_user),  # noqa: B008
) -> tuple[User, AuthSession]:
    return manager_session(current)


def admin_session(
    current: tuple[User, AuthSession] = Depends(current_session_user),  # noqa: B008
) -> tuple[User, AuthSession]:
    _require_roles(current[0], Role.ADMIN)
    return current


def admin_csrf_session(
    current: tuple[User, AuthSession] = Depends(csrf_session_user),  # noqa: B008
) -> tuple[User, AuthSession]:
    return admin_session(current)


def get_media_asset_service(request: Request) -> MediaAssetService:
    service = getattr(request.app.state, "media_asset_service", None)
    if not isinstance(service, MediaAssetService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Media asset storage unavailable",
        )
    return service


def get_receipt_upload_service(request: Request) -> ReceiptUploadService:
    service = getattr(request.app.state, "receipt_upload_service", None)
    if not isinstance(service, ReceiptUploadService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Upload unavailable",
        )
    return service


async def authorized_upload_body(
    request: Request,
    current: tuple[User, AuthSession] = Depends(manager_csrf_session),  # noqa: B008
    service: ReceiptUploadService = Depends(get_receipt_upload_service),  # noqa: B008
) -> BoundedUpload:
    user, _ = current
    max_file_bytes = service.max_file_bytes
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Content-Length",
            ) from error
        if declared_length > max_file_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Receipt source exceeds the configured size limit",
            )
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > max_file_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Receipt source exceeds the configured size limit",
            )
        body.extend(chunk)
    media_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0].strip()
    return BoundedUpload(bytes(body), media_type, user.id)
