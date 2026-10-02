from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from playwright.sync_api import Page
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from mbs.auth import Role, create_session, create_user
from mbs.db import get_session
from mbs.items import register_store_item
from mbs.main import app
from mbs.models import (
    AuditLog,
    Item,
    ItemMappingEvent,
    ReceiptItem,
    Setting,
    Store,
    StoreItem,
    StoreItemMapping,
)
from mbs.receipts.approval import approve_receipt_item
from mbs.receipts.ocr import BusinessDisposition, normalize_receipt
from mbs.receipts.persistence import persist_extracted_receipt
from tests.database import postgres_test_url


def _database(path: Path) -> tuple[Any, sessionmaker[Session]]:
    engine = create_engine(postgres_test_url(path))

    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(path).replace("%", "%%"))
    command.upgrade(config, "head")
    return engine, sessionmaker(engine, expire_on_commit=False)


def _receipt(
    transaction_number: str,
    store: str,
    receipt_date: str,
    product_id: str,
    description: str,
    upc: str | None = None,
) -> Any:
    item: dict[str, object] = {
        "description": description,
        "line_total": "2.00",
        "store_product_id": product_id,
    }
    if upc is not None:
        item["upc"] = upc
    return normalize_receipt(
        {
            "receipt": {
                "store": store,
                "date": receipt_date,
                "time": "14:05:06",
                "transaction_number": transaction_number,
                "total": "2.00",
            },
            "items": [item],
        }
    )


def _gallery_png(position: int, color: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (160, 120), "white")
    ImageDraw.Draw(image).rectangle((position, 10, position + 42, 110), fill=color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _override(session_factory: sessionmaker[Session]) -> Any:
    def override_session() -> Any:
        with session_factory() as session:
            yield session

    return override_session


def test_im_002_item_gallery_upload_replace_reorder_and_detach_browser(
    tmp_path: Path,
    page: Page,
) -> None:
    engine, session_factory = _database(tmp_path / "item-gallery-browser.db")
    with session_factory.begin() as session:
        manager = create_user(session, "gallery-ui-manager", "synthetic password", Role.MANAGER)
        token, _ = create_session(session, manager)
        store = Store(display_name="Synthetic Gallery UI Store")
        session.add(store)
        session.flush()
        store_item = register_store_item(
            session,
            store.store_id,
            "GALLERY-UI-SKU",
            "Synthetic image item",
            actor_id=manager.id,
        )
        store_item.mapping_confirmed = True
        owner_id = store_item.item_id

    app.dependency_overrides[get_session] = _override(session_factory)
    try:
        response = TestClient(app).get(
            "/api/v1/items/page", headers={"Cookie": f"mbs_session={token}"}
        )
        assert response.status_code == 200
        assert response.text.count("data-image-gallery data-owner-kind=") == 2
        page.context.add_cookies(
            [{"name": "mbs_csrf", "value": "gallery-ui-csrf", "url": "http://gallery.test"}]
        )
        gallery_state: dict[str, Any] = {"images": [], "primary_id": None, "next_id": 1}
        image_requests: list[dict[str, Any]] = []
        image_png = _gallery_png(12, (30, 110, 180))

        def gallery_route(route: Any) -> None:
            request = route.request
            image_requests.append(
                {
                    "method": request.method,
                    "headers": request.headers,
                    "url": request.url,
                    "body": request.post_data_buffer,
                }
            )
            if request.method == "GET":
                resolved = None
                if gallery_state["primary_id"] is not None:
                    resolved = {
                        "owner_kind": "ITEM",
                        "owner_id": owner_id,
                        "link_id": gallery_state["primary_id"],
                        "thumbnail_url": (
                            f"/api/v1/image-owners/ITEM/{owner_id}/images/"
                            f"{gallery_state['primary_id']}/thumbnail"
                        ),
                    }
                body = {
                    "resolved_primary": resolved,
                    "placeholder": resolved is None,
                    "images": gallery_state["images"],
                }
                route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
                return
            if request.method == "POST":
                link_id = gallery_state["next_id"]
                gallery_state["next_id"] += 1
                image = {
                    "link_id": link_id,
                    "asset_sha256": f"synthetic-{link_id}",
                    "is_primary": not gallery_state["images"],
                    "sort_order": len(gallery_state["images"]),
                    "thumbnail_url": (
                        f"/api/v1/image-owners/ITEM/{owner_id}/images/{link_id}/thumbnail"
                    ),
                    "display_url": f"/api/v1/image-owners/ITEM/{owner_id}/images/{link_id}/display",
                }
                gallery_state["images"].append(image)
                if image["is_primary"]:
                    gallery_state["primary_id"] = link_id
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "link_id": link_id,
                            "is_primary": image["is_primary"],
                            "replace_prompt_required": False,
                        }
                    ),
                )
                return
            if request.method == "PUT":
                ordered_ids = request.post_data_json["link_ids"]
                gallery_state["images"].sort(key=lambda image: ordered_ids.index(image["link_id"]))
                route.fulfill(status=200, content_type="application/json", body="{}")
                return
            if request.method == "DELETE":
                link_id = int(request.url.rstrip("/").split("/")[-1])
                gallery_state["images"] = [
                    image for image in gallery_state["images"] if image["link_id"] != link_id
                ]
                if gallery_state["primary_id"] == link_id:
                    gallery_state["primary_id"] = (
                        gallery_state["images"][0]["link_id"] if gallery_state["images"] else None
                    )
                route.fulfill(status=200, content_type="application/json", body="{}")
                return
            route.fulfill(status=405, body="Method not allowed")

        def primary_route(route: Any) -> None:
            payload = route.request.post_data_json
            link_id = int(route.request.url.rstrip("/").split("/")[-2])
            image_requests.append(
                {"method": "POST_PRIMARY", "payload": payload, "headers": route.request.headers}
            )
            if (
                gallery_state["primary_id"] not in {None, link_id}
                and not payload["replace_primary"]
            ):
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"replace_prompt_required": True}),
                )
                return
            gallery_state["primary_id"] = link_id
            for image in gallery_state["images"]:
                image["is_primary"] = image["link_id"] == link_id
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"link_id": link_id, "is_primary": True}),
            )

        def reorder_route(route: Any) -> None:
            image_requests.append({"method": "PUT_ORDER", "headers": route.request.headers})
            ordered_ids = route.request.post_data_json["link_ids"]
            gallery_state["images"].sort(key=lambda image: ordered_ids.index(image["link_id"]))
            route.fulfill(status=200, content_type="application/json", body="{}")

        def detach_route(route: Any) -> None:
            image_requests.append({"method": "DELETE_IMAGE", "headers": route.request.headers})
            link_id = int(route.request.url.rstrip("/").split("/")[-1])
            gallery_state["images"] = [
                image for image in gallery_state["images"] if image["link_id"] != link_id
            ]
            if gallery_state["primary_id"] == link_id:
                gallery_state["primary_id"] = (
                    gallery_state["images"][0]["link_id"] if gallery_state["images"] else None
                )
            route.fulfill(status=200, content_type="application/json", body="{}")

        page.route("http://gallery.test/", lambda route: route.fulfill(body=response.text))
        page.route(re.compile(r"/image-owners/[^/]+/[^/]+/images$"), gallery_route)
        page.route(re.compile(r"/image-owners/[^/]+/[^/]+/images/order$"), reorder_route)
        page.route(re.compile(r"/image-owners/[^/]+/[^/]+/images/\d+$"), detach_route)
        page.route("**/image-owners/*/*/images/*/primary", primary_route)
        page.route(
            "**/image-owners/*/*/images/*/thumbnail",
            lambda route: route.fulfill(status=200, content_type="image/png", body=image_png),
        )
        page.goto("http://gallery.test/")
        gallery = page.locator('[data-image-gallery][data-owner-kind="ITEM"]').first
        gallery.get_by_text("No image").wait_for()
        assert gallery.locator('[data-gallery-upload][capture="environment"]').count() == 1
        upload = gallery.locator("[data-gallery-upload]").first
        upload.set_input_files(
            {"name": "synthetic-one.png", "mimeType": "image/png", "buffer": image_png}
        )
        gallery.get_by_text("Primary", exact=True).wait_for()
        upload.set_input_files(
            {
                "name": "synthetic-two.png",
                "mimeType": "image/png",
                "buffer": _gallery_png(75, (190, 50, 25)),
            }
        )
        second_primary_button = gallery.get_by_role("button", name="Make primary").last
        second_primary_button.click()
        dialog = page.locator("[data-gallery-replacement-dialog]")
        dialog.wait_for(state="visible")
        assert page.evaluate("document.activeElement.textContent") == "Keep current primary"
        dialog.get_by_role("button", name="Keep current primary").click()
        gallery.get_by_text("Gallery", exact=True).wait_for()
        assert gallery.locator("[data-gallery-images] img").count() == 2
        gallery.get_by_role("button", name="Move later").first.click()
        gallery.get_by_role("button", name="Make primary").last.click()
        dialog.get_by_role("button", name="Replace primary").click()
        page.wait_for_function(
            "document.querySelector('[data-image-gallery][data-owner-kind=\\\"ITEM\\\"]')"
            ".querySelectorAll('[data-gallery-images] img').length === 2"
        )
        assert any(
            request["headers"].get("x-csrf-token") == "gallery-ui-csrf"
            for request in image_requests
            if request["method"] == "POST_PRIMARY"
        )
        assert any(request["method"] == "PUT_ORDER" for request in image_requests)
        gallery.get_by_role("button", name="Detach").first.click()
        assert any(request["method"] == "DELETE_IMAGE" for request in image_requests)
        for width in (1280, 390):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_s16_migration_backfills_purchase_dates_and_downgrades_unchanged_history(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "mapping-history-migration.db"
    engine = create_engine(postgres_test_url(database_path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(database_path).replace("%", "%%"))
    command.upgrade(config, "0014_item_identity")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """INSERT INTO tbl_items (item_id, common_name, is_store_observed, is_active)
            VALUES ('legacy-item', 'Legacy item', TRUE, TRUE)"""
        )
        connection.exec_driver_sql(
            """INSERT INTO tbl_stores (store_id, display_name, is_active)
            VALUES ('legacy-store', 'Legacy store', TRUE)"""
        )
        connection.exec_driver_sql(
            """INSERT INTO tbl_store_aliases (normalized_key, store_id)
            VALUES ('legacy store', 'legacy-store')"""
        )
        connection.exec_driver_sql(
            """INSERT INTO tbl_store_items
            (store_item_id, store_id, store_product_id, item_id, latest_description,
             identifier_source, mapping_confirmed, created_at)
            VALUES ('legacy-store-item', 'legacy-store', 'LEGACY-SKU', 'legacy-item',
                    'Legacy printed name', 'MERCHANT', TRUE, '2026-10-03 12:00:00+00')"""
        )
        connection.exec_driver_sql(
            """INSERT INTO tbl_receipts
            (receipt_pk, receipt_id, store_id, store_alias_key, store, receipt_date,
             receipt_time, transaction_number, source_type, total, raw_ocr_document,
             receipt_document)
            VALUES ('legacy-receipt', 'Legacy|2026-09-30|14:00:00|MIG-1',
                    'legacy-store', 'legacy store', 'Legacy store', '2026-09-30',
                    '14:00:00', 'MIG-1', 'OCR', 2.00, '{}', '{}')"""
        )
        connection.exec_driver_sql(
            """INSERT INTO tbl_receipt_items
            (receipt_pk, description, line_total, category, business_disposition,
             store_item_id, item_id)
            VALUES ('legacy-receipt', 'Legacy printed name', 2.00, 'Other',
                    'UNCLASSIFIED', 'legacy-store-item', 'legacy-item')"""
        )

    command.upgrade(config, "head")
    with sessionmaker(engine)() as session:
        store_item = session.get(StoreItem, "legacy-store-item")
        mapping = session.scalar(
            select(StoreItemMapping).where(StoreItemMapping.store_item_id == "legacy-store-item")
        )
        assert store_item is not None and mapping is not None
        assert mapping.item_id == store_item.item_id == "legacy-item"
        assert mapping.effective_from == date(2026, 9, 30)
        assert mapping.actor == "SYSTEM"

    command.downgrade(config, "0014_item_identity")
    assert "tbl_store_item_mappings" not in inspect(engine).get_table_names()
    engine.dispose()


def test_remap_is_effective_dated_and_preserves_posted_receipt_identity(
    tmp_path: Path,
) -> None:
    engine, session_factory = _database(tmp_path / "effective-item-mapping.db")
    with session_factory.begin() as session:
        manager = create_user(session, "mapping-manager", "synthetic password", Role.MANAGER)
        viewer = create_user(session, "mapping-viewer", "synthetic password", Role.VIEWER)
        manager_token, csrf_token = create_session(session, manager)
        viewer_token, viewer_csrf = create_session(session, viewer)
        manager_id = manager.id
        base_receipt = persist_extracted_receipt(
            session,
            normalize_receipt(
                {
                    "receipt": {
                        "store": "Market One",
                        "date": "2026-09-30",
                        "time": "14:00:00",
                        "transaction_number": "MAP-000",
                        "total": "0.00",
                    },
                    "items": [],
                }
            ),
        )
        canonical = Item(common_name="Dairy Milk", is_store_observed=False)
        target = Item(common_name="Whole Milk", is_store_observed=False)
        session.add_all([canonical, target])
        session.flush()
        store_item_one = register_store_item(
            session,
            base_receipt.store_id,
            "MILK-1",
            "Milk",
            confirmed_item_id=canonical.item_id,
            actor_id=manager.id,
            effective_from=date(2026, 9, 30),
        )
        register_store_item(
            session,
            base_receipt.store_id,
            "MILK-2",
            "Milk large",
            confirmed_item_id=canonical.item_id,
            actor_id=manager.id,
            effective_from=date(2026, 9, 30),
        )
        historical_receipt = persist_extracted_receipt(
            session,
            _receipt("MAP-001", "Market One", "2026-09-30", "MILK-1", "Milk"),
        )
        store_item_id = store_item_one.store_item_id
        canonical_item_id = canonical.item_id
        target_item_id = target.item_id
        receipt_pk = historical_receipt.receipt_pk

    app.dependency_overrides[get_session] = _override(session_factory)
    try:
        client = TestClient(app)
        url = "/api/v1/items/map"
        payload = {
            "store_item_id": store_item_id,
            "item_id": target_item_id,
            "store_common_name": "  Large Milk  ",
            "effective_from": "2026-10-01",
            "reason": "Separate the larger package for future purchases",
            "source_event_id": "mapping-event-001",
        }
        denied = client.post(
            url,
            json=payload,
            headers={"Cookie": f"mbs_session={manager_token}"},
        )
        backdated = client.post(
            url,
            json={**payload, "effective_from": "2026-09-30", "source_event_id": "backdated-1"},
            headers={
                "Cookie": f"mbs_session={manager_token}",
                "X-CSRF-Token": csrf_token,
            },
        )
        viewer_denied = client.get(
            "/api/v1/store-items?unmapped_only=true",
            headers={"Cookie": f"mbs_session={viewer_token}"},
        )
        viewer_mapping_denied = client.post(
            url,
            json=payload,
            headers={
                "Cookie": f"mbs_session={viewer_token}",
                "X-CSRF-Token": viewer_csrf,
            },
        )
        mapped = client.post(
            url,
            json=payload,
            headers={
                "Cookie": f"mbs_session={manager_token}",
                "X-CSRF-Token": csrf_token,
            },
        )
        retried = client.post(
            url,
            json=payload,
            headers={
                "Cookie": f"mbs_session={manager_token}",
                "X-CSRF-Token": csrf_token,
            },
        )
        conflict = client.post(
            url,
            json={**payload, "item_id": canonical_item_id},
            headers={
                "Cookie": f"mbs_session={manager_token}",
                "X-CSRF-Token": csrf_token,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert denied.status_code == 403
    assert backdated.status_code == 409
    assert "Historical item mapping changes" in backdated.json()["detail"]
    assert viewer_denied.status_code == 403
    assert viewer_mapping_denied.status_code == 403
    assert mapped.status_code == 200
    assert retried.status_code == 200 and retried.json()["item_id"] == target_item_id
    assert conflict.status_code == 409
    with session_factory.begin() as session:
        original_line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt_pk)
        )
        assert original_line is not None
        assert original_line.item_id == canonical_item_id
        assert original_line.store_item_id == store_item_id
        current_store_item = session.get(StoreItem, store_item_id)
        assert current_store_item is not None and current_store_item.item_id == target_item_id
        assert current_store_item.common_name == "Large Milk"
        assert (
            session.scalar(
                select(func.count(StoreItem.store_item_id)).where(
                    StoreItem.item_id == canonical_item_id
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(ItemMappingEvent).where(
                    ItemMappingEvent.source_event_id == "mapping-event-001"
                )
            )
            is not None
        )
        assert (
            session.scalar(
                select(AuditLog).where(AuditLog.event_type == "STORE_ITEM_MAPPING_CONFIRMED")
            )
            is not None
        )
        original_line.package_count = Decimal("1")
        original_line.pack_size = Decimal("1")
        original_line.pack_unit = "EACH"
        historical_approval = approve_receipt_item(
            session,
            original_line.id,
            manager_id,
            BusinessDisposition.RECIPE_INGREDIENT,
        )
        assert historical_approval.approval.posting_status == "ROUTED"
        future_receipt = persist_extracted_receipt(
            session,
            _receipt("MAP-002", "Market One", "2026-10-02", "MILK-1", "Milk new label"),
        )
        future_line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == future_receipt.receipt_pk)
        )
        assert future_line is not None and future_line.item_id == target_item_id
        original_line.package_count = None
        original_line.pack_size = None
        original_line.pack_unit = None
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        postgres_test_url(tmp_path / "effective-item-mapping.db").replace("%", "%%"),
    )
    with pytest.raises(RuntimeError, match="routing records exist"):
        command.downgrade(config, "0014_item_identity")
    engine.dispose()


def test_ranked_suggestions_use_shared_upc_and_setting_limit_without_auto_mapping(
    tmp_path: Path,
) -> None:
    engine, session_factory = _database(tmp_path / "item-suggestions.db")
    with session_factory.begin() as session:
        manager = create_user(session, "suggestion-manager", "synthetic password", Role.MANAGER)
        token, _ = create_session(session, manager)
        receipt = persist_extracted_receipt(
            session,
            _receipt("SUG-001", "Market One", "2026-09-30", "SKU-1", "Milk", "UPC-1"),
        )
        setting = session.get(Setting, "item_mapping_suggestion_limit")
        assert setting is not None
        setting.value = "1"
        item_line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
        )
        assert item_line is not None and item_line.item_id is not None
        source_store_item = session.get(StoreItem, item_line.store_item_id)
        assert source_store_item is not None
        source_store_item.mapping_confirmed = True
        source_item_id = source_store_item.item_id
        new_store = persist_extracted_receipt(
            session,
            _receipt("SUG-002", "Market Two", "2026-09-30", "SKU-2", "Milk alt", "UPC-1"),
        )
        new_line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == new_store.receipt_pk)
        )
        assert new_line is not None and new_line.store_item_id is not None
        new_store_item_id = new_line.store_item_id

    app.dependency_overrides[get_session] = _override(session_factory)
    try:
        response = TestClient(app).get(
            "/api/v1/items/mapping-suggestions",
            params={"store_item_id": new_store_item_id},
            headers={"Cookie": f"mbs_session={token}"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["item_id"] == source_item_id
    assert "Shared UPC" in response.json()[0]["reasons"]
    with session_factory() as session:
        new_store_item = session.get(StoreItem, new_store_item_id)
        assert new_store_item is not None and new_store_item.mapping_confirmed is False
    engine.dispose()


def test_missing_printed_identifier_resolution_is_protected_audited_and_idempotent(
    tmp_path: Path,
) -> None:
    engine, session_factory = _database(tmp_path / "reviewed-sku-api.db")
    with session_factory.begin() as session:
        manager = create_user(session, "sku-api-manager", "synthetic password", Role.MANAGER)
        token, csrf = create_session(session, manager)
        receipt = persist_extracted_receipt(
            session,
            _receipt("SKU-API-001", "Market One", "2026-09-30", "", "Mystery item"),
        )
        line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
        )
        assert line is not None
        line.package_count = Decimal("1")
        line.pack_size = Decimal("1")
        line.pack_unit = "EACH"
        line_id = line.id

    app.dependency_overrides[get_session] = _override(session_factory)
    try:
        client = TestClient(app)
        path = f"/api/v1/receipt-items/{line_id}/store-product-id"
        payload = {
            "store_product_id": "SKU-REVIEWED-1",
            "source_event_id": "reviewed-sku-event-1",
        }
        denied = client.post(path, json=payload, headers={"Cookie": f"mbs_session={token}"})
        headers = {"Cookie": f"mbs_session={token}", "X-CSRF-Token": csrf}
        resolved = client.post(path, json=payload, headers=headers)
        retry = client.post(path, json=payload, headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert denied.status_code == 403
    assert resolved.status_code == 200
    assert retry.status_code == 200
    assert retry.json()["store_item_id"] == resolved.json()["store_item_id"]
    with session_factory() as session:
        line = session.get(ReceiptItem, line_id)
        assert line is not None and line.raw_ocr_item is not None
        assert line.raw_ocr_item.get("store_product_id") == ""
        assert line.store_item_id == resolved.json()["store_item_id"]
        store_item = session.get(StoreItem, line.store_item_id)
        assert store_item is not None and store_item.mapping_confirmed is False
        assert (
            session.scalar(
                select(ItemMappingEvent).where(
                    ItemMappingEvent.source_event_id == "reviewed-sku-event-1"
                )
            )
            is not None
        )
        with pytest.raises(ValueError, match="mapping must be confirmed"):
            approve_receipt_item(
                session,
                line_id,
                1,
                BusinessDisposition.RECIPE_INGREDIENT,
            )
    engine.dispose()


def test_audited_item_merge_preserves_receipt_lines_and_routes_future_imports(
    tmp_path: Path,
) -> None:
    engine, session_factory = _database(tmp_path / "item-merge.db")
    with session_factory.begin() as session:
        manager = create_user(session, "merge-manager", "synthetic password", Role.MANAGER)
        token, csrf = create_session(session, manager)
        base_receipt = persist_extracted_receipt(
            session,
            normalize_receipt(
                {
                    "receipt": {
                        "store": "Market One",
                        "date": "2026-09-30",
                        "time": "14:00:00",
                        "transaction_number": "MERGE-000",
                        "total": "0.00",
                    },
                    "items": [],
                }
            ),
        )
        source = Item(common_name="Source item", is_store_observed=False)
        target = Item(common_name="Canonical item", is_store_observed=False)
        session.add_all([source, target])
        session.flush()
        register_store_item(
            session,
            base_receipt.store_id,
            "MERGE-SKU-1",
            "Product one",
            confirmed_item_id=source.item_id,
            actor_id=manager.id,
            effective_from=date(2026, 9, 30),
        )
        register_store_item(
            session,
            base_receipt.store_id,
            "MERGE-SKU-2",
            "Product two",
            confirmed_item_id=source.item_id,
            actor_id=manager.id,
            effective_from=date(2026, 9, 30),
        )
        receipt = persist_extracted_receipt(
            session,
            _receipt("MERGE-001", "Market One", "2026-09-30", "MERGE-SKU-1", "Product one"),
        )
        receipt_pk = receipt.receipt_pk
        source_id = source.item_id
        target_id = target.item_id

    app.dependency_overrides[get_session] = _override(session_factory)
    try:
        client = TestClient(app)
        payload = {
            "source_item_id": source_id,
            "target_item_id": target_id,
            "effective_from": "2026-10-01",
            "reason": "Consolidate confirmed canonical identity",
            "source_event_id": "canonical-merge-event-1",
        }
        headers = {"Cookie": f"mbs_session={token}", "X-CSRF-Token": csrf}
        merged = client.post("/api/v1/items/merge", json=payload, headers=headers)
        retry = client.post("/api/v1/items/merge", json=payload, headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert merged.status_code == 200
    assert retry.status_code == 200
    with session_factory.begin() as session:
        source_item = session.get(Item, source_id)
        assert source_item is not None
        assert source_item.is_active is False
        assert source_item.superseded_by_item_id == target_id
        old_line = session.scalar(select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt_pk))
        assert old_line is not None and old_line.item_id == source_id
        assert (
            session.scalar(
                select(func.count(StoreItem.store_item_id)).where(StoreItem.item_id == target_id)
            )
            == 2
        )
        future = persist_extracted_receipt(
            session,
            _receipt("MERGE-002", "Market One", "2026-10-02", "MERGE-SKU-1", "Renamed product"),
        )
        future_line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == future.receipt_pk)
        )
        assert future_line is not None and future_line.item_id == target_id
        assert (
            session.scalar(
                select(func.count(ItemMappingEvent.id)).where(
                    ItemMappingEvent.source_event_id == "canonical-merge-event-1"
                )
            )
            == 1
        )
    engine.dispose()


def test_store_item_split_moves_only_future_mapping_and_keeps_other_source_links(
    tmp_path: Path,
) -> None:
    engine, session_factory = _database(tmp_path / "item-split.db")
    with session_factory.begin() as session:
        manager = create_user(session, "split-manager", "synthetic password", Role.MANAGER)
        token, csrf = create_session(session, manager)
        base_receipt = persist_extracted_receipt(
            session,
            normalize_receipt(
                {
                    "receipt": {
                        "store": "Market One",
                        "date": "2026-09-30",
                        "time": "14:00:00",
                        "transaction_number": "SPLIT-000",
                        "total": "0.00",
                    },
                    "items": [],
                }
            ),
        )
        original = Item(common_name="Milk", is_store_observed=False)
        session.add(original)
        session.flush()
        register_store_item(
            session,
            base_receipt.store_id,
            "SPLIT-SKU-1",
            "Milk small",
            confirmed_item_id=original.item_id,
            actor_id=manager.id,
            effective_from=date(2026, 9, 30),
        )
        register_store_item(
            session,
            base_receipt.store_id,
            "SPLIT-SKU-2",
            "Milk large",
            confirmed_item_id=original.item_id,
            actor_id=manager.id,
            effective_from=date(2026, 9, 30),
        )
        receipt = persist_extracted_receipt(
            session,
            _receipt("SPLIT-001", "Market One", "2026-09-30", "SPLIT-SKU-1", "Milk small"),
        )
        line_id = session.scalar(
            select(ReceiptItem.id).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
        )
        original_item_id = original.item_id
        store_item_id = session.scalar(
            select(StoreItem.store_item_id).where(
                StoreItem.store_id == base_receipt.store_id,
                StoreItem.store_product_id == "SPLIT-SKU-1",
            )
        )

    app.dependency_overrides[get_session] = _override(session_factory)
    try:
        response = TestClient(app).post(
            "/api/v1/items/split",
            json={
                "store_item_id": store_item_id,
                "common_name": "Milk small",
                "effective_from": "2026-10-01",
                "reason": "Separate package size",
                "source_event_id": "item-split-event-1",
            },
            headers={"Cookie": f"mbs_session={token}", "X-CSRF-Token": csrf},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    split_item_id = response.json()["item_id"]
    with session_factory.begin() as session:
        old_line = session.get(ReceiptItem, line_id)
        assert old_line is not None and old_line.item_id == original_item_id
        current_store_item = session.get(StoreItem, store_item_id)
        assert current_store_item is not None and current_store_item.item_id == split_item_id
        assert (
            session.scalar(
                select(func.count(StoreItem.store_item_id)).where(
                    StoreItem.item_id == original_item_id
                )
            )
            == 1
        )
        event_row = session.scalar(
            select(ItemMappingEvent).where(ItemMappingEvent.source_event_id == "item-split-event-1")
        )
        assert event_row is not None and event_row.operation == "SPLIT"
        future_receipt = persist_extracted_receipt(
            session,
            _receipt("SPLIT-002", "Market One", "2026-10-02", "SPLIT-SKU-1", "Milk small"),
        )
        future_line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == future_receipt.receipt_pk)
        )
        assert future_line is not None and future_line.item_id == split_item_id
    engine.dispose()


@pytest.mark.parametrize("width", [1280, 390])
def test_item_mapping_screen_requires_confirmation_and_fits_viewport(
    tmp_path: Path,
    page: Page,
    width: int,
) -> None:
    engine, session_factory = _database(tmp_path / f"item-map-page-{width}.db")
    with session_factory.begin() as session:
        manager = create_user(session, f"page-manager-{width}", "synthetic password", Role.MANAGER)
        token, _ = create_session(session, manager)
        persist_extracted_receipt(
            session,
            _receipt("PAGE-001", "Market One", "2026-09-30", "SKU-PAGE", "Milk"),
        )
        suggested_item = Item(common_name="Milk")
        session.add(suggested_item)
        session.flush()
        suggested_item_id = suggested_item.item_id

    app.dependency_overrides[get_session] = _override(session_factory)
    try:
        response = TestClient(app).get(
            "/api/v1/items/page",
            headers={"Cookie": f"mbs_session={token}"},
        )
        assert response.status_code == 200
        requests: list[dict[str, Any]] = []

        def route_request(route: Any) -> None:
            request = route.request
            requests.append(
                {
                    "url": request.url,
                    "method": request.method,
                    "headers": request.headers,
                    "body": request.post_data_json,
                }
            )
            if "mapping-suggestions" in request.url:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=(
                        '[{"item_id":"' + suggested_item_id + '","common_name":"Milk","score":100,'
                        '"reasons":["Shared UPC"]}]'
                    ),
                )
            elif request.method == "POST":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=(
                        '{"store_item_id":"store-item","item_id":"'
                        + suggested_item_id
                        + '","mapping_confirmed":true}'
                    ),
                )
            else:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body='{"store_item_id":"store-item","common_name":"Milk"}',
                )

        page.context.add_cookies(
            [{"name": "mbs_csrf", "value": "item-page-csrf", "url": "http://testserver"}]
        )
        page.route("**/api/v1/items/**", route_request)
        page.route("**/api/v1/store-items/**", route_request)
        page.route("http://testserver/", lambda route: route.fulfill(body="<html></html>"))
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto("http://testserver/")
        page.set_viewport_size({"width": width, "height": 900})
        page.set_content(response.text)
        card = page.locator(".item-row")
        card.get_by_role("button", name="Find suggestions").click()
        page.get_by_role("button", name="Milk: Shared UPC").click()
        mapping_form = card.locator("[data-item-map]")
        mapping_form.locator("input[name='reason']").fill("Confirmed synthetic suggestion")
        mapping_form.get_by_role("button", name="Confirm mapping").click()
        page.wait_for_function(
            "document.querySelector('.message').textContent === 'Mapping confirmed'"
        )

        assert requests[0]["url"].find("mapping-suggestions") >= 0
        assert requests[1]["headers"]["x-csrf-token"] == "item-page-csrf"
        assert requests[1]["body"]["item_id"] == suggested_item_id
        assert requests[1]["body"]["reason"] == "Confirmed synthetic suggestion"
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
