from __future__ import annotations

import hashlib
import secrets
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import Lock

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs.models import AuditLog, AuthSession, PasswordResetToken, User

SESSION_IDLE_TIMEOUT = timedelta(hours=2)
SESSION_ABSOLUTE_TIMEOUT = timedelta(hours=12)
SESSION_TOUCH_INTERVAL = timedelta(minutes=1)
RESET_TOKEN_TIMEOUT = timedelta(minutes=30)
LOGIN_IP_WINDOW = timedelta(minutes=1)
LOGIN_ACCOUNT_LOCK = timedelta(minutes=15)
MAX_TRACKED_THROTTLE_KEYS = 10_000
MIN_PASSWORD_LENGTH = 12
password_hasher = PasswordHasher()
_DUMMY_PASSWORD_HASH = password_hasher.hash(secrets.token_urlsafe(32))


class Role(StrEnum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    VIEWER = "VIEWER"


class LoginRateLimited(Exception):
    pass


class AccountLocked(Exception):
    pass


@dataclass(frozen=True)
class ThrottleThresholds:
    ip_limit_reached: bool = False
    account_lock_started: bool = False


def _trim_oldest[T](entries: OrderedDict[str, T]) -> None:
    while len(entries) > MAX_TRACKED_THROTTLE_KEYS:
        entries.popitem(last=False)


class LoginThrottle:
    def __init__(self) -> None:
        self._ip_failures: OrderedDict[str, deque[datetime]] = OrderedDict()
        self._account_failures: OrderedDict[str, int] = OrderedDict()
        self._locked_until: OrderedDict[str, datetime] = OrderedDict()
        self._lock = Lock()

    def check(self, username: str, client_ip: str | None, now: datetime) -> None:
        with self._lock:
            if client_ip is not None:
                failures = self._ip_failures.get(client_ip)
                if failures is not None:
                    while failures and failures[0] <= now - LOGIN_IP_WINDOW:
                        failures.popleft()
                    if failures:
                        self._ip_failures.move_to_end(client_ip)
                        if len(failures) >= 5:
                            raise LoginRateLimited
                    else:
                        del self._ip_failures[client_ip]
            locked_until = self._locked_until.get(username)
            if locked_until is not None:
                if locked_until > now:
                    self._locked_until.move_to_end(username)
                    raise AccountLocked
                del self._locked_until[username]
                self._account_failures.pop(username, None)

    def failure(self, username: str, client_ip: str | None, now: datetime) -> ThrottleThresholds:
        with self._lock:
            ip_limit_reached = False
            if client_ip is not None:
                failures = self._ip_failures.setdefault(client_ip, deque())
                while failures and failures[0] <= now - LOGIN_IP_WINDOW:
                    failures.popleft()
                failures.append(now)
                self._ip_failures.move_to_end(client_ip)
                ip_limit_reached = len(failures) == 5
                _trim_oldest(self._ip_failures)

            account_failures = self._account_failures.get(username, 0) + 1
            self._account_failures[username] = account_failures
            self._account_failures.move_to_end(username)
            _trim_oldest(self._account_failures)
            account_lock_started = account_failures == 10
            if account_failures >= 10:
                self._locked_until[username] = now + LOGIN_ACCOUNT_LOCK
                self._locked_until.move_to_end(username)
                _trim_oldest(self._locked_until)
            return ThrottleThresholds(ip_limit_reached, account_lock_started)

    def success(self, username: str) -> None:
        with self._lock:
            self._account_failures.pop(username, None)
            self._locked_until.pop(username, None)


login_throttle = LoginThrottle()


def utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long")
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerifyMismatchError):
        return False


def _record_login_threshold(
    session: Session,
    event_type: str,
    username: str,
    client_ip: str | None,
) -> None:
    username_hash = hashlib.sha256(username.encode("utf-8")).hexdigest()
    client_ip_hash = (
        hashlib.sha256(client_ip.encode("utf-8")).hexdigest() if client_ip is not None else None
    )
    session.add(
        AuditLog(
            event_type=event_type,
            entity_type="AuthenticationAttempt",
            entity_id=username_hash,
            details=f"client_ip_sha256={client_ip_hash or 'unknown'}",
        )
    )


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
    password_hash = (
        user.password_hash if user is not None and user.is_active else _DUMMY_PASSWORD_HASH
    )
    password_matches = verify_password(password, password_hash)
    if user is None or not user.is_active or not password_matches:
        thresholds = login_throttle.failure(normalized_username, client_ip, current)
        if thresholds.ip_limit_reached:
            _record_login_threshold(
                session, "LOGIN_IP_THROTTLE_THRESHOLD", normalized_username, client_ip
            )
        if thresholds.account_lock_started:
            _record_login_threshold(
                session, "LOGIN_ACCOUNT_LOCK_STARTED", normalized_username, client_ip
            )
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
    if current - _as_utc(auth_session.last_seen_at) >= SESSION_TOUCH_INTERVAL:
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


def _revoke_user_access(session: Session, user_id: int, now: datetime) -> None:
    sessions = session.scalars(
        select(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .with_for_update()
    )
    for auth_session in sessions:
        auth_session.revoked_at = now

    reset_tokens = session.scalars(
        select(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None))
        .with_for_update()
    )
    for reset_token in reset_tokens:
        reset_token.used_at = now


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
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == _token_hash(token))
        .with_for_update()
    )
    if reset is None or reset.used_at is not None or _as_utc(reset.expires_at) <= current:
        raise ValueError("Reset token is invalid or expired")
    user = session.scalar(select(User).where(User.id == reset.user_id).with_for_update())
    if user is None or not user.is_active:
        raise ValueError("Reset target is unavailable")
    user.password_hash = hash_password(new_password)
    reset.used_at = current
    _revoke_user_access(session, user.id, current)
    session.add(
        AuditLog(
            event_type="PASSWORD_RESET_COMPLETED",
            entity_type="User",
            entity_id=str(user.id),
        )
    )
    return user


def recover_admin(session: Session, username: str, new_password: str) -> User:
    user = session.scalar(select(User).where(User.username == username.strip()).with_for_update())
    if user is None or user.role != Role.ADMIN.value or not user.is_active:
        raise ValueError("Admin recovery target is unavailable")
    user.password_hash = hash_password(new_password)
    current = utc_now()
    _revoke_user_access(session, user.id, current)
    session.add(
        AuditLog(
            event_type="ADMIN_RECOVERY_COMPLETED",
            entity_type="User",
            entity_id=str(user.id),
        )
    )
    login_throttle.success(user.username)
    return user
