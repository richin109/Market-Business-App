import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from playwright.sync_api import Page
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.orm import sessionmaker

from mbs.auth import Role, create_session, create_user
from mbs.db import get_session
from mbs.main import app
from mbs.models import (
    AuditLog,
    Receipt,
    ReceiptUpload,
    Store,
    StoreAliasKey,
    StoreAliasSpelling,
    StoreItem,
    StoreResolutionHold,
)
from mbs.receipts.ocr import normalize_receipt
from mbs.receipts.persistence import persist_extracted_receipt
from mbs.receipts.storage import LocalProtectedFileStore
from mbs.receipts.tasks import PersistedUploadProcessor
from mbs.stores import (
    STORE_ALIAS_NORMALIZATION_VERSION,
    add_store_alias,
    normalize_store_alias,
    resolve_store,
)
from tests.database import postgres_test_url


def _database(path: Path, revision: str = "head") -> tuple[Any, Any]:
    engine = create_engine(postgres_test_url(path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(path).replace("%", "%%"))
    command.upgrade(config, revision)
    return engine, sessionmaker(engine, expire_on_commit=False)


def _document(
    store: str | None,
    transaction_number: str,
    branch_number: str | None = None,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "date": "2026-09-30",
        "time": "14:05:06",
        "transaction_number": transaction_number,
        "total": "0.00",
    }
    if store is not None:
        receipt["store"] = store
    if branch_number is not None:
        receipt["branch_number"] = branch_number
    return {"receipt": receipt, "items": []}


def test_store_alias_normalization_is_exact_and_versioned() -> None:
    spellings = (
        "  BJ'S WHOLESALE CLUB #123  ",
        "bjs wholesale club store 123",
        "BJS WHOLESALE CLUB",
    )

    assert {
        normalize_store_alias(value, STORE_ALIAS_NORMALIZATION_VERSION) for value in spellings
    } == {"bjs wholesale club"}
    assert normalize_store_alias("Wal Mart", STORE_ALIAS_NORMALIZATION_VERSION) != (
        normalize_store_alias("Walmart", STORE_ALIAS_NORMALIZATION_VERSION)
    )
    with pytest.raises(ValueError, match="Unsupported store alias normalization version"):
        normalize_store_alias("Walmart", "future-normalization")


def test_imported_spellings_resolve_to_one_store_without_rewriting_receipt_text(
    tmp_path: Path,
) -> None:
    engine, session_factory = _database(tmp_path / "store-aliases.db")
    try:
        with session_factory.begin() as session:
            first = persist_extracted_receipt(
                session,
                normalize_receipt(_document("BJ'S WHOLESALE CLUB #123", "TC-101")),
            )
            second = persist_extracted_receipt(
                session,
                normalize_receipt(_document("bjs wholesale club", "TC-102")),
            )

            assert first.store_id == second.store_id
            assert first.store_alias_key == second.store_alias_key == "bjs wholesale club"
            assert first.store == "BJ'S WHOLESALE CLUB #123"
            assert first.receipt_id.startswith("BJ'S WHOLESALE CLUB #123|")
            assert session.scalar(select(func.count(Store.store_id))) == 1
            assert session.scalar(select(func.count(StoreAliasKey.normalized_key))) == 1
            assert session.scalar(select(func.count(StoreAliasSpelling.id))) == 2
    finally:
        engine.dispose()


def test_unreadable_store_is_persisted_as_review_hold(tmp_path: Path) -> None:
    engine, session_factory = _database(tmp_path / "unreadable-store.db")
    file_store = LocalProtectedFileStore(tmp_path / "files")
    source = b"synthetic source"
    source_sha256 = hashlib.sha256(source).hexdigest()
    file_key = file_store.save(source_sha256, source, "image/png")
    document = _document(None, "TC-103")
    try:
        with session_factory.begin() as session:
            session.add(
                ReceiptUpload(
                    source_sha256=source_sha256,
                    file_key=file_key,
                    media_type="image/png",
                    size_bytes=len(source),
                    processing_status="QUEUED",
                )
            )
            upload_pk = session.scalar(select(ReceiptUpload.upload_pk))

        class FixedEngine:
            def extract(self, source: bytes, media_type: str) -> dict[str, Any]:
                return document

        processor = PersistedUploadProcessor(session_factory, file_store, FixedEngine())
        assert processor.process(upload_pk) == "REVIEW"

        with session_factory() as session:
            upload = session.get(ReceiptUpload, upload_pk)
            hold = session.scalar(select(StoreResolutionHold))
            assert upload is not None and upload.processing_status == "REVIEW"
            assert hold is not None and "missing or unreadable" in hold.reason
            assert hold.raw_ocr_document == document
            assert session.scalar(select(func.count(Receipt.receipt_pk))) == 0
            assert (
                session.scalar(
                    select(AuditLog).where(AuditLog.event_type == "RECEIPT_STORE_RESOLUTION_HELD")
                )
                is not None
            )
    finally:
        engine.dispose()


def test_known_conflicting_branch_location_is_held(tmp_path: Path) -> None:
    engine, session_factory = _database(tmp_path / "conflicting-branch.db")
    file_store = LocalProtectedFileStore(tmp_path / "files")
    with session_factory.begin() as session:
        persist_extracted_receipt(
            session,
            normalize_receipt(_document("Synthetic Market", "TC-104", "BR-01")),
        )
    source = b"synthetic branch source"
    source_sha256 = hashlib.sha256(source).hexdigest()
    file_key = file_store.save(source_sha256, source, "image/png")
    document = _document("Synthetic Market", "TC-105", "BR-02")
    try:
        with session_factory.begin() as session:
            session.add(
                ReceiptUpload(
                    source_sha256=source_sha256,
                    file_key=file_key,
                    media_type="image/png",
                    size_bytes=len(source),
                    processing_status="QUEUED",
                )
            )
            upload_pk = session.scalar(select(ReceiptUpload.upload_pk))

        class FixedEngine:
            def extract(self, source: bytes, media_type: str) -> dict[str, Any]:
                return document

        processor = PersistedUploadProcessor(session_factory, file_store, FixedEngine())
        assert processor.process(upload_pk) == "REVIEW"

        with session_factory() as session:
            hold = session.scalar(select(StoreResolutionHold))
            assert hold is not None and "conflicting known location" in hold.reason
            assert session.scalar(select(func.count(Receipt.receipt_pk))) == 1
            assert session.scalar(select(func.count(Store.store_id))) == 1
    finally:
        engine.dispose()


def test_store_migration_refuses_existing_receipts_before_schema_changes(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "store-migration-guard.db"
    engine, _ = _database(database_path, "0012_settings_catalog")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(database_path).replace("%", "%%"))
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO tbl_receipts
                    (receipt_pk, receipt_id, store, receipt_date, receipt_time,
                     transaction_number, total, raw_ocr_document, receipt_document)
                    VALUES ('synthetic-pk', 'Synthetic|2026-09-30|14:05:06|TC-106',
                            'Synthetic', '2026-09-30', '14:05:06', 'TC-106', 0,
                            '{}', '{}')"""
                )
            )

        with pytest.raises(RuntimeError, match="tbl_receipts contains rows"):
            command.upgrade(config, "head")

        columns = {column["name"] for column in inspect(engine).get_columns("tbl_receipts")}
        assert "store_id" not in columns
        assert "tbl_stores" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_store_directory_is_manager_only_and_duplicate_names_require_confirmation(
    tmp_path: Path,
) -> None:
    engine, session_factory = _database(tmp_path / "store-directory.db")
    with session_factory.begin() as session:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        viewer = create_user(session, "viewer", "viewer password", Role.VIEWER)
        manager_token, manager_csrf = create_session(session, manager)
        viewer_token, _ = create_session(session, viewer)
        first = persist_extracted_receipt(
            session,
            normalize_receipt(_document("Market One", "TC-107")),
        )
        second = persist_extracted_receipt(
            session,
            normalize_receipt(_document("Market Two", "TC-108")),
        )

    def override_session() -> Any:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        manager_headers = {"Cookie": f"mbs_session={manager_token}"}
        viewer_headers = {"Cookie": f"mbs_session={viewer_token}"}
        listing = client.get("/api/v1/stores", headers=manager_headers)
        store_queries: list[str] = []

        def record_store_queries(
            connection: Any,
            cursor: Any,
            statement: str,
            parameters: Any,
            context: Any,
            executemany: bool,
        ) -> None:
            if any(table in statement for table in ("tbl_stores", "tbl_store_aliases")):
                store_queries.append(statement)

        event.listen(engine, "before_cursor_execute", record_store_queries)
        page = client.get("/api/v1/stores/page", headers=manager_headers)
        event.remove(engine, "before_cursor_execute", record_store_queries)
        denied = client.get("/api/v1/stores", headers=viewer_headers)
        duplicate = client.put(
            f"/api/v1/stores/{first.store_id}",
            json={"display_name": "Market Two"},
            headers={**manager_headers, "X-CSRF-Token": manager_csrf},
        )
        renamed = client.put(
            f"/api/v1/stores/{first.store_id}",
            json={"display_name": "Market Two", "confirm_duplicate_name": True},
            headers={**manager_headers, "X-CSRF-Token": manager_csrf},
        )
        deactivated = client.put(
            f"/api/v1/stores/{first.store_id}",
            json={"is_active": False},
            headers={**manager_headers, "X-CSRF-Token": manager_csrf},
        )
        alias = client.post(
            f"/api/v1/stores/{first.store_id}/aliases",
            json={"raw_alias": "Market One Store 001"},
            headers={**manager_headers, "X-CSRF-Token": manager_csrf},
        )
        repeated_alias = client.post(
            f"/api/v1/stores/{first.store_id}/aliases",
            json={"raw_alias": "Market One"},
            headers={**manager_headers, "X-CSRF-Token": manager_csrf},
        )
        conflicting_alias = client.post(
            f"/api/v1/stores/{second.store_id}/aliases",
            json={"raw_alias": "Market One"},
            headers={**manager_headers, "X-CSRF-Token": manager_csrf},
        )
    finally:
        app.dependency_overrides.clear()

    assert listing.status_code == 200
    assert page.status_code == 200
    assert len(store_queries) == 2
    assert "Market One" in page.text
    assert "market one" in page.text
    listed = {store["store_id"]: store for store in listing.json()}
    assert listed[first.store_id]["alias_count"] == 1
    assert listed[first.store_id]["receipt_count"] == 1
    assert listed[second.store_id]["receipt_count"] == 1
    assert denied.status_code == 403
    assert duplicate.status_code == 409
    assert renamed.status_code == 200
    assert renamed.json()["display_name"] == "Market Two"
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    assert alias.status_code == 200
    assert alias.json()["normalized_key"] == "market one"
    assert repeated_alias.status_code == 200
    assert repeated_alias.json()["created"] is False
    assert conflicting_alias.status_code == 409
    with session_factory() as session:
        assert (
            session.scalar(
                select(AuditLog).where(
                    AuditLog.event_type == "STORE_UPDATED",
                    AuditLog.entity_id == first.store_id,
                )
            )
            is not None
        )
    engine.dispose()


def test_store_directory_renders_on_desktop_and_mobile(tmp_path: Path, page: Page) -> None:
    engine, session_factory = _database(tmp_path / "store-page-browser.db")
    with session_factory.begin() as session:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        manager_token, _ = create_session(session, manager)
        persist_extracted_receipt(
            session,
            normalize_receipt(_document("Market One", "TC-109")),
        )

    def override_session() -> Any:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/stores/page",
            headers={"Cookie": f"mbs_session={manager_token}"},
        )
        assert response.status_code == 200
        requests: list[dict[str, Any]] = []

        def route_store_request(route: Any) -> None:
            browser_request = route.request
            requests.append(
                {
                    "url": browser_request.url,
                    "method": browser_request.method,
                    "headers": browser_request.headers,
                    "body": browser_request.post_data_json,
                }
            )
            if browser_request.url.endswith("/aliases"):
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "raw_alias": "Market One Store 001",
                            "normalized_key": "market one",
                        }
                    ),
                )
            elif len([request for request in requests if request["method"] == "PUT"]) == 1:
                route.fulfill(
                    status=409,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "detail": "Another active store uses this display name; "
                            "explicit confirmation is required"
                        }
                    ),
                )
            else:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"display_name": "Market Two", "is_active": False}),
                )

        page.context.add_cookies(
            [{"name": "mbs_csrf", "value": "browser-test-token", "url": "http://testserver"}]
        )
        page.route("**/api/v1/stores/**", route_store_request)
        page.route("http://testserver/", lambda route: route.fulfill(body="<html></html>"))
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto("http://testserver/")
        page.set_viewport_size({"width": 1280, "height": 900})
        page.set_content(response.text)
        store = page.locator("article[data-store-id]")
        assert store.count() == 1
        update_form = store.locator("[data-store-update]")
        update_form.locator("input[name='display_name']").fill("Market Two")
        update_form.locator("input[name='is_active']").uncheck()
        store.get_by_role("button", name="Save store").click()
        page.wait_for_function("document.querySelector('.store-name').textContent === 'Market Two'")
        assert store.locator(".store-name").inner_text() == "Market Two"
        assert store.locator(".status").inner_text().strip() == "Inactive"
        assert store.locator(".store-message").inner_text() == "Store updated"
        assert requests[0]["headers"]["x-csrf-token"] == "browser-test-token"
        assert requests[1]["body"] == {
            "display_name": "Market Two",
            "is_active": False,
            "confirm_duplicate_name": True,
        }

        alias_form = store.locator("[data-store-alias]")
        alias_form.locator("input[name='raw_alias']").fill("Market One Store 001")
        store.get_by_role("button", name="Add alias").click()
        page.wait_for_function(
            "document.querySelector('article[data-store-id]')?.textContent.includes"
            "('Market One Store 001 (market one)')"
        )
        assert "Market One Store 001 (market one)" in store.inner_text()
        assert store.locator(".store-message").inner_text() == "Alias added"

        for width in (1280, 390):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_store_merge_and_forward_split_are_audited_and_idempotent(tmp_path: Path) -> None:
    engine, session_factory = _database(tmp_path / "store-admin.db")
    with session_factory.begin() as session:
        manager = create_user(session, "store-admin", "synthetic password", Role.MANAGER)
        viewer = create_user(session, "store-viewer", "synthetic password", Role.VIEWER)
        manager_token, csrf_token = create_session(session, manager)
        viewer_token, _ = create_session(session, viewer)
        source_receipt = persist_extracted_receipt(
            session,
            normalize_receipt(_document("Market South", "TC-201")),
        )
        target_receipt = persist_extracted_receipt(
            session,
            normalize_receipt(_document("Market North", "TC-202")),
        )
        source_store = session.get(Store, source_receipt.store_id)
        assert source_store is not None
        split_alias, _ = add_store_alias(session, source_store, "Market South Outlet")
        source_store_id = source_receipt.store_id
        target_store_id = target_receipt.store_id
        source_receipt_pk = source_receipt.receipt_pk
        split_alias_key = split_alias.normalized_key

    def override_session() -> Any:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        headers = {
            "Cookie": f"mbs_session={manager_token}",
            "X-CSRF-Token": csrf_token,
        }
        merge_payload = {
            "source_store_id": source_store_id,
            "target_store_id": target_store_id,
            "reason": "Same legal purchase location",
            "source_event_id": "store-merge-event-1",
        }
        denied = client.post(
            "/api/v1/stores/merge",
            json=merge_payload,
            headers={"Cookie": f"mbs_session={viewer_token}", "X-CSRF-Token": csrf_token},
        )
        merged = client.post("/api/v1/stores/merge", json=merge_payload, headers=headers)
        merge_retry = client.post("/api/v1/stores/merge", json=merge_payload, headers=headers)
        split_payload = {
            "source_store_id": target_store_id,
            "alias_keys": [split_alias_key],
            "new_display_name": "South Outlet",
            "reason": "Separate branch for future orders",
            "source_event_id": "store-split-event-1",
        }
        split = client.post("/api/v1/stores/split", json=split_payload, headers=headers)
        split_retry = client.post("/api/v1/stores/split", json=split_payload, headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert denied.status_code == 403
    assert merged.status_code == 200 and merged.json()["idempotent"] is False
    assert merge_retry.status_code == 200 and merge_retry.json()["idempotent"] is True
    assert split.status_code == 200 and split.json()["idempotent"] is False
    assert split_retry.status_code == 200 and split_retry.json()["idempotent"] is True
    split_store_id = split.json()["store_id"]
    with session_factory() as session:
        old_store = session.get(Store, source_store_id)
        receipt = session.get(Receipt, source_receipt_pk)
        alias = session.get(StoreAliasKey, split_alias_key)
        assert old_store is not None and old_store.superseded_by_store_id == target_store_id
        assert receipt is not None and receipt.store_id == target_store_id
        assert alias is not None and alias.store_id == split_store_id
        assert (
            session.scalar(select(AuditLog).where(AuditLog.event_type == "STORE_MERGED"))
            is not None
        )
        assert (
            session.scalar(
                select(AuditLog).where(AuditLog.event_type == "STORE_SPLIT_FORWARD_ONLY")
            )
            is not None
        )
        future_store, alias_key = resolve_store(
            session,
            "Market South Outlet",
            {"receipt": {"store": "Market South Outlet"}},
        )
        assert future_store.store_id == split_store_id
        assert alias_key == split_alias_key
    engine.dispose()


def test_store_merge_requires_item_merge_before_resolving_colliding_product_ids(
    tmp_path: Path,
) -> None:
    engine, session_factory = _database(tmp_path / "store-merge-collision.db")
    with session_factory.begin() as session:
        manager = create_user(session, "collision-manager", "synthetic password", Role.MANAGER)
        token, csrf = create_session(session, manager)
        source_receipt = persist_extracted_receipt(
            session,
            normalize_receipt(
                {
                    "receipt": {
                        "store": "Market Source",
                        "date": "2026-09-30",
                        "time": "14:05:06",
                        "transaction_number": "COL-1",
                        "total": "1.00",
                    },
                    "items": [
                        {"description": "Milk", "line_total": "1.00", "store_product_id": "SKU-1"}
                    ],
                }
            ),
        )
        target_receipt = persist_extracted_receipt(
            session,
            normalize_receipt(
                {
                    "receipt": {
                        "store": "Market Target",
                        "date": "2026-09-30",
                        "time": "14:05:06",
                        "transaction_number": "COL-2",
                        "total": "1.00",
                    },
                    "items": [
                        {"description": "Milk", "line_total": "1.00", "store_product_id": "SKU-1"}
                    ],
                }
            ),
        )
        source_store_id = source_receipt.store_id
        target_store_id = target_receipt.store_id
        source_item = session.scalar(select(StoreItem).where(StoreItem.store_id == source_store_id))
        target_item = session.scalar(select(StoreItem).where(StoreItem.store_id == target_store_id))
        assert source_item is not None and target_item is not None
        source_item_id = source_item.item_id
        target_item_id = target_item.item_id

    def override_session() -> Any:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        headers = {"Cookie": f"mbs_session={token}", "X-CSRF-Token": csrf}
        merge_payload = {
            "source_store_id": source_store_id,
            "target_store_id": target_store_id,
            "reason": "Group duplicate canonical stores",
            "source_event_id": "colliding-store-merge-event",
        }
        response = client.post("/api/v1/stores/merge", json=merge_payload, headers=headers)
        item_merge = client.post(
            "/api/v1/items/merge",
            json={
                "source_item_id": source_item_id,
                "target_item_id": target_item_id,
                "effective_from": "2026-10-01",
                "reason": "Same product at newly grouped store",
                "source_event_id": "store-collision-item-merge",
            },
            headers=headers,
        )
        resolved_merge = client.post("/api/v1/stores/merge", json=merge_payload, headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "colliding store product identifiers" in response.json()["detail"]
    assert item_merge.status_code == 200
    assert resolved_merge.status_code == 200
    with session_factory() as session:
        source_store = session.get(Store, source_store_id)
        source_item = session.scalar(select(StoreItem).where(StoreItem.store_id == source_store_id))
        assert source_store is not None and source_store.superseded_by_store_id == target_store_id
        assert source_item is not None
        assert source_item.store_id == source_store_id
        assert source_item.item_id == target_item_id
    engine.dispose()


@pytest.mark.parametrize("width", [1280, 390])
def test_store_grouping_screen_sends_confirmed_merge_and_forward_split(
    tmp_path: Path,
    page: Page,
    width: int,
) -> None:
    engine, session_factory = _database(tmp_path / f"store-grouping-page-{width}.db")
    with session_factory.begin() as session:
        manager = create_user(session, f"group-manager-{width}", "synthetic password", Role.MANAGER)
        token, _ = create_session(session, manager)
        source = persist_extracted_receipt(
            session,
            normalize_receipt(_document("Market South", f"TC-{width}-1")),
        )
        target = persist_extracted_receipt(
            session,
            normalize_receipt(_document("Market North", f"TC-{width}-2")),
        )
        source_store_id = source.store_id
        target_store_id = target.store_id

    def override_session() -> Any:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        response = TestClient(app).get(
            "/api/v1/stores/page",
            headers={"Cookie": f"mbs_session={token}"},
        )
        assert response.status_code == 200
        requests: list[dict[str, Any]] = []

        def route_operation(route: Any) -> None:
            request = route.request
            requests.append(
                {
                    "url": request.url,
                    "method": request.method,
                    "headers": request.headers,
                    "body": request.post_data_json,
                }
            )
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"store_id": "new-store", "display_name": "South Outlet"}),
            )

        page.context.add_cookies(
            [{"name": "mbs_csrf", "value": "group-csrf", "url": "http://testserver"}]
        )
        page.route("**/api/v1/stores/merge", route_operation)
        page.route("**/api/v1/stores/split", route_operation)
        page.route("http://testserver/", lambda route: route.fulfill(body=response.text))
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto("http://testserver/")
        page.set_viewport_size({"width": width, "height": 900})
        page.set_content(response.text)

        source_card = page.locator(f"article[data-store-id='{source_store_id}']")
        merge_form = source_card.locator("[data-store-merge]")
        merge_form.locator("select[name='target_store_id']").select_option(target_store_id)
        merge_form.locator("input[name='reason']").fill("Duplicate store record")
        merge_form.get_by_role("button", name="Merge store").click()
        page.wait_for_function("window.location.pathname === '/' && document.querySelector('h1')")

        source_card = page.locator(f"article[data-store-id='{source_store_id}']")
        split_form = source_card.locator("[data-store-split]")
        split_form.locator("input[name='alias_key'][value='market south']").check()
        split_form.locator("input[name='new_display_name']").fill("South Outlet")
        split_form.locator("input[name='reason']").fill("Separate branch going forward")
        split_form.get_by_role("button", name="Split aliases forward").click()
        page.wait_for_function("window.location.pathname === '/' && document.querySelector('h1')")

        assert len(requests) == 2
        assert requests[0]["url"].endswith("/stores/merge")
        assert requests[0]["headers"]["x-csrf-token"] == "group-csrf"
        assert requests[0]["body"]["source_store_id"] == source_store_id
        assert requests[0]["body"]["target_store_id"] == target_store_id
        assert requests[0]["body"]["source_event_id"]
        assert requests[1]["url"].endswith("/stores/split")
        assert requests[1]["body"]["alias_keys"] == ["market south"]
        assert "future imports only" in response.text.lower()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
