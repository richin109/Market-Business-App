from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from mbs.auth import (
    AccountLocked,
    LoginRateLimited,
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
from mbs.models import AuthSession


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    database_path = tmp_path / "auth.db"
    engine = create_engine(f"sqlite:///{database_path}")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
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


def test_sessions_expire_after_idle_timeout(session: Session) -> None:
    user = create_user(session, "viewer", "password", Role.VIEWER)
    created_at = datetime(2026, 9, 30, tzinfo=UTC)
    session_token, _ = create_session(session, user, created_at)
    session.commit()

    assert (
        resolve_session(session, session_token, created_at + timedelta(hours=2, seconds=1))
        is None
    )
    auth_session = session.scalar(select(AuthSession).where(AuthSession.token_hash.is_not(None)))
    assert auth_session is not None
    assert auth_session.revoked_at is not None


def test_admin_reset_is_one_time_and_role_protected(session: Session) -> None:
    admin = create_user(session, "admin", "admin password", Role.ADMIN)
    manager = create_user(session, "manager", "old password", Role.MANAGER)
    viewer = create_user(session, "viewer", "viewer password", Role.VIEWER)
    session.commit()

    token = issue_admin_reset(session, admin, manager)
    session.commit()
    consume_reset(session, token, "new password")
    session.commit()
    assert authenticate(session, "manager", "new password") is not None
    with pytest.raises(ValueError, match="invalid or expired"):
        consume_reset(session, token, "another password")
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
    session.commit()

    recover_admin(session, admin.username, "new password")
    session.commit()

    assert authenticate(session, admin.username, "old password") is None
    assert authenticate(session, admin.username, "new password") is not None


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
        csrf_token = login_response.json()["csrf_token"]
        assert session_token is not None

        auth_headers = {"Cookie": f"mbs_session={session_token}"}
        assert client.get("/api/v1/auth/me", headers=auth_headers).json()["role"] == "MANAGER"
        assert client.get("/api/v1/auth/admin/users", headers=auth_headers).status_code == 403
        assert client.post("/api/v1/auth/logout", headers=auth_headers).status_code == 403
        assert (
            client.post(
                "/api/v1/auth/logout",
                headers={**auth_headers, "X-CSRF-Token": csrf_token},
            ).status_code
            == 200
        )
        assert client.get("/api/v1/auth/me", headers=auth_headers).status_code == 401
    finally:
        app.dependency_overrides.clear()
