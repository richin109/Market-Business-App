from __future__ import annotations

import json
from contextlib import nullcontext
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pymupdf
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from playwright.sync_api import Page
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from mbs.auth import Role, create_session, create_user
from mbs.db import get_session
from mbs.items import confirm_store_item_mapping
from mbs.main import app
from mbs.media_assets import MediaAssetService
from mbs.models import (
    AuditLog,
    MediaAssetLink,
    ReceiptItem,
    ReceiptSource,
    ReceiptUpload,
    StoreItem,
)
from mbs.receipts.approval import DispositionSubtype, approve_receipt_item
from mbs.receipts.ocr import BusinessDisposition, normalize_receipt
from mbs.receipts.persistence import persist_extracted_receipt, persist_source_candidate
from mbs.receipts.storage import LocalProtectedFileStore
from mbs.routers.dependencies import get_receipt_upload_service
from tests.database import postgres_test_url


def _synthetic_pdf(page_count: int) -> bytes:
    document = pymupdf.open()
    for page_index in range(page_count):
        page = document.new_page()
        page.insert_text((48, 72), f"Synthetic receipt page {page_index + 1}")
    source = cast(bytes, document.tobytes())
    document.close()
    return source


def _database(path: Path) -> tuple[Any, sessionmaker[Session]]:
    engine = create_engine(postgres_test_url(path))

    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(path).replace("%", "%%"))
    command.upgrade(config, "head")
    return engine, sessionmaker(engine, expire_on_commit=False)


def test_manager_review_preselects_remembered_subtype_without_auto_approval(
    tmp_path: Path,
    page: Page,
) -> None:
    engine, session_factory = _database(tmp_path / "receipt-review-ui.db")
    with session_factory.begin() as session:
        manager = create_user(session, "review-ui-manager", "synthetic password", Role.MANAGER)
        viewer = create_user(session, "review-ui-viewer", "synthetic password", Role.VIEWER)
        manager_token, _ = create_session(session, manager)
        viewer_token, _ = create_session(session, viewer)
        receipt = persist_extracted_receipt(
            session,
            normalize_receipt(
                {
                    "receipt": {
                        "store": "Synthetic Review Market",
                        "date": "2026-09-30",
                        "time": "14:05:06",
                        "transaction_number": "REVIEW-UI-1",
                        "total": "2.00",
                    },
                    "items": [
                        {
                            "description": "Cups",
                            "line_total": "2.00",
                            "store_product_id": "CUPS-1",
                        }
                    ],
                }
            ),
        )
        line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
        )
        assert line is not None and line.store_item_id is not None and line.item_id is not None
        store_item = session.get(StoreItem, line.store_item_id)
        assert store_item is not None
        confirm_store_item_mapping(
            session, store_item.store_item_id, store_item.item_id, manager.id
        )
        store_item.last_disposition = "ORDINARY_BUSINESS_PURCHASE"
        store_item.last_disposition_subtype = "STOCKED_SUPPLY"
        receipt_pk = receipt.receipt_pk

    def override_session() -> Any:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        path = f"/api/v1/receipts/{receipt_pk}/review"
        response = client.get(path, headers={"Cookie": f"mbs_session={manager_token}"})
        denied = client.get(path, headers={"Cookie": f"mbs_session={viewer_token}"})
        assert response.status_code == 200
        assert denied.status_code == 403
        requests: list[dict[str, Any]] = []

        def route_approval(route: Any) -> None:
            request = route.request
            requests.append(
                {
                    "headers": request.headers,
                    "body": request.post_data_json,
                }
            )
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "posting_kind": "DIRECT_EXPENSE",
                        "posting_status": "ROUTED",
                        "disposition": "ORDINARY_BUSINESS_PURCHASE",
                        "disposition_subtype": "DIRECT_EXPENSE",
                        "remembered_rule_differs": True,
                    }
                ),
            )

        rule_requests: list[dict[str, Any]] = []

        def route_rule(route: Any) -> None:
            rule_requests.append(
                {"headers": route.request.headers, "body": route.request.post_data_json}
            )
            route.fulfill(status=200, content_type="application/json", body="{}")

        dialogs: list[str] = []

        def accept_dialog(dialog: Any) -> None:
            dialogs.append(dialog.message)
            dialog.accept()

        page.context.add_cookies(
            [{"name": "mbs_csrf", "value": "review-page-csrf", "url": "http://testserver"}]
        )
        page.route("**/api/v1/receipts/*/items/*/approval", route_approval)
        page.route("**/api/v1/remembered-rules/*", route_rule)
        page.route("http://testserver/", lambda route: route.fulfill(body=response.text))
        page.on("dialog", accept_dialog)
        page.goto("http://testserver/")
        page.set_content(response.text)

        line_card = page.locator(".line")
        disposition = line_card.locator("select[name='disposition']")
        subtype = line_card.locator("select[name='disposition_subtype']")
        assert disposition.input_value() == "ORDINARY_BUSINESS_PURCHASE"
        assert subtype.input_value() == "STOCKED_SUPPLY"
        assert len(requests) == 0

        disposition.select_option("PERSONAL_NON_BUSINESS")
        assert subtype.input_value() == "NONE"
        assert subtype.is_disabled()
        disposition.select_option("ORDINARY_BUSINESS_PURCHASE")
        subtype.select_option("DIRECT_EXPENSE")
        line_card.get_by_role("button", name="Approve line").click()
        page.wait_for_function(
            "document.querySelector('.line .message').textContent.includes('Saved rule updated')"
        )
        assert dialogs == [
            "This item has a different saved classification. Update the saved rule to this choice?"
        ]
        assert rule_requests[0]["headers"]["x-csrf-token"] == "review-page-csrf"
        assert rule_requests[0]["body"]["disposition_subtype"] == "DIRECT_EXPENSE"
        assert rule_requests[0]["body"]["reason"] == "Updated from receipt review"
        assert requests[0]["headers"]["x-csrf-token"] == "review-page-csrf"
        assert requests[0]["body"]["disposition"] == "ORDINARY_BUSINESS_PURCHASE"
        assert requests[0]["body"]["disposition_subtype"] == "DIRECT_EXPENSE"
        for width in (1280, 390):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_rm_023_manager_review_displays_candidates_and_corrects_without_approval(
    tmp_path: Path,
    page: Page,
) -> None:
    engine, session_factory = _database(tmp_path / "rm-023-evidence-review.db")
    with session_factory.begin() as session:
        manager = create_user(session, "rm023-review-manager", "synthetic password", Role.MANAGER)
        token, _ = create_session(session, manager)
        receipt = persist_extracted_receipt(
            session,
            normalize_receipt(
                {
                    "receipt": {
                        "store": "Synthetic Evidence Market",
                        "date": "2026-10-02",
                        "time": "09:30:00",
                        "transaction_number": "RM023-REVIEW-1",
                        "subtotal": "1.00",
                        "tax": "0.06",
                        "total": "1.06",
                        "reference_candidates": {
                            "transaction_reference": "0002",
                            "printed_reference": "0003",
                        },
                    },
                    "items": [
                        {
                            "description": "Synthetic packaged item",
                            "store_product_id": "12345678",
                            "upc": "00012345",
                            "quantity": None,
                            "weight_lb": None,
                            "printed_size": None,
                            "line_total": "1.00",
                            "identifier_candidate": "12345678",
                            "raw_line_text": (
                                "ITEM # 12345678 UPC: 00012345 18 OZ; "
                                "native amount $1.00; OCR amount $1.06"
                            ),
                        }
                    ],
                    "extraction": {
                        "field_candidates": {
                            "total": {
                                "native": "1.00",
                                "ocr": "1.06",
                                "selected": "1.06",
                                "selected_source": "OCR",
                            }
                        },
                        "field_sources": {"total": "OCR"},
                        "issues": ["AMBIGUOUS_PRINTED_TIMESTAMPS"],
                        "missing_fields": [],
                    },
                }
            ),
        )
        receipt_pk = receipt.receipt_pk

    app.dependency_overrides[get_session] = _session_override(session_factory)
    try:
        response = TestClient(app).get(
            f"/api/v1/receipts/{receipt_pk}/review",
            headers={"Cookie": f"mbs_session={token}"},
        )
        assert response.status_code == 200
        correction_requests: list[dict[str, Any]] = []
        approval_requests: list[str] = []

        def route_correction(route: Any) -> None:
            correction_requests.append(
                {"headers": route.request.headers, "body": route.request.post_data_json}
            )
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"status": "UPDATED", "document_version": 2}),
            )

        page.context.add_cookies(
            [{"name": "mbs_csrf", "value": "rm023-review-csrf", "url": "http://testserver"}]
        )
        page.route("**/corrections", route_correction)
        page.route("**/approval", lambda route: approval_requests.append(route.request.url))
        page.route("http://testserver/", lambda route: route.fulfill(body=response.text))
        page.goto("http://testserver/")
        page.set_content(response.text)

        assert page.locator('.line[data-approved="false"]').count() == 1
        evidence = page.locator("[data-extraction-evidence]")
        assert evidence.count() == 1
        evidence.locator("summary").click()
        assert "1.00" in evidence.inner_text()
        assert "1.06" in evidence.inner_text()
        assert "OCR" in evidence.inner_text()
        assert "0002" in evidence.inner_text()
        line = page.locator(".line").first
        raw_line_evidence = line.locator("[data-line-evidence]")
        raw_line_evidence.locator("summary").click()
        assert "12345678" in raw_line_evidence.inner_text()
        assert "00012345" in raw_line_evidence.inner_text()
        assert "18 OZ" in raw_line_evidence.inner_text()
        assert "AMBIGUOUS_PRINTED_TIMESTAMPS" in page.locator(".review-warning").inner_text()

        correction = line.locator(".correction-form")
        correction.locator("input[name='upc']").fill("000123456789")
        correction.locator("textarea[name='reason']").fill("Verified printed UPC")
        correction.get_by_role("button", name="Save line correction").click()
        correction.locator("[role='status']").filter(has_text="Saved version 2").wait_for()
        assert correction_requests[0]["body"]["item_updates"]["0"]["upc"] == "000123456789"
        assert correction_requests[0]["headers"]["x-csrf-token"] == "rm023-review-csrf"
        assert correction_requests[0]["body"]["reason"] == "Verified printed UPC"
        assert approval_requests == []
        for width in (1280, 390):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_directory_batch_page_previews_folder_and_shows_idempotent_replay(
    tmp_path: Path,
    page: Page,
) -> None:
    engine, session_factory = _database(tmp_path / "directory-batch-page.db")
    with session_factory.begin() as session:
        manager = create_user(session, "directory-page-manager", "synthetic password", Role.MANAGER)
        token, _ = create_session(session, manager)
        viewer = create_user(session, "directory-page-viewer", "synthetic password", Role.VIEWER)
        viewer_token, _ = create_session(session, viewer)

    selected_root = tmp_path / "selected-folder"
    nested_folder = selected_root / "nested"
    nested_folder.mkdir(parents=True)
    (nested_folder / "synthetic.pdf").write_bytes(_synthetic_pdf(1))
    image_buffer = BytesIO()
    Image.new("RGB", (16, 12), color=(35, 110, 70)).save(image_buffer, format="PNG")
    (selected_root / "synthetic.png").write_bytes(image_buffer.getvalue())

    app.dependency_overrides[get_session] = _session_override(session_factory)
    try:
        response = TestClient(app).get(
            "/api/v1/receipts/upload/page",
            headers={"Cookie": f"mbs_session={token}"},
        )
        viewer_response = TestClient(app).get(
            "/api/v1/receipts/upload/page",
            headers={"Cookie": f"mbs_session={viewer_token}"},
        )
        assert response.status_code == 200
        assert viewer_response.status_code == 403
        requests: list[dict[str, Any]] = []
        status_requests: list[str] = []

        def route_batch(route: Any) -> None:
            requests.append(
                {
                    "headers": route.request.headers,
                    "body": route.request.post_data or "",
                }
            )
            replay = len(requests) == 2
            possible_match = len(requests) == 3
            files = [
                {
                    "filename": "synthetic.pdf",
                    "status": "POSSIBLE_DUPLICATE",
                    "upload_pk": "upload-1",
                    "idempotent": False,
                },
                {
                    "filename": "synthetic.png",
                    "status": "EXACT_DUPLICATE",
                    "upload_pk": "upload-2",
                    "idempotent": True,
                },
            ] if possible_match else [
                {
                    "filename": "synthetic.pdf",
                    "status": "EXACT_DUPLICATE",
                    "upload_pk": "upload-1",
                    "idempotent": True,
                },
                {
                    "filename": "synthetic.png",
                    "status": "EXACT_DUPLICATE",
                    "upload_pk": "upload-2",
                    "idempotent": True,
                },
            ] if replay else [
                {
                    "filename": "synthetic.pdf",
                    "status": "QUEUED",
                    "upload_pk": "upload-1",
                    "idempotent": False,
                },
                {
                    "filename": "synthetic.png",
                    "status": "QUEUED",
                    "upload_pk": "upload-2",
                    "idempotent": False,
                },
            ]
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"file_count": 2, "total_bytes": 200, "files": files}),
            )

        def route_status(route: Any) -> None:
            status_requests.append(route.request.url)
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "upload_pk": route.request.url.rsplit("/", 2)[-2],
                        "status": "REVIEW",
                        "ocr_attempts": 1,
                        "order_summary": {
                            "added": 1,
                            "source_review": 0,
                            "held": 1,
                            "already_associated": 0,
                        },
                        "orders": [
                            {"order_index": 1, "status": "ADDED", "issue_codes": []},
                            {
                                "order_index": 2,
                                "status": "HELD",
                                "issue_codes": ["MISSING_TRANSACTION_NUMBER"],
                            },
                        ],
                    }
                ),
            )

        resolutions: list[dict[str, Any]] = []

        def route_near_match_resolution(route: Any) -> None:
            resolutions.append(
                {
                    "headers": route.request.headers,
                    "body": route.request.post_data_json,
                }
            )
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {"upload_pk": "upload-1", "status": "QUEUED", "idempotent": False}
                ),
            )

        page.context.add_cookies(
            [{"name": "mbs_csrf", "value": "directory-batch-csrf", "url": "http://testserver"}]
        )
        page.route("**/api/v1/receipts/upload-batch", route_batch)
        page.route("**/api/v1/receipt-uploads/*/status", route_status)
        page.route("**/api/v1/receipt-uploads/*/resolve-near-match", route_near_match_resolution)
        page.route("http://testserver/", lambda route: route.fulfill(body=response.text))
        page.goto("http://testserver/")
        page.set_content(response.text)
        directory_input = page.locator("[data-directory-input]")
        directory_input.set_input_files(str(selected_root))
        assert page.locator("[data-selection-summary]").inner_text() == "2 files selected"
        selection = page.locator("[data-selection-list]").inner_text()
        assert "nested/synthetic.pdf" in selection
        assert "synthetic.png" in selection

        upload_button = page.locator("[data-upload-button]")
        upload_button.click()
        page.wait_for_function(
            "document.querySelector('[data-result-list]').innerText.includes('Order 2: HELD')"
        )
        assert page.locator("[data-result-list]").inner_text().count("REVIEW") == 2
        assert page.locator("[data-result-list]").inner_text().count("Order 1: ADDED") == 2
        assert page.locator("[data-result-list]").inner_text().count("Order 2: HELD") == 2
        assert len(status_requests) == 2
        assert requests[0]["headers"]["x-csrf-token"] == "directory-batch-csrf"
        assert "nested/synthetic.pdf" in requests[0]["body"]

        upload_button.click()
        page.wait_for_function(
            "document.querySelector('[data-result-list]').innerText.includes('EXACT_DUPLICATE')"
        )
        assert page.locator("[data-result-list]").inner_text().count("Already received") == 2
        assert len(status_requests) == 4
        assert requests[1]["headers"]["x-csrf-token"] == "directory-batch-csrf"

        upload_button.click()
        page.get_by_role("button", name="Process as new").wait_for()
        assert "POSSIBLE_DUPLICATE" in page.locator("[data-result-list]").inner_text()
        page.get_by_role("button", name="Process as new").click()
        page.wait_for_function(
            "document.querySelector('[data-result-list]').innerText.includes('Order 2: HELD')"
        )
        assert resolutions[0]["headers"]["x-csrf-token"] == "directory-batch-csrf"
        assert resolutions[0]["body"] == {"process_as_new": True}
        assert len(status_requests) == 6
        for width in (1280, 390):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_repeat_item_can_be_personal_and_expense_reroute_stays_held(
    tmp_path: Path,
    page: Page,
) -> None:
    engine, session_factory = _database(tmp_path / "receipt-review-reroute-ui.db")
    with session_factory.begin() as session:
        manager = create_user(session, "reroute-ui-manager", "synthetic password", Role.MANAGER)
        token, _ = create_session(session, manager)
        receipt = persist_extracted_receipt(
            session,
            normalize_receipt(
                {
                    "receipt": {
                        "store": "Synthetic Review Market",
                        "date": "2026-09-30",
                        "time": "14:05:06",
                        "transaction_number": "REVIEW-REROUTE-1",
                        "total": "4.00",
                    },
                    "items": [
                        {
                            "description": "Cups",
                            "line_total": "2.00",
                            "store_product_id": "CUPS-REPEAT-1",
                        },
                        {
                            "description": "Cups",
                            "line_total": "2.00",
                            "store_product_id": "CUPS-REPEAT-1",
                        },
                    ],
                }
            ),
        )
        lines = list(
            session.scalars(
                select(ReceiptItem)
                .where(ReceiptItem.receipt_pk == receipt.receipt_pk)
                .order_by(ReceiptItem.id)
            )
        )
        assert len(lines) == 2
        store_item = session.get(StoreItem, lines[0].store_item_id)
        assert store_item is not None
        confirm_store_item_mapping(
            session, store_item.store_item_id, store_item.item_id, manager.id
        )
        approve_receipt_item(
            session,
            lines[0].id,
            manager.id,
            BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
            "repeat-item-expense",
            DispositionSubtype.DIRECT_EXPENSE,
        )
        receipt_pk = receipt.receipt_pk
        first_line_id, second_line_id = lines[0].id, lines[1].id

    app.dependency_overrides[get_session] = _session_override(session_factory)
    try:
        response = TestClient(app).get(
            f"/api/v1/receipts/{receipt_pk}/review",
            headers={"Cookie": f"mbs_session={token}"},
        )
        assert response.status_code == 200
        requests: list[dict[str, Any]] = []

        def route_approval(route: Any) -> None:
            requests.append(
                {
                    "url": route.request.url,
                    "headers": route.request.headers,
                    "body": route.request.post_data_json,
                }
            )
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "posting_kind": "NO_POST",
                        "posting_status": "NO_POST",
                        "disposition_subtype": "NONE",
                    }
                ),
            )

        def route_reroute(route: Any) -> None:
            requests.append(
                {
                    "url": route.request.url,
                    "headers": route.request.headers,
                    "body": route.request.post_data_json,
                }
            )
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "posting_kind": "DIRECT_SELL_RESTOCK",
                        "posting_status": "HELD",
                        "disposition_subtype": "DIRECT_SELL_RESTOCK",
                    }
                ),
            )

        page.context.add_cookies(
            [{"name": "mbs_csrf", "value": "reroute-ui-csrf", "url": "http://testserver"}]
        )
        page.route("**/items/*/approval", route_approval)
        page.route("**/items/*/reroute", route_reroute)
        page.route("http://testserver/", lambda route: route.fulfill(body=response.text))
        page.goto("http://testserver/")
        page.set_content(response.text)

        first = page.locator(f'.line[data-line-id="{first_line_id}"]')
        second = page.locator(f'.line[data-line-id="{second_line_id}"]')
        assert first.get_by_role("button", name="Request reroute").is_visible()
        assert second.locator("select[name='disposition']").input_value() == (
            "ORDINARY_BUSINESS_PURCHASE"
        )
        assert (
            second.locator("select[name='disposition_subtype']").input_value() == "DIRECT_EXPENSE"
        )
        assert second.get_by_role("button", name="Approve line").is_visible()
        assert len(requests) == 0

        second.locator("select[name='disposition']").select_option("PERSONAL_NON_BUSINESS")
        assert second.locator("select[name='disposition_subtype']").input_value() == "NONE"
        second.get_by_role("button", name="Approve line").click()
        page.wait_for_function(
            f"document.querySelector('.line[data-line-id=\\\"{second_line_id}\\\"] .message')"
            ".textContent.includes('Routing')"
        )

        first.locator("select[name='disposition_subtype']").select_option("DIRECT_SELL_RESTOCK")
        first.locator("input[name='reason']").fill("Resale stock confirmed by manager")
        first.get_by_role("button", name="Request reroute").click()
        page.wait_for_function(
            "document.querySelector('.line .message').textContent.includes('Held:')"
        )
        assert requests[0]["body"]["disposition"] == "PERSONAL_NON_BUSINESS"
        assert requests[0]["body"]["disposition_subtype"] == "NONE"
        assert requests[0]["headers"]["x-csrf-token"] == "reroute-ui-csrf"
        assert requests[1]["body"]["disposition_subtype"] == "DIRECT_SELL_RESTOCK"
        assert requests[1]["body"]["reason"] == "Resale stock confirmed by manager"
        assert requests[1]["headers"]["x-csrf-token"] == "reroute-ui-csrf"
        assert "HELD" in first.locator(".status").inner_text()
        for width in (1280, 390):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_source_viewer_navigates_and_saves_manager_source_decision(
    tmp_path: Path,
    page: Page,
) -> None:
    engine, session_factory = _database(tmp_path / "receipt-source-review-ui.db")
    with session_factory.begin() as session:
        manager = create_user(
            session, "source-review-ui-manager", "synthetic password", Role.MANAGER
        )
        token, _ = create_session(session, manager)
        primary_upload = ReceiptUpload(
            source_sha256="a" * 64,
            file_key="receipts/a.pdf",
            media_type="application/pdf",
            size_bytes=100,
            uploaded_by=manager.id,
            processing_status="SUCCEEDED",
            page_count=3,
        )
        session.add(primary_upload)
        session.flush()
        receipt = persist_extracted_receipt(
            session,
            normalize_receipt(
                {
                    "receipt": {
                        "store": "Synthetic Review Market",
                        "date": "2026-09-30",
                        "time": "14:05:06",
                        "transaction_number": "SOURCE-REVIEW-UI-1",
                        "subtotal": "2.00",
                        "tax": "0.00",
                        "total": "2.00",
                    },
                    "items": [
                        {
                            "description": "Cups",
                            "line_total": "2.00",
                            "store_product_id": "CUPS-UI-1",
                        }
                    ],
                }
            ),
            primary_upload,
        )
        receipt.raw_ocr_document = {
            **receipt.raw_ocr_document,
            "extraction": {
                "field_confidence": {
                    "store": "0.40",
                    "date": "0.90",
                    "time": "0.90",
                    "transaction_number": "0.50",
                    "total": "0.95",
                    "items": "0.90",
                },
                "missing_fields": ["transaction_number"],
            },
        }
        receipt.receipt_document = {**receipt.receipt_document, "total_mismatch": True}
        primary_line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
        )
        assert primary_line is not None and primary_line.store_item_id is not None
        remembered_item = session.get(StoreItem, primary_line.store_item_id)
        assert remembered_item is not None
        remembered_item.remembered_pack_size = Decimal("1")
        remembered_item.remembered_pack_unit = "PINT"
        pending_upload = ReceiptUpload(
            source_sha256="b" * 64,
            file_key="receipts/b.png",
            media_type="image/png",
            size_bytes=100,
            uploaded_by=manager.id,
            processing_status="REVIEW",
            page_count=1,
        )
        session.add(pending_upload)
        session.flush()
        pending_source = persist_source_candidate(
            session,
            normalize_receipt(
                {
                    "receipt": {
                        "store": "Synthetic Review Market",
                        "date": "2026-09-30",
                        "time": "14:05:06",
                        "transaction_number": "SOURCE-REVIEW-UI-1",
                        "subtotal": "2.00",
                        "tax": "0.00",
                        "total": "2.00",
                    },
                    "items": [
                        {
                            "description": "Cups",
                            "line_total": "2.00",
                            "store_product_id": "CUPS-UI-1",
                        }
                    ],
                }
            ),
            pending_upload,
            receipt,
        )
        receipt_pk = receipt.receipt_pk
        pending_source_id = pending_source.id

    app.dependency_overrides[get_session] = _session_override(session_factory)
    try:
        synthetic_pdf = _synthetic_pdf(3)
        response = TestClient(app).get(
            f"/api/v1/receipts/{receipt_pk}/review",
            headers={"Cookie": f"mbs_session={token}"},
        )
        assert response.status_code == 200
        assert "Line totals do not reconcile" in response.text
        requests: list[dict[str, Any]] = []
        correction_requests: list[dict[str, Any]] = []
        decision_attempts = 0

        def route_source(route: Any) -> None:
            if str(pending_source_id) in route.request.url:
                buffer = BytesIO()
                Image.new("RGB", (2, 2), color=(10, 120, 70)).save(buffer, format="PNG")
                route.fulfill(status=200, content_type="image/png", body=buffer.getvalue())
            else:
                route.fulfill(
                    status=200,
                    content_type="application/pdf",
                    body=synthetic_pdf,
                )

        def route_decision(route: Any) -> None:
            nonlocal decision_attempts
            decision_attempts += 1
            decision_body = route.request.post_data_json
            requests.append(
                {
                    "headers": route.request.headers,
                    "body": decision_body,
                    "url": route.request.url,
                }
            )
            if decision_attempts <= 2:
                route.fulfill(
                    status=503,
                    content_type="application/json",
                    body=json.dumps({"detail": f"Temporary decision failure {decision_attempts}"}),
                )
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"association_kind": decision_body["decision"], "held": False}),
            )

        def route_correction(route: Any) -> None:
            correction_requests.append(
                {
                    "headers": route.request.headers,
                    "body": route.request.post_data_json,
                }
            )
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"status": "UPDATED", "document_version": 2}),
            )

        page.context.add_cookies(
            [{"name": "mbs_csrf", "value": "source-review-ui-csrf", "url": "http://testserver"}]
        )
        page.route("**/sources/*/content", route_source)
        page.route("**/sources/*/decision", route_decision)
        page.route("**/corrections", route_correction)
        page.route("http://testserver/", lambda route: route.fulfill(body=response.text))
        browser_errors: list[str] = []
        browser_requests: list[str] = []
        page.on("pageerror", lambda error: browser_errors.append(str(error)))
        page.on("request", lambda request: browser_requests.append(request.url))
        page.goto("http://testserver/")
        page.set_content(response.text)
        assert page.locator("label.needs-review input[name='store']").count() == 1
        assert page.locator("label.needs-review input[name='transaction_number']").count() == 1

        selector = page.locator("[data-source-select]")
        frame = page.locator("[data-source-frame]")
        assert selector.count() == 1
        assert "#page=1" in str(frame.get_attribute("src"))
        assert page.locator("[data-page-number]").get_attribute("max") == "3"
        page.locator("[data-page-next]").click()
        assert page.locator("[data-page-number]").input_value() == "2"
        assert "#page=2" in str(frame.get_attribute("src")), browser_errors
        page.locator("[data-source-zoom]").evaluate(
            "element => { element.value = '130'; "
            "element.dispatchEvent(new Event('input', {bubbles: true})); }"
        )
        assert "scale(1.3)" in str(frame.get_attribute("style"))
        page.locator("[data-source-rotate]").click()
        assert page.locator("[data-source-rotate]").get_attribute("data-rotation") == "90"
        selector.select_option(str(pending_source_id))
        image = page.locator("[data-source-image]")
        assert image.is_visible()
        assert "sources/2/content" in str(image.get_attribute("src"))
        assert page.locator("[data-page-number]").get_attribute("max") == "1"

        decision_form = page.locator(f'.source-decision[data-source-id="{pending_source_id}"]')
        decision_form.locator("select[name='decision']").select_option("SUPPLEMENT")
        decision_form.locator("input[name='confirmed_repeated_line_indexes']").check()
        decision_form.locator("textarea[name='reason']").fill(
            "The scan overlaps the accepted source"
        )
        decision_form.get_by_role("button", name="Save source decision").click()
        page.wait_for_function(
            "document.querySelector('.source-decision [role=\"status\"]')"
            ".textContent.includes('Temporary decision failure 1')"
        )
        decision_form.get_by_role("button", name="Save source decision").click()
        page.wait_for_function(
            "document.querySelector('.source-decision [role=\"status\"]')"
            ".textContent.includes('Temporary decision failure 2')"
        )
        decision_form.locator("textarea[name='reason']").fill(
            "The scan overlaps the accepted source after rechecking"
        )
        with page.expect_navigation(wait_until="load"):
            decision_form.get_by_role("button", name="Save source decision").click()
        assert requests[0]["body"]["decision"] == "SUPPLEMENT"
        assert requests[0]["body"]["reason"] == "The scan overlaps the accepted source"
        assert requests[0]["headers"]["x-csrf-token"] == "source-review-ui-csrf"
        assert requests[0]["body"]["source_event_id"] == requests[1]["body"]["source_event_id"]
        assert requests[1]["body"]["source_event_id"] != requests[2]["body"]["source_event_id"]
        assert requests[2]["body"]["reason"] == (
            "The scan overlaps the accepted source after rechecking"
        )
        assert requests[2]["body"]["confirmed_repeated_line_indexes"] == [0]
        line_correction = page.locator('.correction-form[data-item-index="0"]')
        assert "Remembered package size; verify before saving." in line_correction.inner_text()
        assert page.locator("[data-package-warning]").count() == 1
        assert line_correction.locator("input[name='pack_size']").input_value() == "1.0000"
        assert line_correction.locator("input[name='pack_unit']").input_value() == "PINT"
        line_correction.locator("input[name='package_count']").fill("2")
        line_correction.locator("input[name='pack_size']").fill("1")
        line_correction.locator("input[name='pack_unit']").fill("points")
        line_correction.locator("[data-confirm-unit]").click()
        line_correction.locator("input[name='unit_price']").fill("1.00")
        line_correction.locator("input[name='remember_package_default']").check()
        assert line_correction.locator("[data-calculated-line-total]").inner_text() == "2.00"
        line_correction.locator("textarea[name='reason']").fill("Correct package quantity")
        line_correction.get_by_role("button", name="Save line correction").click()
        page.wait_for_function(
            'document.querySelector(\'.correction-form[data-item-index="0"] [role="status"]\')'
            ".textContent.includes('Saved version 2')"
        )
        correction_body = correction_requests[0]["body"]
        assert correction_body["reason"] == "Correct package quantity"
        assert correction_body["item_updates"] == {
            "0": {
                "package_count": "2",
                "pack_size": "1",
                "pack_unit": "PINT",
                "unit_price": "1.00",
            }
        }
        assert correction_body["remember_package_default_indexes"] == [0]
        assert line_correction.locator("input[name='pack_unit']").input_value() == "PINT"
        assert "line_total" not in correction_body["item_updates"]["0"]
        assert correction_requests[0]["headers"]["x-csrf-token"] == "source-review-ui-csrf"
        addition_form = page.locator("[data-line-addition-form]")
        line_id_value = page.locator(".line").first.get_attribute("data-line-id")
        assert line_id_value is not None
        line_id = int(line_id_value)
        addition_form.locator("input[name='description']").fill("Cups")
        addition_form.locator("input[name='package_count']").fill("1")
        addition_form.locator("input[name='pack_size']").fill("1")
        addition_form.locator("input[name='pack_unit']").fill("points")
        addition_form.locator("[data-confirm-addition-unit]").click()
        addition_form.locator("input[name='unit_price']").fill("0.50")
        addition_form.locator("input[name='confirm_repeated_occurrence']").check()
        source_select = addition_form.locator("select[name='source_id']")
        source_select.select_option(label="PRIMARY")
        selected_source_id = source_select.input_value()
        assert selected_source_id is not None
        primary_source_id = int(selected_source_id)
        addition_form.locator("input[name='source_line_number']").fill("2")
        addition_form.locator("textarea[name='reason']").fill("Add the visible second line")
        assert addition_form.locator("[data-addition-line-total]").inner_text() == "0.50"
        addition_form.get_by_role("button", name="Add line").click()
        page.wait_for_function(
            "document.querySelector('[data-line-addition-form] [role=\"status\"]')"
            ".textContent.includes('Added line')"
        )
        assert addition_form.locator("[data-refresh-review]").is_visible()
        addition_body = correction_requests[1]["body"]
        assert addition_body["item_additions"] == [
            {
                "description": "Cups",
                "category": "Other",
                "store_product_id": None,
                "package_count": "1",
                "pack_size": "1",
                "pack_unit": "PINT",
                "unit_price": "0.50",
                "source_id": primary_source_id,
                "source_page": 1,
                "source_line_number": 2,
                "confirm_repeated_occurrence": True,
                "remember_package_as_default": False,
            }
        ]
        assert addition_body["reason"] == "Add the visible second line"
        assert correction_requests[1]["headers"]["x-csrf-token"] == "source-review-ui-csrf"
        line_correction.locator("textarea[name='reason']").fill("Exclude misread source row")
        with page.expect_navigation(wait_until="load"):
            line_correction.get_by_role("button", name="Exclude bogus line").click()
        assert correction_requests[2]["body"]["item_exclusions"] == [line_id]
        for width in (1280, 390):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not any("ocr" in url.casefold() for url in browser_requests)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_rm_012_upc_and_description_matches_are_suggestions_never_preselected(
    tmp_path: Path,
) -> None:
    engine, session_factory = _database(tmp_path / "remembered-rule-suggestions.db")

    def receipt_for(transaction_number: str, items: list[dict[str, object]]) -> Any:
        return normalize_receipt(
            {
                "receipt": {
                    "store": "Synthetic Rule Market",
                    "date": "2026-09-30",
                    "time": "14:05:06",
                    "transaction_number": transaction_number,
                    "total": str(2 * len(items)) + ".00",
                },
                "items": items,
            }
        )

    with session_factory.begin() as session:
        manager = create_user(session, "rule-manager", "synthetic password", Role.MANAGER)
        token, _ = create_session(session, manager)
        first = persist_extracted_receipt(
            session,
            receipt_for(
                "RULE-1",
                [
                    {
                        "description": "Paper towels",
                        "line_total": "2.00",
                        "store_product_id": "R-1",
                    },
                    {
                        "description": "Cups",
                        "line_total": "2.00",
                        "store_product_id": "R-2",
                        "upc": "123456789012",
                    },
                ],
            ),
        )
        remembered = {
            item.store_product_id: item
            for item in session.scalars(
                select(StoreItem).where(StoreItem.store_product_id.in_(["R-1", "R-2"]))
            )
        }
        remembered["R-1"].last_disposition = "ORDINARY_BUSINESS_PURCHASE"
        remembered["R-2"].last_disposition = "RECIPE_INGREDIENT"
        assert first.receipt_pk
        second = persist_extracted_receipt(
            session,
            receipt_for(
                "RULE-2",
                [
                    {
                        "description": "paper  TOWELS",
                        "line_total": "2.00",
                        "store_product_id": "N-1",
                    },
                    {
                        "description": "Different cups label",
                        "line_total": "2.00",
                        "store_product_id": "N-2",
                        "upc": "123456789012",
                    },
                    {
                        "description": "Mystery item",
                        "line_total": "2.00",
                        "store_product_id": "N-3",
                    },
                ],
            ),
        )
        second_pk = second.receipt_pk

    app.dependency_overrides[get_session] = _session_override(session_factory)
    try:
        html = (
            TestClient(app)
            .get(f"/api/v1/receipts/{second_pk}/review", headers={"Cookie": f"mbs_session={token}"})
            .text
        )
        assert html.count("data-rule-suggestion") == 2
        assert "Matches a remembered item: Ordinary Business Purchase" in html
        assert "Matches a remembered item: Recipe Ingredient" in html
        assert "Suggestion only" in html
        assert html.count('value="RECIPE_INGREDIENT" selected') == 1
        assert 'value="ORDINARY_BUSINESS_PURCHASE" selected' not in html
        with session_factory() as session:
            dispositions = set(
                session.scalars(
                    select(ReceiptItem.business_disposition).where(
                        ReceiptItem.receipt_pk == second_pk
                    )
                )
            )
        assert dispositions == {"UNCLASSIFIED"}
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_receipt_image_candidate_decisions_are_audited_and_replace_is_explicit(
    tmp_path: Path,
    page: Page,
) -> None:
    engine, session_factory = _database(tmp_path / "receipt-image-candidate-review.db")
    file_store = LocalProtectedFileStore(tmp_path / "receipt-image-candidate-review-files")

    def candidate_image(position: int, color: tuple[int, int, int]) -> bytes:
        image = Image.new("RGB", (160, 120), "white")
        ImageDraw.Draw(image).rectangle((position, 10, position + 38, 110), fill=color)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    with session_factory.begin() as session:
        manager = create_user(
            session, "image-candidate-manager", "synthetic password", Role.MANAGER
        )
        viewer = create_user(session, "image-candidate-viewer", "synthetic password", Role.VIEWER)
        manager_token, manager_csrf = create_session(session, manager)
        viewer_token, viewer_csrf = create_session(session, viewer)
        upload = ReceiptUpload(
            source_sha256="a" * 64,
            file_key="receipts/synthetic-source.pdf",
            media_type="application/pdf",
            size_bytes=100,
            uploaded_by=manager.id,
            processing_status="SUCCEEDED",
        )
        session.add(upload)
        session.flush()
        receipt = persist_extracted_receipt(
            session,
            normalize_receipt(
                {
                    "receipt": {
                        "store": "Synthetic Image Market",
                        "date": "2026-09-30",
                        "time": "14:05:06",
                        "transaction_number": "IMAGE-CANDIDATE-1",
                        "total": "2.00",
                    },
                    "items": [
                        {
                            "description": "Cups",
                            "line_total": "2.00",
                            "store_product_id": "CUPS-IMAGE-1",
                        }
                    ],
                }
            ),
            upload,
        )
        line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
        )
        source = session.scalar(
            select(ReceiptSource).where(ReceiptSource.upload_pk == upload.upload_pk)
        )
        assert line is not None and line.item_id is not None
        assert source is not None
        assert line.store_item_id is not None
        store_item = session.get(StoreItem, line.store_item_id)
        assert store_item is not None
        store_item.mapping_confirmed = True
        media_service = MediaAssetService(file_store)
        existing_primary = media_service.stage(
            session, candidate_image(8, (200, 30, 40)), "image/png", manager.id
        )
        keep_candidate = media_service.stage(
            session, candidate_image(62, (20, 130, 40)), "image/png", manager.id
        )
        replace_candidate = media_service.stage(
            session, candidate_image(112, (30, 50, 210)), "image/png", manager.id
        )
        browser_candidate = media_service.stage(
            session, candidate_image(28, (200, 150, 20)), "image/png", manager.id
        )
        rejected_candidate = media_service.stage(
            session, candidate_image(82, (120, 20, 190)), "image/png", manager.id
        )
        unmapped_candidate = media_service.stage(
            session, candidate_image(132, (30, 180, 210)), "image/png", manager.id
        )
        assets = (
            existing_primary,
            keep_candidate,
            replace_candidate,
            browser_candidate,
            rejected_candidate,
            unmapped_candidate,
        )
        assert len({asset.asset_sha256 for asset in assets}) == len(assets)
        for asset in assets:
            media_service.promote(session, asset.asset_sha256)
        session.add(
            MediaAssetLink(
                asset_sha256=existing_primary.asset_sha256,
                owner_kind="ITEM",
                owner_id=line.item_id,
                status="CONFIRMED",
                is_primary=True,
                created_by=manager.id,
            )
        )
        candidate_links = [
            MediaAssetLink(
                asset_sha256=asset.asset_sha256,
                owner_kind="RECEIPT_LINE_CANDIDATE",
                owner_id=f"synthetic-candidate-{index}",
                status="PENDING",
                source_id=source.id,
                receipt_item_id=line.id,
                source_page=1,
                source_region={"bbox": [10, 20, 50, 60]},
                created_by=manager.id,
            )
            for index, asset in enumerate(
                (
                    keep_candidate,
                    replace_candidate,
                    browser_candidate,
                    rejected_candidate,
                    unmapped_candidate,
                ),
                start=1,
            )
        ]
        session.add_all(candidate_links)
        session.flush()
        candidate_ids = [candidate.id for candidate in candidate_links]
        receipt_pk = receipt.receipt_pk
        line_id = line.id

    class ProtectedReader:
        def read_protected_source(self, file_key: str) -> bytes:
            return file_store.read(file_key)

    app.dependency_overrides[get_session] = _session_override(session_factory)
    app.dependency_overrides[get_receipt_upload_service] = lambda: ProtectedReader()
    try:
        with nullcontext(TestClient(app)) as client:
            headers = {
                "Cookie": f"mbs_session={manager_token}",
                "X-CSRF-Token": manager_csrf,
            }
            viewer_headers = {
                "Cookie": f"mbs_session={viewer_token}",
                "X-CSRF-Token": viewer_csrf,
            }
            thumbnail = client.get(
                f"/api/v1/receipts/{receipt_pk}/image-candidates/{candidate_ids[0]}/thumbnail",
                headers=headers,
            )
            assert thumbnail.status_code == 200
            assert thumbnail.headers["cache-control"] == "private, no-store, max-age=0"
            assert thumbnail.headers["x-content-type-options"] == "nosniff"
            rejected_url = (
                f"/api/v1/receipts/{receipt_pk}/image-candidates/{candidate_ids[3]}/decision"
            )
            assert (
                client.post(
                    rejected_url,
                    headers=headers,
                    json={"decision": "REJECT"},
                ).status_code
                == 400
            )
            rejected = client.post(
                rejected_url,
                headers=headers,
                json={"decision": "REJECT", "reason": "Synthetic packaging image"},
            )
            assert rejected.status_code == 200 and rejected.json()["status"] == "REJECTED"
            assert (
                client.post(
                    rejected_url,
                    headers=headers,
                    json={"decision": "REJECT", "reason": "Synthetic packaging image"},
                ).json()["idempotent"]
                is True
            )
            assert (
                client.get(
                    f"/api/v1/receipts/{receipt_pk}/image-candidates/{candidate_ids[0]}/thumbnail",
                    headers=viewer_headers,
                ).status_code
                == 403
            )

            csrf_denied = client.post(
                f"/api/v1/receipts/{receipt_pk}/image-candidates/{candidate_ids[0]}/decision",
                headers={"Cookie": f"mbs_session={manager_token}"},
                json={"decision": "CONFIRM", "receipt_item_id": line_id},
            )
            assert csrf_denied.status_code == 403
            with session_factory.begin() as session:
                pending_line = session.get(ReceiptItem, line_id)
                assert pending_line is not None and pending_line.store_item_id is not None
                pending_store_item = session.get(StoreItem, pending_line.store_item_id)
                assert pending_store_item is not None
                pending_store_item.mapping_confirmed = False
            unmapped_url = (
                f"/api/v1/receipts/{receipt_pk}/image-candidates/{candidate_ids[4]}/decision"
            )
            unmapped_result = client.post(
                unmapped_url,
                headers=headers,
                json={"decision": "CONFIRM", "receipt_item_id": line_id},
            )
            assert unmapped_result.status_code == 200
            assert unmapped_result.json()["is_primary"] is True
            with session_factory.begin() as session:
                pending_line = session.get(ReceiptItem, line_id)
                assert pending_line is not None and pending_line.store_item_id is not None
                pending_store_item = session.get(StoreItem, pending_line.store_item_id)
                assert pending_store_item is not None
                pending_store_item.mapping_confirmed = True

            candidate_url = (
                f"/api/v1/receipts/{receipt_pk}/image-candidates/{candidate_ids[0]}/decision"
            )
            prompt = client.post(
                candidate_url,
                headers=headers,
                json={"decision": "CONFIRM", "receipt_item_id": line_id},
            )
            assert prompt.status_code == 200
            assert prompt.json()["replace_prompt_required"] is True
            with session_factory() as session:
                pending = session.get(MediaAssetLink, candidate_ids[0])
                assert pending is not None and pending.status == "PENDING"

            kept = client.post(
                candidate_url,
                headers=headers,
                json={
                    "decision": "CONFIRM",
                    "receipt_item_id": line_id,
                    "replace_primary": False,
                },
            )
            assert kept.status_code == 200 and kept.json()["is_primary"] is False
            assert (
                client.post(
                    candidate_url,
                    headers=headers,
                    json={
                        "decision": "CONFIRM",
                        "receipt_item_id": line_id,
                        "replace_primary": False,
                    },
                ).json()["idempotent"]
                is True
            )

            replace_url = (
                f"/api/v1/receipts/{receipt_pk}/image-candidates/{candidate_ids[1]}/decision"
            )
            assert (
                client.post(
                    replace_url,
                    headers=headers,
                    json={"decision": "CONFIRM", "receipt_item_id": line_id},
                ).json()["replace_prompt_required"]
                is True
            )
            replaced = client.post(
                replace_url,
                headers=headers,
                json={
                    "decision": "CONFIRM",
                    "receipt_item_id": line_id,
                    "replace_primary": True,
                },
            )
            assert replaced.status_code == 200 and replaced.json()["is_primary"] is True

            review_page = client.get(
                f"/api/v1/receipts/{receipt_pk}/review",
                headers={"Cookie": f"mbs_session={manager_token}"},
            )
            assert review_page.status_code == 200
            browser_requests: list[dict[str, Any]] = []

            def route_candidate_decision(route: Any) -> None:
                payload = route.request.post_data_json
                browser_requests.append({"payload": payload, "headers": route.request.headers})
                body = (
                    {"replace_prompt_required": True}
                    if len(browser_requests) == 1
                    else {
                        "candidate_id": candidate_ids[2],
                        "status": "CONFIRMED",
                        "is_primary": False,
                    }
                )
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(body),
                )

            page.context.add_cookies(
                [{"name": "mbs_csrf", "value": "image-candidate-csrf", "url": "http://testserver"}]
            )
            page.route(
                "http://testserver/",
                lambda route: route.fulfill(
                    status=200, content_type="text/html", body=review_page.text
                ),
            )
            page.route(
                "**/image-candidates/*/thumbnail",
                lambda route: route.fulfill(
                    status=200, content_type="image/png", body=candidate_image(28, (200, 150, 20))
                ),
            )
            page.route("**/image-candidates/*/decision", route_candidate_decision)
            page.route(
                "**/sources/*/content",
                lambda route: route.fulfill(
                    status=200, content_type="application/pdf", body=_synthetic_pdf(1)
                ),
            )
            page.goto("http://testserver/")
            browser_form = page.locator(
                f'[data-image-candidate][data-candidate-id="{candidate_ids[2]}"]'
            )
            browser_form.get_by_role("button", name="Confirm image").click()
            dialog = page.locator("[data-image-replacement-dialog]")
            dialog.wait_for(state="visible")
            assert dialog.locator("p").inner_text() == "Replace the current image?"
            assert page.evaluate("document.activeElement.textContent") == "Keep current primary"
            dialog.get_by_role("button", name="Keep current primary").click()
            page.wait_for_function(
                "document.querySelector('[data-image-candidate][data-candidate-id=\\\""
                + str(candidate_ids[2])
                + "\\\"] [data-candidate-message]').textContent.includes('confirmed')"
            )
            assert browser_requests[0]["payload"].get("replace_primary") is None
            assert browser_requests[1]["payload"]["replace_primary"] is False
            assert browser_requests[1]["headers"]["x-csrf-token"] == "image-candidate-csrf"
            for width in (1280, 390):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

        with session_factory() as session:
            primary_links = session.scalars(
                select(MediaAssetLink).where(
                    MediaAssetLink.owner_kind == "ITEM",
                    MediaAssetLink.owner_id == str(line_id),
                    MediaAssetLink.is_primary.is_(True),
                )
            ).all()
            # Owner identity is the canonical item id, not the receipt line id.
            item_line = session.get(ReceiptItem, line_id)
            assert item_line is not None and item_line.item_id is not None
            primary_links = session.scalars(
                select(MediaAssetLink).where(
                    MediaAssetLink.owner_kind == "ITEM",
                    MediaAssetLink.owner_id == item_line.item_id,
                    MediaAssetLink.is_primary.is_(True),
                )
            ).all()
            store_item_primary = session.scalars(
                select(MediaAssetLink).where(
                    MediaAssetLink.owner_kind == "STORE_ITEM",
                    MediaAssetLink.owner_id == item_line.store_item_id,
                    MediaAssetLink.is_primary.is_(True),
                )
            ).all()
            assert len(primary_links) == 1
            assert len(store_item_primary) == 1
            assert store_item_primary[0].asset_sha256 == unmapped_candidate.asset_sha256
            assert primary_links[0].asset_sha256 != existing_primary.asset_sha256
            assert (
                session.scalar(
                    select(AuditLog).where(
                        AuditLog.event_type == "RECEIPT_IMAGE_CANDIDATE_CONFIRMED"
                    )
                )
                is not None
            )
            rejected_link = session.get(MediaAssetLink, candidate_ids[3])
            assert rejected_link is not None
            assert rejected_link.status == "REJECTED"
            assert rejected_link.rejection_reason == "Synthetic packaging image"
            assert (
                session.scalar(
                    select(AuditLog).where(
                        AuditLog.event_type == "RECEIPT_IMAGE_CANDIDATE_REJECTED"
                    )
                )
                is not None
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _session_override(session_factory: sessionmaker[Session]) -> Any:
    def override_session() -> Any:
        with session_factory() as session:
            yield session

    return override_session
