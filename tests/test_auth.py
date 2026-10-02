from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session, sessionmaker

import mbs.auth as auth_module
import mbs.main as main_module
from mbs.auth import (
    AccountLocked,
    LoginRateLimited,
    LoginThrottle,
    Role,
    authenticate,
    consume_reset,
    create_session,
    create_user,
    issue_admin_reset,
    recover_admin,
    require_role,
    resolve_session,
    verify_csrf,
)
from mbs.db import get_session
from mbs.main import app
from mbs.models import AuditLog, AuthSession
from tests.database import postgres_test_url


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    database_path = tmp_path / "auth.db"
    engine = create_engine(postgres_test_url(database_path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(database_path).replace("%", "%%"))
    command.upgrade(config, "head")
    with Session(engine) as database_session:
        yield database_session


def test_authentication_uses_argon2_and_revocable_opaque_session(session: Session) -> None:
    user = create_user(session, "manager", "correct horse", Role.MANAGER)
    session.commit()

    assert authenticate(session, "manager", "correct horse") is not None
    assert authenticate(session, "manager", "wrong") is None
    session_token, csrf_token = create_session(session, user, datetime.now(UTC))
    session.commit()

    resolved = resolve_session(session, session_token)
    assert resolved is not None
    resolved_user, auth_session = resolved
    assert resolved_user.id == user.id
    assert verify_csrf(auth_session, csrf_token)
    assert not verify_csrf(auth_session, "wrong")

    auth_session.revoked_at = datetime.now(UTC)
    session.commit()
    assert resolve_session(session, session_token) is None


def test_password_hashing_rejects_passwords_below_minimum_length() -> None:
    with pytest.raises(ValueError, match="at least 12 characters"):
        auth_module.hash_password("short-pass")


def test_password_hashing_accepts_minimum_length_password() -> None:
    password_hash = auth_module.hash_password("twelve_chars")

    assert auth_module.verify_password("twelve_chars", password_hash)


def test_auth_sessions_have_user_lookup_index(session: Session) -> None:
    indexes = {
        index["name"] for index in inspect(session.get_bind()).get_indexes("tbl_auth_sessions")
    }

    assert "ix_tbl_auth_sessions_user_id" in indexes


def test_sessions_expire_after_idle_timeout(session: Session) -> None:
    user = create_user(session, "viewer", "synthetic password", Role.VIEWER)
    created_at = datetime(2026, 9, 30, tzinfo=UTC)
    session_token, _ = create_session(session, user, created_at)
    session.commit()

    assert (
        resolve_session(session, session_token, created_at + timedelta(hours=2, seconds=1)) is None
    )
    auth_session = session.scalar(select(AuthSession).where(AuthSession.token_hash.is_not(None)))
    assert auth_session is not None
    assert auth_session.revoked_at is not None


def test_absolute_session_timeout_is_not_extended_by_activity(session: Session) -> None:
    user = create_user(session, "absolute-viewer", "long enough password", Role.VIEWER)
    created_at = datetime(2026, 9, 30, tzinfo=UTC)
    session_token, _ = create_session(session, user, created_at)
    session.commit()

    for elapsed_hours in range(1, 12):
        assert (
            resolve_session(session, session_token, created_at + timedelta(hours=elapsed_hours))
            is not None
        )
    assert (
        resolve_session(session, session_token, created_at + timedelta(hours=11, minutes=59))
        is not None
    )
    assert (
        resolve_session(session, session_token, created_at + timedelta(hours=12, seconds=1)) is None
    )


def test_admin_reset_is_one_time_and_role_protected(session: Session) -> None:
    admin = create_user(session, "admin", "admin password", Role.ADMIN)
    manager = create_user(session, "manager", "old password", Role.MANAGER)
    viewer = create_user(session, "viewer", "viewer password", Role.VIEWER)
    session.commit()

    manager_session_token, _ = create_session(session, manager, datetime(2026, 9, 30, tzinfo=UTC))
    token = issue_admin_reset(session, admin, manager)
    stale_token = issue_admin_reset(session, admin, manager)
    session.commit()
    consume_reset(session, token, "new password")
    session.commit()
    assert resolve_session(session, manager_session_token) is None
    assert authenticate(session, "manager", "new password") is not None
    with pytest.raises(ValueError, match="invalid or expired"):
        consume_reset(session, token, "another password")
    with pytest.raises(ValueError, match="invalid or expired"):
        consume_reset(session, stale_token, "another password")
    with pytest.raises(PermissionError):
        issue_admin_reset(session, viewer, manager)
    with pytest.raises(PermissionError):
        require_role(viewer, Role.MANAGER)


def test_login_throttle_limits_ip_and_locks_after_ten_account_failures(session: Session) -> None:
    user = create_user(session, "throttled", "correct password", Role.VIEWER)
    session.commit()
    now = datetime(2026, 9, 30, tzinfo=UTC)

    for _ in range(5):
        assert authenticate(session, user.username, "wrong", "198.51.100.10", now) is None
    with pytest.raises(LoginRateLimited):
        authenticate(session, user.username, "wrong", "198.51.100.10", now)

    for attempt in range(4):
        assert (
            authenticate(
                session,
                user.username,
                "wrong",
                f"198.51.100.{20 + attempt}",
                now,
            )
            is None
        )
    assert authenticate(session, user.username, "wrong", "198.51.100.30", now) is None
    with pytest.raises(AccountLocked):
        authenticate(session, user.username, "correct password", "198.51.100.31", now)


def test_local_admin_recovery_replaces_password(session: Session) -> None:
    admin = create_user(session, "recoverable", "old password", Role.ADMIN)
    session_token, _ = create_session(session, admin)
    session.commit()

    recover_admin(session, admin.username, "new password")
    session.commit()

    assert resolve_session(session, session_token) is None
    assert authenticate(session, admin.username, "old password") is None
    assert authenticate(session, admin.username, "new password") is not None


def test_unknown_username_still_verifies_against_dummy_hash(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_module, "login_throttle", LoginThrottle())
    verified_hashes: list[str] = []

    def record_verification(password: str, password_hash: str) -> bool:
        verified_hashes.append(password_hash)
        return False

    monkeypatch.setattr(auth_module, "verify_password", record_verification)

    assert authenticate(session, "missing-user", "candidate password") is None
    assert verified_hashes == [auth_module._DUMMY_PASSWORD_HASH]


def test_login_throttle_bounds_tracked_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "MAX_TRACKED_THROTTLE_KEYS", 3)
    throttle = LoginThrottle()
    now = datetime(2026, 9, 30, tzinfo=UTC)

    for attempt in range(5):
        throttle.failure(f"user-{attempt}", f"ip-{attempt}", now)

    assert len(throttle._ip_failures) == 3
    assert len(throttle._account_failures) == 3


def test_login_throttle_returns_http_statuses_and_audits_thresholds(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_module, "login_throttle", LoginThrottle())
    ip_limited = create_user(session, "ip-limited", "correct password", Role.VIEWER)
    locked = create_user(session, "account-locked", "correct password", Role.VIEWER)
    session.commit()

    def override_session() -> Iterator[Session]:
        yield session

    monkeypatch.setattr(
        main_module,
        "SessionLocal",
        sessionmaker(bind=session.get_bind(), expire_on_commit=False),
    )
    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app, client=("203.0.113.10", 1234)) as client:
            for _ in range(5):
                response = client.post(
                    "/api/v1/auth/login",
                    json={"username": ip_limited.username, "password": "wrong password"},
                )
                assert response.status_code == 401
            response = client.post(
                "/api/v1/auth/login",
                json={"username": ip_limited.username, "password": "wrong password"},
            )
            assert response.status_code == 429

        for attempt in range(10):
            authenticate(
                session,
                locked.username,
                "wrong password",
                f"198.51.100.{attempt + 1}",
            )
        with TestClient(app, client=("198.51.100.50", 1234)) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"username": locked.username, "password": "correct password"},
            )
            assert response.status_code == 423
    finally:
        app.dependency_overrides.clear()

    event_types = set(session.scalars(select(AuditLog.event_type)))
    assert "LOGIN_IP_THROTTLE_THRESHOLD" in event_types
    assert "LOGIN_ACCOUNT_LOCK_STARTED" in event_types


def test_http_auth_enforces_cookie_flags_csrf_and_admin_role(session: Session) -> None:
    manager = create_user(session, "manager", "manager password", Role.MANAGER)
    session.commit()

    def override_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        login_response = client.post(
            "/api/v1/auth/login",
            json={"username": manager.username, "password": "manager password"},
        )
        assert login_response.status_code == 200
        cookie_header = login_response.headers["set-cookie"].lower()
        assert "secure" in cookie_header
        assert "httponly" in cookie_header
        assert "samesite=lax" in cookie_header
        session_token = login_response.cookies.get("mbs_session")
        csrf_cookie = login_response.cookies.get("mbs_csrf")
        csrf_token = login_response.json()["csrf_token"]
        assert session_token is not None
        assert csrf_cookie == csrf_token
        csrf_cookie_header = next(
            value.lower()
            for value in login_response.headers.get_list("set-cookie")
            if value.startswith("mbs_csrf=")
        )
        assert "secure" in csrf_cookie_header
        assert "httponly" not in csrf_cookie_header
        assert "samesite=strict" in csrf_cookie_header

        auth_headers = {"Cookie": f"mbs_session={session_token}"}
        assert client.get("/api/v1/auth/me", headers=auth_headers).json()["role"] == "MANAGER"
        assert client.get("/api/v1/auth/admin/users", headers=auth_headers).status_code == 403
        assert client.post("/api/v1/auth/logout", headers=auth_headers).status_code == 403
        logout_response = client.post(
            "/api/v1/auth/logout",
            headers={**auth_headers, "X-CSRF-Token": csrf_token},
        )
        assert logout_response.status_code == 200
        csrf_deletion = next(
            value.lower()
            for value in logout_response.headers.get_list("set-cookie")
            if value.startswith("mbs_csrf=")
        )
        assert "max-age=0" in csrf_deletion
        assert client.get("/api/v1/auth/me", headers=auth_headers).status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_read_only_requests_persist_session_activity_and_expiry(session: Session) -> None:
    user = create_user(session, "reader", "synthetic password", Role.VIEWER)
    now = datetime.now(UTC)
    active_token, _ = create_session(session, user, now - timedelta(minutes=90))
    stale_token, _ = create_session(session, user, now - timedelta(hours=3))
    session.commit()
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)

    def override_session() -> Iterator[Session]:
        with factory() as active_session:
            yield active_session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        active = client.get("/api/v1/auth/me", headers={"Cookie": f"mbs_session={active_token}"})
        stale = client.get("/api/v1/auth/me", headers={"Cookie": f"mbs_session={stale_token}"})
    finally:
        app.dependency_overrides.clear()

    assert active.status_code == 200
    assert stale.status_code == 401
    with factory() as check:
        rows = {row.token_hash: row for row in check.scalars(select(AuthSession))}
    touched = rows[auth_module._token_hash(active_token)]
    revoked = rows[auth_module._token_hash(stale_token)]
    assert auth_module._as_utc(touched.last_seen_at) >= now - timedelta(minutes=1)
    assert revoked.revoked_at is not None
