from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from playwright.sync_api import Page
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from mbs.auth import Role, create_session, create_user
from mbs.db import get_session
from mbs.main import app
from mbs.models import AuditLog, Receipt, ReceiptItem, StoreItem
from mbs.receipts.ocr import normalize_receipt
from mbs.receipts.persistence import persist_extracted_receipt
from tests.database import postgres_test_url


def _database(path: Path) -> tuple[Any, sessionmaker[Session]]:
    engine = create_engine(postgres_test_url(path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(path).replace("%", "%%"))
    command.upgrade(config, "head")
    return engine, sessionmaker(engine, expire_on_commit=False)


def _create_store(session: Session) -> str:
    receipt = persist_extracted_receipt(
        session,
        normalize_receipt(
            {
                "receipt": {
                    "store": "Synthetic Manual Market",
                    "date": "2026-09-30",
                    "time": "10:00:00",
                    "transaction_number": "STORE-SEED-1",
                    "total": "0.00",
                },
                "items": [],
            }
        ),
    )
    return receipt.store_id


def _override(session_factory: sessionmaker[Session]) -> Any:
    def override_session() -> Any:
        with session_factory() as session:
            yield session

    return override_session


def test_manual_receipt_uses_canonical_store_and_manual_item_identity_idempotently(
    tmp_path: Path,
) -> None:
    engine, session_factory = _database(tmp_path / "manual-receipt-api.db")
    with session_factory.begin() as session:
        store_id = _create_store(session)
        persist_extracted_receipt(
            session,
            normalize_receipt(
                {
                    "receipt": {
                        "store": "Synthetic Manual Market",
                        "date": "2026-09-29",
                        "time": "09:00:00",
                        "transaction_number": "OCR-SKU-SEED-1",
                        "total": "1.00",
                    },
                    "items": [
                        {
                            "description": "Milk",
                            "line_total": "1.00",
                            "store_product_id": "SKU-OCR-FIRST-1",
                        }
                    ],
                }
            ),
        )
        manager = create_user(session, "manual-entry-manager", "synthetic password", Role.MANAGER)
        viewer = create_user(session, "manual-entry-viewer", "synthetic password", Role.VIEWER)
        manager_token, manager_csrf = create_session(session, manager)
        viewer_token, viewer_csrf = create_session(session, viewer)
        manager_id = manager.id

    app.dependency_overrides[get_session] = _override(session_factory)
    try:
        client = TestClient(app)
        path = "/api/v1/receipts/manual"
        payload = {
            "source_event_id": "manual-event-001",
            "store_id": store_id,
            "receipt_date": "2026-09-30",
            "vendor_reference": None,
            "receipt_time": None,
            "subtotal": "2.00",
            "tax": "0.00",
            "total": "2.00",
            "payment_method": "CASH",
            "items": [
                {
                    "description": "Milk",
                    "store_product_id": None,
                    "upc": None,
                    "quantity": "1",
                    "unit_price": "2.00",
                    "line_total": "2.00",
                    "category": "Dairy",
                    "business_disposition": "ORDINARY_BUSINESS_PURCHASE",
                    "disposition_subtype": "DIRECT_EXPENSE",
                },
                {
                    "description": "User-entered product number",
                    "store_product_id": "SKU-OCR-FIRST-1",
                    "upc": None,
                    "quantity": None,
                    "unit_price": None,
                    "line_total": "0.00",
                    "category": "Other",
                    "business_disposition": "PERSONAL_NON_BUSINESS",
                    "disposition_subtype": "NONE",
                },
            ],
        }
        no_csrf = client.post(
            path,
            json=payload,
            headers={"Cookie": f"mbs_session={manager_token}"},
        )
        viewer_response = client.post(
            path,
            json=payload,
            headers={
                "Cookie": f"mbs_session={viewer_token}",
                "X-CSRF-Token": viewer_csrf,
            },
        )
        headers = {
            "Cookie": f"mbs_session={manager_token}",
            "X-CSRF-Token": manager_csrf,
        }
        created = client.post(path, json=payload, headers=headers)
        retried = client.post(path, json=payload, headers=headers)
        changed_retry = client.post(
            path,
            json={**payload, "total": "3.00"},
            headers=headers,
        )
        details = client.get(
            f"/api/v1/receipts/{created.json()['receipt_pk']}",
            headers={"Cookie": f"mbs_session={manager_token}"},
        )
        unknown_store = client.post(
            path,
            json={
                **payload,
                "store_id": "not-a-canonical-store",
                "source_event_id": "manual-event-unknown",
            },
            headers=headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert no_csrf.status_code == 403
    assert viewer_response.status_code == 403
    assert created.status_code == 201
    assert retried.status_code == 201
    assert retried.json()["receipt_pk"] == created.json()["receipt_pk"]
    assert created.json()["items"][0]["identifier_source"] == "MANUAL"
    assert created.json()["items"][0]["store_product_id"].startswith("MANUAL:")
    assert created.json()["items"][1]["identifier_source"] == "USER_ENTERED"
    assert created.json()["items"][1]["store_product_id"] == "SKU-OCR-FIRST-1"
    assert changed_retry.status_code == 422
    assert "reused with another request" in changed_retry.json()["detail"]
    assert unknown_store.status_code == 422
    assert "active canonical store" in unknown_store.json()["detail"]
    assert details.status_code == 200
    assert details.json()["source_type"] == "MANUAL"
    assert details.json()["items"][0]["identifier_source"] == "MANUAL"
    assert details.json()["items"][0]["store_product_id"].startswith("MANUAL:")
    assert details.json()["items"][1]["identifier_source"] == "USER_ENTERED"
    with session_factory() as session:
        receipt = session.get(Receipt, created.json()["receipt_pk"])
        line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == created.json()["receipt_pk"])
        )
        assert receipt is not None and receipt.source_type == "MANUAL"
        assert receipt.transaction_number == f"MANUAL:{receipt.receipt_pk}"
        assert receipt.raw_ocr_document == {"source_type": "MANUAL"}
        assert line is not None and line.raw_ocr_item is None
        assert line.store_item_id is not None and line.item_id is not None
        store_item = session.get(StoreItem, line.store_item_id)
        assert store_item is not None
        assert store_item.store_product_id.startswith("MANUAL:")
        assert store_item.identifier_source == "MANUAL"
        assert store_item.mapping_confirmed is True
        assert (
            session.scalar(
                select(AuditLog).where(
                    AuditLog.event_type == "MANUAL_STORE_PRODUCT_ID_ASSIGNED",
                    AuditLog.actor == str(manager_id),
                )
            )
            is not None
        )
        manual_audit = session.scalar(
            select(AuditLog).where(
                AuditLog.event_type == "MANUAL_RECEIPT_CREATED",
                AuditLog.entity_id == receipt.receipt_pk,
            )
        )
        assert manual_audit is not None
        assert manual_audit.details is not None
        audit_fields = json.loads(manual_audit.details)
        assert audit_fields["receipt_date"] == "2026-09-30"
        assert audit_fields["items"][0]["description"] == "Milk"
        assert audit_fields["items"][0]["store_product_id"].startswith("MANUAL:")
        assert audit_fields["items"][0]["identifier_source"] == "MANUAL"
        user_entered_item = session.scalar(
            select(StoreItem).where(StoreItem.store_product_id == "SKU-OCR-FIRST-1")
        )
        assert user_entered_item is not None
        assert user_entered_item.identifier_source == "MERCHANT"
    engine.dispose()

    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url", postgres_test_url(tmp_path / "manual-receipt-api.db").replace("%", "%%")
    )

    with pytest.raises(RuntimeError, match="manual receipt idempotency"):
        command.downgrade(config, "0015_item_mapping_admin")


def test_manual_receipt_form_is_operable_on_desktop_and_mobile(
    tmp_path: Path,
    page: Page,
) -> None:
    engine, session_factory = _database(tmp_path / "manual-receipt-page.db")
    with session_factory.begin() as session:
        store_id = _create_store(session)
        manager = create_user(session, "manual-page-manager", "synthetic password", Role.MANAGER)
        token, _ = create_session(session, manager)

    app.dependency_overrides[get_session] = _override(session_factory)
    try:
        response = TestClient(app).get(
            "/api/v1/receipts/manual/page",
            headers={"Cookie": f"mbs_session={token}"},
        )
        assert response.status_code == 200
        requests: list[dict[str, Any]] = []

        def route_manual_request(route: Any) -> None:
            request = route.request
            requests.append(
                {
                    "headers": request.headers,
                    "body": request.post_data_json,
                }
            )
            route.fulfill(
                status=201,
                content_type="application/json",
                body=(
                    '{"receipt_pk":"manual-pk","receipt_id":"MANUAL:manual-pk",'
                    '"source_type":"MANUAL","item_count":1,"items":[{"description":"Milk",'
                    '"store_product_id":"MANUAL:synthetic-id","identifier_source":"MANUAL"}]}'
                ),
            )

        page.context.add_cookies(
            [{"name": "mbs_csrf", "value": "manual-page-csrf", "url": "http://testserver"}]
        )
        page.route("**/api/v1/receipts/manual", route_manual_request)
        page.route("http://testserver/", lambda route: route.fulfill(body=response.text))
        browser_errors: list[str] = []
        page.on("pageerror", lambda error: browser_errors.append(str(error)))
        page.goto("http://testserver/")
        page.set_content(response.text)
        assert page.locator("#line-list [data-line]").count() == 1, browser_errors
        page.locator("select[name='store_id']").select_option(store_id)
        page.locator("input[name='total']").fill("2.00")
        page.locator("[data-line] input[name='description']").fill("Milk")
        page.locator("[data-line] input[name='line_total']").fill("2.00")
        page.locator("[data-line] select[name='business_disposition']").select_option(
            "ORDINARY_BUSINESS_PURCHASE"
        )
        page.locator("[data-line] select[name='disposition_subtype']").select_option(
            "DIRECT_EXPENSE"
        )
        page.locator("button[type='submit']").click()
        page.wait_for_function("document.querySelector('.message').textContent.includes('created')")
        assert (
            "Manual identifier MANUAL:synthetic-id"
            in page.locator(".created-identifiers").inner_text()
        )
        assert page.get_by_role("link", name="Review receipt").get_attribute("href") == (
            "/api/v1/receipts/manual-pk/review"
        )
        assert requests[0]["headers"]["x-csrf-token"] == "manual-page-csrf"
        assert requests[0]["body"]["store_id"] == store_id
        assert requests[0]["body"]["source_event_id"]
        assert requests[0]["body"]["items"][0]["disposition_subtype"] == "DIRECT_EXPENSE"
        for width in (1280, 390):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
