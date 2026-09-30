from __future__ import annotations

import hashlib
import secrets
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import Lock

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs.models import AuditLog, AuthSession, PasswordResetToken, User

SESSION_IDLE_TIMEOUT = timedelta(hours=2)
SESSION_ABSOLUTE_TIMEOUT = timedelta(hours=12)
RESET_TOKEN_TIMEOUT = timedelta(minutes=30)
LOGIN_IP_WINDOW = timedelta(minutes=1)
LOGIN_ACCOUNT_LOCK = timedelta(minutes=15)
password_hasher = PasswordHasher()


class Role(StrEnum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    VIEWER = "VIEWER"


class LoginRateLimited(Exception):
    pass


class AccountLocked(Exception):
    pass


class LoginThrottle:
    def __init__(self) -> None:
        self._ip_failures: defaultdict[str, deque[datetime]] = defaultdict(deque)
        self._account_failures: defaultdict[str, int] = defaultdict(int)
        self._locked_until: dict[str, datetime] = {}
        self._lock = Lock()

    def check(self, username: str, client_ip: str | None, now: datetime) -> None:
        with self._lock:
            if client_ip is not None:
                failures = self._ip_failures[client_ip]
                while failures and failures[0] <= now - LOGIN_IP_WINDOW:
                    failures.popleft()
                if len(failures) >= 5:
                    raise LoginRateLimited
            locked_until = self._locked_until.get(username)
            if locked_until is not None:
                if locked_until > now:
                    raise AccountLocked
                del self._locked_until[username]
                self._account_failures[username] = 0

    def failure(self, username: str, client_ip: str | None, now: datetime) -> None:
        with self._lock:
            if client_ip is not None:
                self._ip_failures[client_ip].append(now)
            self._account_failures[username] += 1
            if self._account_failures[username] >= 10:
                self._locked_until[username] = now + LOGIN_ACCOUNT_LOCK

    def success(self, username: str) -> None:
        with self._lock:
            self._account_failures[username] = 0


login_throttle = LoginThrottle()


def utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_user(session: Session, username: str, password: str, role: Role) -> User:
    if not username or not password:
        raise ValueError("Username and password are required")
    user = User(username=username.strip(), password_hash=hash_password(password), role=role.value)
    session.add(user)
    session.flush()
    return user


def authenticate(
    session: Session,
    username: str,
    password: str,
    client_ip: str | None = None,
    now: datetime | None = None,
) -> User | None:
    normalized_username = username.strip()
    current = now or utc_now()
    login_throttle.check(normalized_username, client_ip, current)
    user = session.scalar(select(User).where(User.username == normalized_username))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        login_throttle.failure(normalized_username, client_ip, current)
        return None
    login_throttle.success(normalized_username)
    return user


def create_session(session: Session, user: User, now: datetime | None = None) -> tuple[str, str]:
    current = now or utc_now()
    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    session.add(
        AuthSession(
            token_hash=_token_hash(session_token),
            user_id=user.id,
            csrf_token_hash=_token_hash(csrf_token),
            last_seen_at=current,
            expires_at=current + SESSION_ABSOLUTE_TIMEOUT,
        )
    )
    session.flush()
    return session_token, csrf_token


def resolve_session(
    session: Session, session_token: str, now: datetime | None = None
) -> tuple[User, AuthSession] | None:
    current = now or utc_now()
    auth_session = session.scalar(
        select(AuthSession).where(AuthSession.token_hash == _token_hash(session_token))
    )
    if auth_session is None or auth_session.revoked_at is not None:
        return None
    idle_expired = _as_utc(auth_session.last_seen_at) + SESSION_IDLE_TIMEOUT <= current
    if _as_utc(auth_session.expires_at) <= current or idle_expired:
        auth_session.revoked_at = current
        return None
    user = session.get(User, auth_session.user_id)
    if user is None or not user.is_active:
        return None
    auth_session.last_seen_at = current
    return user, auth_session


def verify_csrf(auth_session: AuthSession, csrf_token: str) -> bool:
    return secrets.compare_digest(auth_session.csrf_token_hash, _token_hash(csrf_token))


def require_role(user: User, *roles: Role) -> None:
    if user.role not in {role.value for role in roles}:
        raise PermissionError("Insufficient role")


def revoke_session(
    session: Session, auth_session: AuthSession, now: datetime | None = None
) -> None:
    auth_session.revoked_at = now or utc_now()


def issue_admin_reset(
    session: Session, admin: User, target: User, now: datetime | None = None
) -> str:
    require_role(admin, Role.ADMIN)
    current = now or utc_now()
    token = secrets.token_urlsafe(32)
    session.add(
        PasswordResetToken(
            token_hash=_token_hash(token),
            user_id=target.id,
            expires_at=current + RESET_TOKEN_TIMEOUT,
        )
    )
    session.add(
        AuditLog(
            event_type="PASSWORD_RESET_ISSUED",
            actor=str(admin.id),
            entity_type="User",
            entity_id=str(target.id),
        )
    )
    session.flush()
    return token


def consume_reset(
    session: Session, token: str, new_password: str, now: datetime | None = None
) -> User:
    current = now or utc_now()
    reset = session.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == _token_hash(token))
    )
    if reset is None or reset.used_at is not None or _as_utc(reset.expires_at) <= current:
        raise ValueError("Reset token is invalid or expired")
    user = session.get(User, reset.user_id)
    if user is None or not user.is_active:
        raise ValueError("Reset target is unavailable")
    user.password_hash = hash_password(new_password)
    reset.used_at = current
    session.add(
        AuditLog(
            event_type="PASSWORD_RESET_COMPLETED",
            entity_type="User",
            entity_id=str(user.id),
        )
    )
    return user


def recover_admin(session: Session, username: str, new_password: str) -> User:
    user = session.scalar(select(User).where(User.username == username.strip()))
    if user is None or user.role != Role.ADMIN.value or not user.is_active:
        raise ValueError("Admin recovery target is unavailable")
    user.password_hash = hash_password(new_password)
    session.add(
        AuditLog(
            event_type="ADMIN_RECOVERY_COMPLETED",
            entity_type="User",
            entity_id=str(user.id),
        )
    )
    login_throttle.success(user.username)
    return user
