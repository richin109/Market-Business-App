from collections.abc import Sequence
from datetime import date

from fastapi import Body, Cookie, Depends, FastAPI, Header, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mbs.auth import (
    AccountLocked,
    LoginRateLimited,
    Role,
    authenticate,
    consume_reset,
    create_session,
    issue_admin_reset,
    require_role,
    resolve_session,
    revoke_session,
    verify_csrf,
)
from mbs.db import get_session
from mbs.models import AuthSession, Receipt, ReceiptItem, User
from mbs.receipts.upload import ReceiptUploadService, UploadStatus

app = FastAPI(title="Market Business System")
SESSION_COOKIE = "mbs_session"
receipt_upload_service: ReceiptUploadService | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class ResetRequest(BaseModel):
    token: str
    new_password: str


class AdminResetRequest(BaseModel):
    username: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/receipts")
def list_receipts(
    store: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = 50,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    session: Session = Depends(get_session),  # noqa: B008
) -> list[dict[str, object]]:
    _session_user(session, session_token)
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pagination")
    query = select(Receipt).where(Receipt.deleted_at.is_(None))
    if store is not None:
        query = query.where(Receipt.store == store)
    if date_from is not None:
        query = query.where(Receipt.receipt_date >= date_from)
    if date_to is not None:
        query = query.where(Receipt.receipt_date <= date_to)
    receipts = session.scalars(
        query.order_by(Receipt.receipt_date.desc(), Receipt.receipt_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [
        {
            "receipt_pk": receipt.receipt_pk,
            "receipt_id": receipt.receipt_id,
            "store": receipt.store,
            "purchase_date": receipt.receipt_date.isoformat(),
            "item_count": session.scalar(
                select(func.count(ReceiptItem.id)).where(
                    ReceiptItem.receipt_pk == receipt.receipt_pk
                )
            )
            or 0,
        }
        for receipt in receipts
    ]


@app.get("/api/v1/receipts/{receipt_pk}")
def get_receipt(
    receipt_pk: str,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    _session_user(session, session_token)
    receipt = session.scalar(
        select(Receipt).where(Receipt.receipt_pk == receipt_pk, Receipt.deleted_at.is_(None))
    )
    if receipt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    items = session.scalars(
        select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt_pk).order_by(ReceiptItem.id)
    ).all()
    return _receipt_response(receipt, items)


@app.get("/api/v1/receipts/{receipt_pk}/items")
def get_receipt_items(
    receipt_pk: str,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    session: Session = Depends(get_session),  # noqa: B008
) -> list[dict[str, object]]:
    _session_user(session, session_token)
    receipt_exists = session.scalar(
        select(Receipt.receipt_pk).where(
            Receipt.receipt_pk == receipt_pk, Receipt.deleted_at.is_(None)
        )
    )
    if receipt_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    items = session.scalars(
        select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt_pk).order_by(ReceiptItem.id)
    ).all()
    return [_item_response(item) for item in items]


def _receipt_response(receipt: Receipt, items: Sequence[ReceiptItem]) -> dict[str, object]:
    return {
        "receipt_pk": receipt.receipt_pk,
        "receipt_id": receipt.receipt_id,
        "store": receipt.store,
        "purchase_date": receipt.receipt_date.isoformat(),
        "purchase_time": receipt.receipt_time.isoformat(),
        "transaction_number": receipt.transaction_number,
        "subtotal": str(receipt.subtotal) if receipt.subtotal is not None else None,
        "tax": str(receipt.tax) if receipt.tax is not None else None,
        "total": str(receipt.total),
        "payment_method": receipt.payment_method,
        "items": [_item_response(item) for item in items],
    }


def _item_response(item: ReceiptItem) -> dict[str, object]:
    return {
        "description": item.description,
        "upc": item.upc,
        "quantity": str(item.quantity) if item.quantity is not None else None,
        "weight_lb": str(item.weight_lb) if item.weight_lb is not None else None,
        "unit_price": str(item.unit_price) if item.unit_price is not None else None,
        "line_total": str(item.line_total),
        "category": item.category,
        "business_disposition": item.business_disposition,
    }


@app.post("/api/v1/receipts/upload")
def upload_receipt(
    request: Request,
    body: bytes = Body(...),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, str | None]:
    user, _ = _session_user(session, session_token)
    try:
        require_role(user, Role.ADMIN, Role.MANAGER)
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    if receipt_upload_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Upload unavailable",
        )
    media_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0].strip()
    try:
        result = receipt_upload_service.upload(body, media_type)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    if result.status is UploadStatus.SCAN_PENDING:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=result.status)
    if result.status is UploadStatus.MALWARE_REJECTED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.status)
    if result.status is UploadStatus.EXACT_DUPLICATE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.status)
    return {
        "source_sha256": result.source_sha256,
        "status": result.status,
        "file_key": result.file_key,
        "receipt_id": result.receipt.receipt_id if result.receipt is not None else None,
    }


@app.post("/api/v1/auth/login")
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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    session_token, csrf_token = create_session(session, user)
    session.commit()
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=43200,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return {"csrf_token": csrf_token, "role": user.role}


def _session_user(session: Session, session_token: str | None) -> tuple[User, AuthSession]:
    if session_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    resolved = resolve_session(session, session_token)
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    return resolved


@app.get("/api/v1/auth/me")
def current_user(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, str | int]:
    user, _ = _session_user(session, session_token)
    return {"id": user.id, "username": user.username, "role": user.role}


@app.post("/api/v1/auth/logout")
def logout(
    response: Response,
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, str]:
    _, auth_session = _session_user(session, session_token)
    if csrf_token is None or not verify_csrf(auth_session, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
    revoke_session(session, auth_session)
    session.commit()
    response.delete_cookie(SESSION_COOKIE)
    return {"status": "ok"}


@app.post("/api/v1/auth/admin/reset")
def admin_reset(
    payload: AdminResetRequest,
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, str]:
    admin, auth_session = _session_user(session, session_token)
    if csrf_token is None or not verify_csrf(auth_session, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
    try:
        require_role(admin, Role.ADMIN)
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    target = session.scalar(select(User).where(User.username == payload.username.strip()))
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    reset_token = issue_admin_reset(session, admin, target)
    session.commit()
    return {"reset_token": reset_token}


@app.post("/api/v1/auth/reset")
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


@app.get("/api/v1/auth/admin/users")
def list_users(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    session: Session = Depends(get_session),  # noqa: B008
) -> list[dict[str, str | int]]:
    user, _ = _session_user(session, session_token)
    try:
        require_role(user, Role.ADMIN)
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    return [
        {"id": listed.id, "username": listed.username, "role": listed.role}
        for listed in session.scalars(select(User).order_by(User.id))
    ]
