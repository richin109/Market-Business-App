from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from playwright.sync_api import Page
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from mbs.auth import Role, create_session, create_user
from mbs.db import get_session
from mbs.items import register_store_item
from mbs.main import app
from mbs.models import AuditLog, Store, StoreItem
from tests.database import postgres_test_url


def test_manager_can_review_correct_and_clear_remembered_rules_with_audit(tmp_path: Path) -> None:
    path = tmp_path / "remembered-rules.db"
    engine = create_engine(postgres_test_url(path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(path).replace("%", "%%"))
    command.upgrade(config, "head")
    with Session(engine) as session:
        manager = create_user(session, "rule-api-manager", "synthetic password", Role.MANAGER)
        viewer = create_user(session, "rule-api-viewer", "synthetic password", Role.VIEWER)
        manager_token, manager_csrf = create_session(session, manager)
        viewer_token, viewer_csrf = create_session(session, viewer)
        store = Store(display_name="Synthetic Rule API Store")
        session.add(store)
        session.flush()
        store_item = register_store_item(
            session, store.store_id, "RULE-API-1", "Synthetic cups", actor_id=manager.id
        )
        store_item_id = store_item.store_item_id
        session.commit()

    def override_session() -> Iterator[Session]:
        with Session(engine) as active_session:
            yield active_session

    app.dependency_overrides[get_session] = override_session
    manager_headers = {"Cookie": f"mbs_session={manager_token}", "X-CSRF-Token": manager_csrf}
    viewer_headers = {"Cookie": f"mbs_session={viewer_token}", "X-CSRF-Token": viewer_csrf}
    url = f"/api/v1/remembered-rules/{store_item_id}"
    stocked = {
        "disposition": "ORDINARY_BUSINESS_PURCHASE",
        "disposition_subtype": "STOCKED_SUPPLY",
        "reason": "Cups are stocked supplies",
    }
    try:
        client = TestClient(app)
        assert client.get("/api/v1/remembered-rules", headers=manager_headers).json() == []
        assert client.get("/api/v1/remembered-rules", headers=viewer_headers).status_code == 403
        assert client.put(url, json=stocked, headers=viewer_headers).status_code == 403
        assert (
            client.put(
                url, json=stocked, headers={"Cookie": f"mbs_session={manager_token}"}
            ).status_code
            == 403
        )
        assert (
            client.put(url, json={**stocked, "reason": ""}, headers=manager_headers).status_code
            == 422
        )
        for bad in (
            {"disposition": "RECIPE_INGREDIENT", "disposition_subtype": "STOCKED_SUPPLY"},
            {"disposition": "ORDINARY_BUSINESS_PURCHASE", "disposition_subtype": "NONE"},
            {"disposition": "UNCLASSIFIED", "disposition_subtype": "NONE"},
        ):
            rejected = client.put(url, json={**bad, "reason": "synthetic"}, headers=manager_headers)
            assert rejected.status_code == 400
        missing = client.put(
            "/api/v1/remembered-rules/unknown", json=stocked, headers=manager_headers
        )
        assert missing.status_code == 404

        assert client.put(url, json=stocked, headers=manager_headers).json()["changed"] is True
        assert client.put(url, json=stocked, headers=manager_headers).json()["changed"] is False
        listed = client.get("/api/v1/remembered-rules", headers=manager_headers).json()
        assert [rule["disposition_subtype"] for rule in listed] == ["STOCKED_SUPPLY"]

        clear_body = {"reason": "Bought for personal use"}
        cleared = client.request("DELETE", url, json=clear_body, headers=manager_headers)
        assert cleared.json()["changed"] is True
        again = client.request("DELETE", url, json=clear_body, headers=manager_headers)
        assert again.json()["changed"] is False

        with Session(engine) as session:
            stored = session.get(StoreItem, store_item_id)
            assert stored is not None and stored.last_disposition is None
            events = session.scalars(
                select(AuditLog.event_type).where(AuditLog.entity_id == store_item_id)
            ).all()
            assert "REMEMBERED_RULE_CORRECTED" in events and "REMEMBERED_RULE_CLEARED" in events
            assert (
                session.scalar(
                    select(func.count(AuditLog.id)).where(
                        AuditLog.event_type == "REMEMBERED_RULE_CORRECTED"
                    )
                )
                == 1
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_remembered_rules_page_saves_and_clears_rules_on_desktop_and_mobile(
    tmp_path: Path, page: Page
) -> None:
    path = tmp_path / "remembered-rules-page.db"
    engine = create_engine(postgres_test_url(path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(path).replace("%", "%%"))
    command.upgrade(config, "head")
    with Session(engine) as session:
        manager = create_user(session, "rule-page-manager", "synthetic password", Role.MANAGER)
        manager_token, _ = create_session(session, manager)
        store = Store(display_name="Synthetic Rule Page Store")
        session.add(store)
        session.flush()
        store_item = register_store_item(
            session, store.store_id, "RULE-PAGE-1", "Synthetic ice", actor_id=manager.id
        )
        store_item.last_disposition = "ORDINARY_BUSINESS_PURCHASE"
        store_item.last_disposition_subtype = "DIRECT_EXPENSE"
        store_item_id = store_item.store_item_id
        session.commit()

    def override_session() -> Iterator[Session]:
        with Session(engine) as active_session:
            yield active_session

    app.dependency_overrides[get_session] = override_session
    try:
        html = TestClient(app).get(
            "/api/v1/remembered-rules/page", headers={"Cookie": f"mbs_session={manager_token}"}
        )
        assert html.status_code == 200 and "Synthetic ice" in html.text
        assert "Unclassified" not in html.text
        requests: list[dict[str, Any]] = []

        def rule_route(route: Any) -> None:
            requests.append(
                {
                    "method": route.request.method,
                    "headers": route.request.headers,
                    "body": route.request.post_data_json,
                    "url": route.request.url,
                }
            )
            route.fulfill(
                status=200, content_type="application/json", body=json.dumps({"changed": True})
            )

        page.context.add_cookies(
            [{"name": "mbs_csrf", "value": "rules-page-csrf", "url": "http://testserver"}]
        )
        page.route("**/api/v1/remembered-rules/*", rule_route)
        page.route("http://testserver/", lambda route: route.fulfill(body=html.text))
        page.goto("http://testserver/")
        card = page.locator(".rule")
        disposition = card.locator("select[name='disposition']")
        subtype = card.locator("select[name='disposition_subtype']")
        assert subtype.input_value() == "DIRECT_EXPENSE"

        disposition.select_option("PERSONAL_NON_BUSINESS")
        assert subtype.is_disabled() and subtype.input_value() == "NONE"
        card.locator("input[name='reason']").fill("Ice was personal")
        card.get_by_role("button", name="Save rule").click()
        page.wait_for_function(
            "document.querySelector('.rule .message').textContent === 'Rule saved'"
        )
        assert requests[0]["method"] == "PUT"
        assert requests[0]["headers"]["x-csrf-token"] == "rules-page-csrf"
        assert requests[0]["body"] == {
            "disposition": "PERSONAL_NON_BUSINESS",
            "disposition_subtype": "NONE",
            "reason": "Ice was personal",
        }
        assert store_item_id in requests[0]["url"]

        for width in (1280, 390):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

        card.locator("input[name='reason']").fill("")
        card.get_by_role("button", name="Clear rule").click()
        assert card.locator(".message").inner_text() == "A reason is required"
        assert len(requests) == 1
        card.locator("input[name='reason']").fill("No longer applies")
        card.get_by_role("button", name="Clear rule").click()
        page.wait_for_function("document.querySelectorAll('.rule').length === 0")
        assert requests[1]["method"] == "DELETE"
        assert requests[1]["body"] == {"reason": "No longer applies"}
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
