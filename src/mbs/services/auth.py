from __future__ import annotations

import hashlib
import secrets
from collections import OrderedDict, deque
from datetime import UTC, datetime
from threading import Lock

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy.orm import Session

from mbs.domain.auth import (
    LOGIN_ACCOUNT_LOCK,
    LOGIN_IP_WINDOW,
    MIN_PASSWORD_LENGTH,
    RESET_TOKEN_TIMEOUT,
    SESSION_ABSOLUTE_TIMEOUT,
    SESSION_IDLE_TIMEOUT,
    SESSION_TOUCH_INTERVAL,
    AccountLocked,
    LoginRateLimited,
    Role,
    ThrottleThresholds,
)
from mbs.domain.auth import _as_utc as _as_utc
from mbs.domain.auth import _token_hash as _token_hash
from mbs.errors import ConflictError, NotFoundError
from mbs.models import AuditLog, AuthSession, PasswordResetToken, User
from mbs.repositories.auth import AuthRepository

repository = AuthRepository()

MAX_TRACKED_THROTTLE_KEYS = 10_000
password_hasher = PasswordHasher()
_DUMMY_PASSWORD_HASH = password_hasher.hash(secrets.token_urlsafe(32))


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
    repository.add(
        session,
        AuditLog(
            event_type=event_type,
            entity_type="AuthenticationAttempt",
            entity_id=username_hash,
            details=f"client_ip_sha256={client_ip_hash or 'unknown'}",
        ),
    )


def create_user(session: Session, username: str, password: str, role: Role) -> User:
    if not username or not password:
        raise ValueError("Username and password are required")
    user = User(username=username.strip(), password_hash=hash_password(password), role=role.value)
    repository.add(session, user)
    repository.flush(session)
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
    user = repository.user_by_name(session, normalized_username)
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
    repository.add(
        session,
        AuthSession(
            token_hash=_token_hash(session_token),
            user_id=user.id,
            csrf_token_hash=_token_hash(csrf_token),
            last_seen_at=current,
            expires_at=current + SESSION_ABSOLUTE_TIMEOUT,
        ),
    )
    repository.flush(session)
    return session_token, csrf_token


def resolve_session(
    session: Session, session_token: str, now: datetime | None = None
) -> tuple[User, AuthSession] | None:
    current = now or utc_now()
    auth_session = repository.auth_session(session, _token_hash(session_token))
    if auth_session is None or auth_session.revoked_at is not None:
        return None
    idle_expired = _as_utc(auth_session.last_seen_at) + SESSION_IDLE_TIMEOUT <= current
    if _as_utc(auth_session.expires_at) <= current or idle_expired:
        auth_session.revoked_at = current
        return None
    user = repository.get_user(session, auth_session.user_id)
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
    sessions = repository.active_sessions_for_update(session, user_id)
    for auth_session in sessions:
        auth_session.revoked_at = now

    reset_tokens = repository.unused_resets_for_update(session, user_id)
    for reset_token in reset_tokens:
        reset_token.used_at = now


def issue_admin_reset(
    session: Session, admin: User, target: User, now: datetime | None = None
) -> str:
    require_role(admin, Role.ADMIN)
    current = now or utc_now()
    token = secrets.token_urlsafe(32)
    repository.add(
        session,
        PasswordResetToken(
            token_hash=_token_hash(token),
            user_id=target.id,
            expires_at=current + RESET_TOKEN_TIMEOUT,
        ),
    )
    repository.add(
        session,
        AuditLog(
            event_type="PASSWORD_RESET_ISSUED",
            actor=str(admin.id),
            entity_type="User",
            entity_id=str(target.id),
        ),
    )
    repository.flush(session)
    return token


def consume_reset(
    session: Session, token: str, new_password: str, now: datetime | None = None
) -> User:
    current = now or utc_now()
    reset = repository.reset_token_for_update(session, _token_hash(token))
    if reset is None or reset.used_at is not None or _as_utc(reset.expires_at) <= current:
        raise ValueError("Reset token is invalid or expired")
    user = repository.get_user(session, reset.user_id, lock=True)
    if user is None or not user.is_active:
        raise ValueError("Reset target is unavailable")
    user.password_hash = hash_password(new_password)
    reset.used_at = current
    _revoke_user_access(session, user.id, current)
    repository.add(
        session,
        AuditLog(
            event_type="PASSWORD_RESET_COMPLETED",
            entity_type="User",
            entity_id=str(user.id),
        ),
    )
    return user


def recover_admin(session: Session, username: str, new_password: str) -> User:
    user = repository.user_by_name(session, username.strip(), lock=True)
    if user is None or user.role != Role.ADMIN.value or not user.is_active:
        raise ValueError("Admin recovery target is unavailable")
    user.password_hash = hash_password(new_password)
    current = utc_now()
    _revoke_user_access(session, user.id, current)
    repository.add(
        session,
        AuditLog(
            event_type="ADMIN_RECOVERY_COMPLETED",
            entity_type="User",
            entity_id=str(user.id),
        ),
    )
    login_throttle.success(user.username)
    return user


def login_and_create_session(
    session: Session, username: str, password: str, client_ip: str | None
) -> tuple[User, str, str] | None:
    user = authenticate(session, username, password, client_ip=client_ip)
    if user is None:
        repository.commit(session)
        return None
    session_token, csrf_token = create_session(session, user)
    repository.commit(session)
    return user, session_token, csrf_token


def resolve_request_session(session: Session, token: str) -> tuple[User, AuthSession] | None:
    resolved = resolve_session(session, token)
    repository.commit_if_dirty(session)
    return resolved


def logout_session(session: Session, auth_session: AuthSession) -> None:
    revoke_session(session, auth_session)
    repository.commit(session)


def request_admin_reset(session: Session, admin: User, username: str) -> str:
    target = repository.user_by_name(session, username.strip())
    if target is None:
        raise NotFoundError("User not found")
    token = issue_admin_reset(session, admin, target)
    repository.commit(session)
    return token


def reset_password(session: Session, token: str, new_password: str) -> None:
    consume_reset(session, token, new_password)
    repository.commit(session)


def list_users(session: Session) -> list[dict[str, str | int]]:
    return [
        {"id": user.id, "username": user.username, "role": user.role}
        for user in repository.list_users(session)
    ]


def bootstrap_admin_user(session: Session, username: str, password: str) -> None:
    if repository.first_user(session) is not None:
        raise ConflictError("An admin or user already exists")
    create_user(session, username, password, Role.ADMIN)
