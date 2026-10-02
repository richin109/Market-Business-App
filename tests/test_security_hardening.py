from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from mbs.auth import Role, create_session, create_user
from mbs.db import get_session
from mbs.main import app
from tests.database import postgres_test_url


def _database(path: Path) -> Engine:
    engine = create_engine(postgres_test_url(path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(path).replace("%", "%%"))
    command.upgrade(config, "head")
    return engine


def test_every_response_carries_security_headers() -> None:
    response = TestClient(app).get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["referrer-policy"] == "same-origin"
    assert "frame-ancestors 'self'" in response.headers["content-security-policy"]


def test_login_rejects_oversized_credentials_before_password_hashing() -> None:
    client = TestClient(app)

    oversized = client.post(
        "/api/v1/auth/login", json={"username": "manager", "password": "x" * 1025}
    )
    empty = client.post("/api/v1/auth/login", json={"username": "", "password": "x"})

    assert oversized.status_code == 422
    assert empty.status_code == 422


def test_admin_routes_and_html_pages_enforce_roles_and_no_store(tmp_path: Path) -> None:
    engine = _database(tmp_path / "security-hardening.db")
    with Session(engine) as session:
        admin = create_user(session, "sec-admin", "synthetic password", Role.ADMIN)
        manager = create_user(session, "sec-manager", "synthetic password", Role.MANAGER)
        admin_token, admin_csrf = create_session(session, admin)
        manager_token, manager_csrf = create_session(session, manager)
        session.commit()

    def override_session() -> Iterator[Session]:
        with Session(engine) as active_session:
            yield active_session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        manager_headers = {"Cookie": f"mbs_session={manager_token}", "X-CSRF-Token": manager_csrf}
        admin_headers = {"Cookie": f"mbs_session={admin_token}", "X-CSRF-Token": admin_csrf}

        assert client.get("/api/v1/auth/admin/users").status_code == 401
        assert client.get("/api/v1/auth/admin/users", headers=manager_headers).status_code == 403
        assert client.get("/api/v1/auth/admin/users", headers=admin_headers).status_code == 200
        assert (
            client.get("/api/v1/receipt-correction-holds", headers=manager_headers).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/auth/admin/reset",
                json={"username": "sec-manager"},
                headers=manager_headers,
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/receipt-correction-holds/1/resolve",
                json={"action": "KEEP", "reason": "synthetic"},
                headers=manager_headers,
            ).status_code
            == 403
        )

        page = client.get("/api/v1/items/page", headers=manager_headers)
        assert page.status_code == 200
        assert page.headers["cache-control"] == "no-store"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
