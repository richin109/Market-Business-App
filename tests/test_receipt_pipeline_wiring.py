from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pymupdf
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import mbs.main as main_module
from mbs.auth import Role, create_session, create_user
from mbs.celery_app import celery_app
from mbs.db import get_session
from mbs.items import confirm_store_item_mapping
from mbs.main import app
from mbs.media_assets import MediaAssetService
from mbs.models import (
    AuditLog,
    CategoryRule,
    MediaAsset,
    MediaAssetLink,
    Receipt,
    ReceiptCorrection,
    ReceiptItem,
    ReceiptLineApproval,
    ReceiptOutboxEvent,
    ReceiptRoutingRecord,
    ReceiptSource,
    ReceiptUpload,
    Setting,
)
from mbs.receipts.approval import DispositionSubtype, approve_receipt_item
from mbs.receipts.duplicates import PillowPerceptualHasher
from mbs.receipts.ocr import BusinessDisposition
from mbs.receipts.pdf_extraction import EmbeddedPDFImage
from mbs.receipts.sources import SourceDecision, decide_receipt_source
from mbs.receipts.storage import LocalProtectedFileStore
from mbs.receipts.tasks import (
    MAX_ATTEMPTS,
    LocalReceiptOCREngine,
    PersistedUploadProcessor,
    configure_persisted_processor,
    dispatch_pending_receipt_uploads,
    process_receipt_upload,
)
from mbs.receipts.upload import UploadStatus
from mbs.routers import receipts as receipt_routes
from tests.database import postgres_test_url


def _png(color: tuple[int, int, int] = (30, 100, 170)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 6), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _pdf_with_label(label: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((48, 72), label)
    result = cast(bytes, document.tobytes())
    document.close()
    return result


def _multi_order_pdf(order_count: int) -> bytes:
    blocks = []
    for order_number in range(1, order_count + 1):
        blocks.append(
            "\n".join(
                [
                    "Amazon",
                    "Order placed October 2, 2026",
                    f"Order # SYN-ORDER-{order_number:03d}",
                    f"Time: 09:{order_number:02d} AM",
                    "Payment method Visa",
                    "Item (1) Subtotal: $1.00",
                    "Estimated tax: $0.06",
                    "Order total: $1.06",
                    "Delivered October 2, 2026",
                    f"Synthetic item {order_number:03d}",
                    "Quantity: 1",
                    "Size: 1 CT",
                    f"ASIN: SYN-ITEM-{order_number:03d}",
                    f"UPC: {order_number:012d}",
                    "$1.00",
                ]
            )
        )
    document = pymupdf.open()
    page = document.new_page(width=612, height=4000)
    page.insert_textbox(pymupdf.Rect(30, 30, 582, 3970), "\n".join(blocks), fontsize=9)
    source = cast(bytes, document.tobytes())
    document.close()
    return source


def _multi_order_image(order_count: int) -> bytes:
    font = ImageFont.load_default(size=22)
    image = Image.new("RGB", (1200, max(600, order_count * 400)), "white")
    draw = ImageDraw.Draw(image)
    text = []
    for order_number in range(1, order_count + 1):
        text.extend(
            [
                "Amazon",
                "Order placed October 2, 2026",
                f"Order # SYN-ORDER-{order_number:03d}",
                f"Time: 09:{order_number:02d} AM",
                "Payment method Visa",
                "Item (1) Subtotal: $1.00",
                "Estimated tax: $0.06",
                "Order total: $1.06",
                "Delivered October 2, 2026",
                f"Synthetic item {order_number:03d}",
                "Quantity: 1",
                "Size: 1 CT",
                f"ASIN: SYN-ITEM-{order_number:03d}",
                f"UPC: {order_number:012d}",
                "$1.00",
                "",
            ]
        )
    for line_number, line in enumerate(text):
        draw.text((40, 30 + line_number * 24), line, fill="black", font=font)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _multi_order_text(order_count: int) -> str:
    return "\n".join(
        line
        for order_number in range(1, order_count + 1)
        for line in (
            "Amazon",
            "Order placed October 2, 2026",
            f"Order # SYN-ORDER-{order_number:03d}",
            f"Time: 09:{order_number:02d} AM",
            "Payment method Visa",
            "Item (1) Subtotal: $1.00",
            "Estimated tax: $0.06",
            "Order total: $1.06",
            "Delivered October 2, 2026",
            f"Synthetic item {order_number:03d}",
            "Quantity: 1",
            "Size: 1 CT",
            f"ASIN: SYN-ITEM-{order_number:03d}",
            f"UPC: {order_number:012d}",
            "$1.00",
        )
    )


def _near_match_png(offset: int = 0) -> bytes:
    image = Image.new("RGB", (64, 64), "white")
    ImageDraw.Draw(image).rectangle((16 + offset, 16, 48 + offset, 48), fill="black")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _document(transaction_number: str = "SYN-801") -> dict[str, Any]:
    return {
        "receipt": {
            "store": "Synthetic Market",
            "date": "2026-09-30",
            "time": "14:05:06",
            "transaction_number": transaction_number,
            "total": "1.00",
        },
        "items": [{"description": "Milk", "line_total": "1.00"}],
    }


def _database(path: Path) -> tuple[Any, sessionmaker[Session]]:
    engine = create_engine(postgres_test_url(path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(path).replace("%", "%%"))
    command.upgrade(config, "head")
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_real_app_stages_upload_before_dispatch_and_never_runs_ocr(
    tmp_path: Path, monkeypatch: Any
) -> None:
    database_path = tmp_path / "receipt-pipeline.db"
    engine, session_factory = _database(database_path)
    storage_path = tmp_path / "protected"
    monkeypatch.setenv("RECEIPT_STORAGE_PATH", str(storage_path))
    dispatched: list[str] = []

    with session_factory.begin() as session:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        viewer = create_user(session, "viewer", "viewer password", Role.VIEWER)
        manager_token, manager_csrf = create_session(session, manager)
        viewer_token, viewer_csrf = create_session(session, viewer)

    manager_token_hash = manager_token
    viewer_token_hash = viewer_token

    def override_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    def dispatch_after_commit() -> None:
        with session_factory() as session:
            upload = session.scalar(select(ReceiptUpload))
            event = session.scalar(select(ReceiptOutboxEvent))
            assert upload is not None and upload.processing_status == "QUEUED"
            assert event is not None and event.upload_pk == upload.upload_pk
        if dispatch_pending_receipt_uploads.run() == 1:
            dispatched.append(upload.upload_pk)

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    monkeypatch.setattr("mbs.receipts.tasks.SessionLocal", session_factory)
    monkeypatch.setattr(process_receipt_upload, "delay", lambda key: None)
    monkeypatch.setattr(receipt_routes, "_request_outbox_dispatch", dispatch_after_commit)
    try:
        with TestClient(app) as client:
            source = _png()
            missing_csrf = client.post(
                "/api/v1/receipts/upload",
                content=source,
                headers={
                    "Content-Type": "image/png",
                    "Cookie": f"mbs_session={manager_token_hash}",
                },
            )
            viewer_response = client.post(
                "/api/v1/receipts/upload",
                content=source,
                headers={
                    "Content-Type": "image/png",
                    "Cookie": f"mbs_session={viewer_token_hash}",
                    "X-CSRF-Token": viewer_csrf,
                },
            )
            queued = client.post(
                "/api/v1/receipts/upload",
                content=source,
                headers={
                    "Content-Type": "image/png",
                    "Cookie": f"mbs_session={manager_token_hash}",
                    "X-CSRF-Token": manager_csrf,
                },
            )
            pdf_blocked = client.post(
                "/api/v1/receipts/upload",
                content=b"%PDF-1.7 synthetic",
                headers={
                    "Content-Type": "application/pdf",
                    "Cookie": f"mbs_session={manager_token_hash}",
                    "X-CSRF-Token": manager_csrf,
                },
            )
            oversized = client.post(
                "/api/v1/receipts/upload",
                content=b"x" * (10_000_001),
                headers={
                    "Content-Type": "image/png",
                    "Cookie": f"mbs_session={manager_token_hash}",
                    "X-CSRF-Token": manager_csrf,
                },
            )
            retry = client.post(
                "/api/v1/receipts/upload",
                content=source,
                headers={
                    "Content-Type": "image/png",
                    "Cookie": f"mbs_session={manager_token_hash}",
                    "X-CSRF-Token": manager_csrf,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert missing_csrf.status_code == 403
    assert viewer_response.status_code == 403
    assert queued.status_code == 200
    assert queued.json()["status"] == UploadStatus.QUEUED.value
    assert pdf_blocked.status_code == 503
    assert oversized.status_code == 413
    assert retry.status_code == 200
    assert retry.json()["idempotent"] is True
    assert retry.json()["upload_pk"] == queued.json()["upload_pk"]
    assert dispatched == [queued.json()["upload_pk"]]
    with session_factory() as session:
        assert session.scalar(select(func.count(ReceiptUpload.upload_pk))) == 1
        assert session.scalar(select(func.count(ReceiptOutboxEvent.id))) == 1
        assert session.scalar(select(func.count(Receipt.receipt_pk))) == 0
        upload = session.get(ReceiptUpload, queued.json()["upload_pk"])
        event = session.scalar(select(ReceiptOutboxEvent))
        assert upload is not None and upload.staging_file_key is None
        assert event is not None and event.dispatched_at is not None
    assert (storage_path / queued.json()["file_key"]).is_file()
    engine.dispose()


def test_directory_batch_upload_replay_is_per_file_idempotent_and_reports_partial_failure(
    tmp_path: Path, monkeypatch: Any
) -> None:
    engine, session_factory = _database(tmp_path / "directory-batch-upload.db")
    storage_path = tmp_path / "directory-batch-files"
    monkeypatch.setenv("RECEIPT_STORAGE_PATH", str(storage_path))
    dispatch_count = 0
    with session_factory.begin() as session:
        manager = create_user(session, "directory-batch-manager", "manager password", Role.MANAGER)
        token, csrf = create_session(session, manager)
        viewer = create_user(session, "directory-batch-viewer", "viewer password", Role.VIEWER)
        viewer_token, viewer_csrf = create_session(session, viewer)

    def override_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    def dispatch_after_commit() -> None:
        nonlocal dispatch_count
        dispatch_count += 1

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    monkeypatch.setattr("mbs.receipts.tasks.SessionLocal", session_factory)
    monkeypatch.setattr(receipt_routes, "_request_outbox_dispatch", dispatch_after_commit)
    try:
        with TestClient(app) as client:
            headers = {
                "Cookie": f"mbs_session={token}",
                "X-CSRF-Token": csrf,
            }
            missing_csrf = client.post(
                "/api/v1/receipts/upload-batch",
                files=[("files", ("nested/receipt.png", _near_match_png(), "image/png"))],
                headers={"Cookie": f"mbs_session={token}"},
            )
            viewer_response = client.post(
                "/api/v1/receipts/upload-batch",
                files=[("files", ("nested/receipt.png", _near_match_png(), "image/png"))],
                headers={
                    "Cookie": f"mbs_session={viewer_token}",
                    "X-CSRF-Token": viewer_csrf,
                },
            )
            first = client.post(
                "/api/v1/receipts/upload-batch",
                files=[
                    ("files", ("first/receipt.png", _near_match_png(), "image/png")),
                    ("files", ("second/unsupported.txt", b"synthetic text", "text/plain")),
                ],
                headers=headers,
            )
            replay = client.post(
                "/api/v1/receipts/upload-batch",
                files=[
                    ("files", ("first/receipt.png", _near_match_png(), "image/png")),
                    ("files", ("second/unsupported.txt", b"synthetic text", "text/plain")),
                ],
                headers=headers,
            )
    finally:
        app.dependency_overrides.clear()

    assert missing_csrf.status_code == 403
    assert viewer_response.status_code == 403
    assert first.status_code == 200
    assert first.json()["file_count"] == 2
    assert [result["status"] for result in first.json()["files"]] == ["QUEUED", "INVALID"]
    assert replay.status_code == 200
    assert [result["status"] for result in replay.json()["files"]] == [
        "EXACT_DUPLICATE",
        "INVALID",
    ]
    assert replay.json()["files"][0]["upload_pk"] == first.json()["files"][0]["upload_pk"]
    assert replay.json()["files"][0]["idempotent"] is True
    assert dispatch_count == 1
    with session_factory() as session:
        assert session.scalar(select(func.count(ReceiptUpload.upload_pk))) == 1
        assert session.scalar(select(func.count(ReceiptOutboxEvent.id))) == 1
        assert session.scalar(select(func.count(Receipt.receipt_pk))) == 0
    engine.dispose()


def test_concurrent_batch_retries_create_one_upload_and_outbox_event(
    tmp_path: Path, monkeypatch: Any
) -> None:
    engine, session_factory = _database(tmp_path / "concurrent-batch-retry.db")
    monkeypatch.setenv("RECEIPT_STORAGE_PATH", str(tmp_path / "concurrent-batch-files"))
    with session_factory.begin() as session:
        manager = create_user(
            session, "concurrent-batch-manager", "synthetic password", Role.MANAGER
        )
        token, csrf = create_session(session, manager)

    def override_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    dispatches: list[None] = []
    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    monkeypatch.setattr("mbs.receipts.tasks.SessionLocal", session_factory)
    monkeypatch.setattr(receipt_routes, "_request_outbox_dispatch", lambda: dispatches.append(None))
    source = _near_match_png()
    try:
        with TestClient(app) as client:

            def submit_batch() -> Any:
                return client.post(
                    "/api/v1/receipts/upload-batch",
                    files=[("files", ("retry.png", source, "image/png"))],
                    headers={
                        "Cookie": f"mbs_session={token}",
                        "X-CSRF-Token": csrf,
                    },
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(submit_batch), pool.submit(submit_batch)]
                responses = [future.result() for future in futures]

        assert all(response.status_code == 200 for response in responses)
        file_results = [response.json()["files"][0] for response in responses]
        assert sorted(result["status"] for result in file_results) == [
            "EXACT_DUPLICATE",
            "QUEUED",
        ]
        assert len({result["upload_pk"] for result in file_results}) == 1
        assert sum(not result["idempotent"] for result in file_results) == 1
        assert len(dispatches) == 1
        with session_factory() as session:
            assert session.scalar(select(func.count(ReceiptUpload.upload_pk))) == 1
            assert session.scalar(select(func.count(ReceiptOutboxEvent.id))) == 1
            assert session.scalar(select(func.count(Receipt.receipt_pk))) == 0
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_worker_processes_changed_single_image_versions_without_duplicate_receipts(
    tmp_path: Path,
) -> None:
    engine, session_factory = _database(tmp_path / "changed-image-order-versions.db")
    file_store = LocalProtectedFileStore(tmp_path / "changed-image-order-files")
    with session_factory.begin() as session:
        manager = create_user(session, "changed-image-manager", "synthetic password", Role.MANAGER)
        manager_id = manager.id

    order_text_by_hash: dict[str, str] = {}

    def fake_image_ocr(source: bytes, _page_number: int) -> tuple[str, Decimal]:
        return order_text_by_hash[hashlib.sha256(source).hexdigest()], Decimal("0.96")

    processor = PersistedUploadProcessor(
        session_factory,
        file_store,
        LocalReceiptOCREngine(fake_image_ocr),
    )
    prior_receipt_pks: dict[str, str] = {}
    prior_line_ids: dict[str, int] = {}
    processed_uploads: list[tuple[str, str]] = []
    approved_identity: tuple[int, int] | None = None
    try:
        for order_count in (5, 10, 15):
            source = _multi_order_image(order_count)
            source_sha256 = hashlib.sha256(source).hexdigest()
            file_key = file_store.save(source_sha256, source, "image/png")
            order_text_by_hash[source_sha256] = _multi_order_text(order_count)
            with session_factory.begin() as session:
                upload = ReceiptUpload(
                    source_sha256=source_sha256,
                    file_key=file_key,
                    media_type="image/png",
                    size_bytes=len(source),
                    uploaded_by=manager_id,
                    processing_status="QUEUED",
                    scan_status="NOT_SCANNED",
                )
                session.add(upload)
                session.flush()
                upload_pk = upload.upload_pk

            result = processor.process(upload_pk)
            assert result == ("SUCCEEDED" if order_count == 5 else "REVIEW")
            with session_factory.begin() as session:
                receipts = session.scalars(
                    select(Receipt).where(Receipt.transaction_number.like("SYN-ORDER-%"))
                ).all()
                actual_by_transaction = {
                    receipt.transaction_number: receipt.receipt_pk for receipt in receipts
                }
                assert len(actual_by_transaction) == order_count
                expected_transactions = {
                    f"SYN-ORDER-{number:03d}" for number in range(1, order_count + 1)
                }
                assert set(actual_by_transaction) == expected_transactions
                for transaction_number, receipt_pk in prior_receipt_pks.items():
                    assert actual_by_transaction[transaction_number] == receipt_pk
                    line_id = session.scalar(
                        select(ReceiptItem.id).where(ReceiptItem.receipt_pk == receipt_pk)
                    )
                    assert line_id == prior_line_ids[transaction_number]

                source_rows = session.scalars(
                    select(ReceiptSource).join(
                        Receipt, Receipt.receipt_pk == ReceiptSource.receipt_pk
                    ).where(Receipt.transaction_number.like("SYN-ORDER-%"))
                ).all()
                expected_sources = order_count + sum(range(5, order_count, 5))
                assert len(source_rows) == expected_sources
                expected_pending = sum(range(5, order_count, 5))
                assert sum(source.association_kind == "PENDING" for source in source_rows) == (
                    expected_pending
                )
                if order_count == 5:
                    first_line = session.scalar(
                        select(ReceiptItem).where(
                            ReceiptItem.receipt_pk == actual_by_transaction["SYN-ORDER-001"]
                        )
                    )
                    assert first_line is not None
                    assert first_line.store_item_id is not None and first_line.item_id is not None
                    confirm_store_item_mapping(
                        session,
                        first_line.store_item_id,
                        first_line.item_id,
                        manager_id,
                        effective_from=date(2026, 10, 3),
                    )
                    first_line.business_disposition = "ORDINARY_BUSINESS_PURCHASE"
                    first_line.disposition_subtype = "DIRECT_EXPENSE"
                    session.flush()
                    approval = approve_receipt_item(
                        session,
                        first_line.id,
                        manager_id,
                        BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
                        "synthetic-version-approval",
                        DispositionSubtype.DIRECT_EXPENSE,
                    ).approval
                    route_id = session.scalar(
                        select(ReceiptRoutingRecord.id).where(
                            ReceiptRoutingRecord.receipt_item_id == first_line.id
                        )
                    )
                    assert route_id is not None
                    approved_identity = approval.id, route_id
                assert session.scalar(select(func.count(ReceiptLineApproval.id))) == 1
                assert session.scalar(select(func.count(ReceiptRoutingRecord.id))) == 1
                assert approved_identity == (
                    session.scalar(select(ReceiptLineApproval.id)),
                    session.scalar(select(ReceiptRoutingRecord.id)),
                )
                current_transactions = [
                    f"SYN-ORDER-{number:03d}"
                    for number in range(1, order_count + 1)
                    if number > order_count - 5
                ]
                for transaction_number in current_transactions:
                    receipt_pk = actual_by_transaction[transaction_number]
                    prior_receipt_pks[transaction_number] = receipt_pk
                    persisted_line_id = session.scalar(
                        select(ReceiptItem.id).where(ReceiptItem.receipt_pk == receipt_pk)
                    )
                    assert persisted_line_id is not None
                    prior_line_ids[transaction_number] = persisted_line_id

            assert processor.process(upload_pk) == result
            processed_uploads.append((upload_pk, result))
            for prior_upload_pk, prior_result in processed_uploads:
                assert processor.process(prior_upload_pk) == prior_result
            with session_factory() as session:
                assert session.scalar(
                    select(func.count(Receipt.receipt_pk)).where(
                        Receipt.transaction_number.like("SYN-ORDER-%")
                    )
                ) == order_count
                assert session.scalar(
                    select(func.count(ReceiptSource.id)).join(
                        Receipt, Receipt.receipt_pk == ReceiptSource.receipt_pk
                    ).where(Receipt.transaction_number.like("SYN-ORDER-%"))
                ) == (order_count + sum(range(5, order_count, 5)))
    finally:
        engine.dispose()


def test_batch_endpoint_processes_changed_multi_order_image_versions_idempotently(
    tmp_path: Path, monkeypatch: Any
) -> None:
    engine, session_factory = _database(tmp_path / "batch-changed-image-versions.db")
    storage_path = tmp_path / "batch-changed-image-files"
    monkeypatch.setenv("RECEIPT_STORAGE_PATH", str(storage_path))
    with session_factory.begin() as session:
        manager = create_user(session, "batch-version-manager", "synthetic password", Role.MANAGER)
        manager_id = manager.id
        manager_token, manager_csrf = create_session(session, manager)

    order_text_by_hash: dict[str, str] = {}
    ocr_calls: list[str] = []

    def fake_image_ocr(source: bytes, _page_number: int) -> tuple[str, Decimal]:
        source_hash = hashlib.sha256(source).hexdigest()
        ocr_calls.append(source_hash)
        return order_text_by_hash[source_hash], Decimal("0.96")

    processor = PersistedUploadProcessor(
        session_factory,
        LocalProtectedFileStore(storage_path),
        LocalReceiptOCREngine(fake_image_ocr),
    )
    queued_uploads: list[str] = []

    def override_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    def dispatch_after_commit() -> None:
        assert dispatch_pending_receipt_uploads.run() == 1
        while queued_uploads:
            processor.process(queued_uploads.pop(0))

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    monkeypatch.setattr("mbs.receipts.tasks.SessionLocal", session_factory)
    monkeypatch.setattr(
        "mbs.receipts.tasks.process_receipt_upload.delay",
        queued_uploads.append,
    )
    monkeypatch.setattr(receipt_routes, "_request_outbox_dispatch", dispatch_after_commit)

    upload_ids: dict[int, str] = {}
    receipt_ids: dict[str, str] = {}
    line_ids: dict[str, int] = {}
    approved_identity: tuple[int, int] | None = None
    try:
        with TestClient(app) as client:
            for order_count in (5, 10, 15):
                source = _multi_order_image(order_count)
                source_hash = hashlib.sha256(source).hexdigest()
                order_text_by_hash[source_hash] = _multi_order_text(order_count)
                response = client.post(
                    "/api/v1/receipts/upload-batch",
                    files=[("files", ("orders.png", source, "image/png"))],
                    headers={
                        "Cookie": f"mbs_session={manager_token}",
                        "X-CSRF-Token": manager_csrf,
                    },
                )
                assert response.status_code == 200
                uploaded = response.json()["files"][0]
                assert uploaded["status"] == (
                    "QUEUED" if order_count == 5 else "POSSIBLE_DUPLICATE"
                )
                upload_ids[order_count] = uploaded["upload_pk"]
                if order_count > 5:
                    unresolved = client.post(
                        f"/api/v1/receipt-uploads/{uploaded['upload_pk']}/resolve-near-match",
                        json={"process_as_new": True},
                        headers={"Cookie": f"mbs_session={manager_token}"},
                    )
                    assert unresolved.status_code == 403
                    resolved = client.post(
                        f"/api/v1/receipt-uploads/{uploaded['upload_pk']}/resolve-near-match",
                        json={"process_as_new": True},
                        headers={
                            "Cookie": f"mbs_session={manager_token}",
                            "X-CSRF-Token": manager_csrf,
                        },
                    )
                    assert resolved.status_code == 200
                    assert resolved.json()["status"] == "QUEUED"

                with session_factory.begin() as session:
                    upload = session.get(ReceiptUpload, uploaded["upload_pk"])
                    expected_status = "SUCCEEDED" if order_count == 5 else "REVIEW"
                    assert upload is not None and upload.processing_status == expected_status

                    receipts = session.scalars(
                        select(Receipt).where(
                            Receipt.transaction_number.like("SYN-ORDER-%")
                        )
                    ).all()
                    actual_receipt_ids = {
                        receipt.transaction_number: receipt.receipt_pk for receipt in receipts
                    }
                    assert len(actual_receipt_ids) == order_count
                    assert set(actual_receipt_ids) == {
                        f"SYN-ORDER-{number:03d}" for number in range(1, order_count + 1)
                    }
                    for transaction_number, receipt_pk in receipt_ids.items():
                        assert actual_receipt_ids[transaction_number] == receipt_pk
                        assert session.scalar(
                            select(ReceiptItem.id).where(ReceiptItem.receipt_pk == receipt_pk)
                        ) == line_ids[transaction_number]

                    if order_count == 5:
                        first_line = session.scalar(
                            select(ReceiptItem).where(
                                ReceiptItem.receipt_pk
                                == actual_receipt_ids["SYN-ORDER-001"]
                            )
                        )
                        assert first_line is not None
                        assert first_line.store_item_id is not None
                        assert first_line.item_id is not None
                        confirm_store_item_mapping(
                            session,
                            first_line.store_item_id,
                            first_line.item_id,
                            manager_id,
                            effective_from=date(2026, 10, 3),
                        )
                        first_line.business_disposition = "ORDINARY_BUSINESS_PURCHASE"
                        first_line.disposition_subtype = "DIRECT_EXPENSE"
                        session.flush()
                        approval = approve_receipt_item(
                            session,
                            first_line.id,
                            manager_id,
                            BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
                            "batch-version-approval",
                            DispositionSubtype.DIRECT_EXPENSE,
                        ).approval
                        route_id = session.scalar(
                            select(ReceiptRoutingRecord.id).where(
                                ReceiptRoutingRecord.receipt_item_id == first_line.id
                            )
                        )
                        assert route_id is not None
                        approved_identity = approval.id, route_id

                    for transaction_number, receipt_pk in actual_receipt_ids.items():
                        receipt_ids[transaction_number] = receipt_pk
                        line_id = session.scalar(
                            select(ReceiptItem.id).where(ReceiptItem.receipt_pk == receipt_pk)
                        )
                        assert line_id is not None
                        line_ids[transaction_number] = line_id

                    assert session.scalar(select(func.count(ReceiptLineApproval.id))) == (
                        1 if approved_identity is not None else 0
                    )
                    assert session.scalar(select(func.count(ReceiptRoutingRecord.id))) == (
                        1 if approved_identity is not None else 0
                    )
                    if approved_identity is not None:
                        assert approved_identity == (
                            session.scalar(select(ReceiptLineApproval.id)),
                            session.scalar(select(ReceiptRoutingRecord.id)),
                        )

            assert len(ocr_calls) == 3
            replay_names = {
                15: "reselected/final-orders.png",
                5: "archive/original-orders.png",
                10: "another-folder/middle-orders.png",
            }
            for order_count in (15, 5, 10):
                source = _multi_order_image(order_count)
                replay = client.post(
                    "/api/v1/receipts/upload-batch",
                    files=[("files", (replay_names[order_count], source, "image/png"))],
                    headers={
                        "Cookie": f"mbs_session={manager_token}",
                        "X-CSRF-Token": manager_csrf,
                    },
                )
                assert replay.status_code == 200
                result = replay.json()["files"][0]
                assert result["status"] == "EXACT_DUPLICATE"
                assert result["idempotent"] is True
                assert result["upload_pk"] == upload_ids[order_count]
            assert len(ocr_calls) == 3

        with session_factory() as session:
            assert session.scalar(
                select(func.count(Receipt.receipt_pk)).where(
                    Receipt.transaction_number.like("SYN-ORDER-%")
                )
            ) == 15
            assert session.scalar(
                select(func.count(ReceiptSource.id)).join(
                    Receipt, Receipt.receipt_pk == ReceiptSource.receipt_pk
                ).where(Receipt.transaction_number.like("SYN-ORDER-%"))
            ) == 30
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_batch_status_reports_partial_order_holds_without_losing_valid_orders(
    tmp_path: Path, monkeypatch: Any
) -> None:
    engine, session_factory = _database(tmp_path / "batch-partial-order-status.db")
    storage_path = tmp_path / "batch-partial-order-files"
    monkeypatch.setenv("RECEIPT_STORAGE_PATH", str(storage_path))
    with session_factory.begin() as session:
        manager = create_user(session, "partial-order-manager", "synthetic password", Role.MANAGER)
        manager_token, manager_csrf = create_session(session, manager)
        viewer = create_user(session, "partial-order-viewer", "synthetic password", Role.VIEWER)
        viewer_token, _ = create_session(session, viewer)

    source = _multi_order_image(3)
    source_hash = hashlib.sha256(source).hexdigest()
    order_text = _multi_order_text(3).replace("Order # SYN-ORDER-002\n", "")

    def fake_image_ocr(_source: bytes, _page_number: int) -> tuple[str, Decimal]:
        return order_text, Decimal("0.96")

    processor = PersistedUploadProcessor(
        session_factory,
        LocalProtectedFileStore(storage_path),
        LocalReceiptOCREngine(fake_image_ocr),
    )
    queued_uploads: list[str] = []

    def override_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    def dispatch_after_commit() -> None:
        assert dispatch_pending_receipt_uploads.run() == 1
        while queued_uploads:
            processor.process(queued_uploads.pop(0))

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    monkeypatch.setattr("mbs.receipts.tasks.SessionLocal", session_factory)
    monkeypatch.setattr("mbs.receipts.tasks.process_receipt_upload.delay", queued_uploads.append)
    monkeypatch.setattr(receipt_routes, "_request_outbox_dispatch", dispatch_after_commit)
    try:
        with TestClient(app) as client:
            headers = {
                "Cookie": f"mbs_session={manager_token}",
                "X-CSRF-Token": manager_csrf,
            }
            uploaded = client.post(
                "/api/v1/receipts/upload-batch",
                files=[("files", ("orders.png", source, "image/png"))],
                headers=headers,
            )
            assert uploaded.status_code == 200
            assert uploaded.json()["files"][0]["source_sha256"] == source_hash
            upload_pk = uploaded.json()["files"][0]["upload_pk"]

            status_response = client.get(
                f"/api/v1/receipt-uploads/{upload_pk}/status",
                headers={"Cookie": f"mbs_session={manager_token}"},
            )
            viewer_response = client.get(
                f"/api/v1/receipt-uploads/{upload_pk}/status",
                headers={"Cookie": f"mbs_session={viewer_token}"},
            )
            missing_response = client.get(
                f"/api/v1/receipt-uploads/{uuid4()}/status",
                headers={"Cookie": f"mbs_session={manager_token}"},
            )

        assert status_response.status_code == 200
        assert viewer_response.status_code == 403
        assert missing_response.status_code == 404
        status_payload = status_response.json()
        assert status_payload["status"] == "REVIEW"
        assert status_payload["order_summary"] == {
            "added": 2,
            "source_review": 0,
            "held": 1,
            "already_associated": 0,
        }
        assert [order["status"] for order in status_payload["orders"]] == [
            "ADDED",
            "HELD",
            "ADDED",
        ]
        assert status_payload["orders"][1]["issue_codes"]

        with session_factory() as session:
            receipts = session.scalars(
                select(Receipt).where(Receipt.transaction_number.like("SYN-ORDER-%"))
            ).all()
            assert {receipt.transaction_number for receipt in receipts} == {
                "SYN-ORDER-001",
                "SYN-ORDER-003",
            }
            assert session.scalar(
                select(func.count(ReceiptSource.id)).where(ReceiptSource.upload_pk == upload_pk)
            ) == 2
            assert session.scalar(select(func.count(ReceiptLineApproval.id))) == 0
            assert session.scalar(select(func.count(ReceiptRoutingRecord.id))) == 0
            outcomes = session.scalars(
                select(AuditLog).where(
                    AuditLog.event_type == "RECEIPT_ORDER_IMPORT_OUTCOME",
                    AuditLog.entity_id == upload_pk,
                )
            ).all()
            assert len(outcomes) == 3
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


@pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="Local Tesseract executable is unavailable",
)
def test_rm_025_real_tesseract_segments_generated_five_order_image() -> None:
    document = LocalReceiptOCREngine().extract(_multi_order_image(5), "image/png")

    assert document["extraction"]["content_kind"] == "IMAGE_ONLY"
    assert len(document["orders"]) == 5
    transaction_numbers = [
        order["receipt"]["transaction_number"] for order in document["orders"]
    ]
    assert transaction_numbers == [f"SYN-ORDER-{number:03d}" for number in range(1, 6)]
    assert all(order["review_required"] is True or order["items"] for order in document["orders"])


def test_worker_persists_incomplete_image_pdf_extraction_for_review(tmp_path: Path) -> None:
    engine, session_factory = _database(tmp_path / "receipt-worker-image-review.db")
    storage = LocalProtectedFileStore(tmp_path / "worker-image-review-files")
    image = Image.new("RGB", (800, 1000), "white")
    image_buffer = BytesIO()
    image.save(image_buffer, format="PNG")
    pdf = pymupdf.open()
    page = pdf.new_page(width=612, height=792)
    page.insert_image(page.rect, stream=image_buffer.getvalue())
    source = pdf.tobytes()
    pdf.close()
    source_hash = hashlib.sha256(source).hexdigest()
    file_key = storage.save(source_hash, source, "application/pdf")

    with session_factory.begin() as session:
        manager = create_user(session, "image-review-manager", "synthetic password", Role.MANAGER)
        upload = ReceiptUpload(
            source_sha256=source_hash,
            file_key=file_key,
            media_type="application/pdf",
            size_bytes=len(source),
            uploaded_by=manager.id,
            processing_status="QUEUED",
        )
        session.add(upload)
        session.flush()
        upload_pk = upload.upload_pk

    class SyntheticOCR:
        def __call__(self, _page: bytes, _page_number: int) -> tuple[str, Decimal]:
            return "SYNTHETIC MARKET\nPARTIAL OCR TEXT", Decimal("0.91")

    processor = PersistedUploadProcessor(
        session_factory,
        storage,
        LocalReceiptOCREngine(SyntheticOCR()),
    )
    assert processor.process(upload_pk) == "REVIEW"

    with session_factory() as session:
        persisted_upload = session.get(ReceiptUpload, upload_pk)
        review_event = session.scalar(
            select(AuditLog).where(
                AuditLog.event_type == "RECEIPT_OCR_EXTRACTION_REVIEW_REQUIRED",
                AuditLog.entity_id == upload_pk,
            )
        )
        receipt_count = session.scalar(select(func.count(Receipt.receipt_pk)))

    assert persisted_upload is not None
    assert persisted_upload.processing_status == "REVIEW"
    extraction_result = persisted_upload.ocr_extraction_result
    assert isinstance(extraction_result, dict)
    extraction = extraction_result.get("extraction")
    assert isinstance(extraction, dict)
    assert extraction.get("method") == "OCR_FALLBACK"
    missing_fields = extraction.get("missing_fields")
    assert isinstance(missing_fields, list) and "items" in missing_fields
    assert review_event is not None
    assert receipt_count == 0
    engine.dispose()


def test_worker_persists_pdf_image_candidate_and_keeps_rejection_on_retry(
    tmp_path: Path,
) -> None:
    engine, session_factory = _database(tmp_path / "receipt-image-candidate.db")
    storage = LocalProtectedFileStore(tmp_path / "receipt-image-candidate-files")
    product_image = Image.new("RGB", (160, 120), (35, 110, 70))
    product_buffer = BytesIO()
    product_image.save(product_buffer, format="PNG")
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((40, 200), "Milk")
    page.insert_image(pymupdf.Rect(300, 170, 460, 290), stream=product_buffer.getvalue())
    source = cast(bytes, pdf.tobytes())
    pdf.close()
    source_hash = hashlib.sha256(source).hexdigest()
    file_key = storage.save(source_hash, source, "application/pdf")

    with session_factory.begin() as session:
        manager = create_user(session, "candidate-manager", "synthetic password", Role.MANAGER)
        image_setting = session.get(Setting, "receipt_image_extraction_enabled")
        assert image_setting is not None
        image_setting.value = "Yes"
        upload = ReceiptUpload(
            source_sha256=source_hash,
            file_key=file_key,
            media_type="application/pdf",
            size_bytes=len(source),
            uploaded_by=manager.id,
            processing_status="QUEUED",
        )
        session.add(upload)
        session.flush()
        upload_pk = upload.upload_pk

    class SyntheticImageEngine:
        def __init__(self, store: str, transaction_number: str) -> None:
            self.store = store
            self.transaction_number = transaction_number

        def extract(self, _source: bytes, _media_type: str) -> dict[str, Any]:
            document = _document(self.transaction_number)
            document["receipt"]["store"] = self.store
            document["items"] = [{"description": "Milk", "line_total": "1.00"}]
            return document

        def extract_image_candidates(
            self,
            source_bytes: bytes,
            receipt_document: dict[str, Any],
            minimum_dimension_px: int,
            max_image_bytes: int,
            max_dimension_px: int,
        ) -> tuple[Any, ...]:
            from mbs.receipts.pdf_extraction import extract_embedded_pdf_images

            return extract_embedded_pdf_images(
                source_bytes,
                receipt_document,
                minimum_dimension_px,
                max_image_bytes,
                max_dimension_px,
            )

    processor = PersistedUploadProcessor(
        session_factory,
        storage,
        SyntheticImageEngine("Synthetic Store One", "SYN-IMAGE-001"),
    )
    assert processor.process(upload_pk) == "SUCCEEDED"

    second_pdf = pymupdf.open()
    second_page = second_pdf.new_page(width=600, height=800)
    second_page.insert_text((40, 80), "Synthetic Store Two source")
    second_page.insert_text((40, 200), "Milk")
    second_page.insert_image(pymupdf.Rect(300, 170, 460, 290), stream=product_buffer.getvalue())
    second_source = cast(bytes, second_pdf.tobytes())
    second_pdf.close()
    second_source_hash = hashlib.sha256(second_source).hexdigest()
    second_file_key = storage.save(second_source_hash, second_source, "application/pdf")
    with session_factory.begin() as session:
        second_upload = ReceiptUpload(
            source_sha256=second_source_hash,
            file_key=second_file_key,
            media_type="application/pdf",
            size_bytes=len(second_source),
            processing_status="QUEUED",
        )
        session.add(second_upload)
        session.flush()
        second_upload_pk = second_upload.upload_pk
    second_processor = PersistedUploadProcessor(
        session_factory,
        storage,
        SyntheticImageEngine("Synthetic Store Two", "SYN-IMAGE-002"),
    )
    assert second_processor.process(second_upload_pk) == "SUCCEEDED"

    with session_factory.begin() as session:
        links = list(
            session.scalars(
                select(MediaAssetLink)
                .where(MediaAssetLink.owner_kind == "RECEIPT_LINE_CANDIDATE")
                .order_by(MediaAssetLink.id)
            )
        )
        assert len(links) == 2
        assert session.scalar(select(func.count(MediaAsset.asset_sha256))) == 1
        link = links[0]
        assert link is not None
        link.status = "REJECTED"
        link.rejection_reason = "Synthetic reviewer rejection"
        rejected_id = link.id

    with session_factory.begin() as session:
        source_row = session.scalar(
            select(ReceiptSource).where(ReceiptSource.upload_pk == upload_pk)
        )
        assert source_row is not None
        receipt_items = list(
            session.scalars(
                select(ReceiptItem).where(ReceiptItem.receipt_pk == source_row.receipt_pk)
            )
        )
        candidates = SyntheticImageEngine(
            "Synthetic Store One", "SYN-IMAGE-001"
        ).extract_image_candidates(
            source,
            _document("SYN-IMAGE-001"),
            100,
            10_000_000,
            10_000,
        )
        created = MediaAssetService.persist_pdf_image_candidates(
            session,
            source_row,
            candidates,
            receipt_items,
            storage,
            None,
        )
        assert created == []
        persisted = session.get(MediaAssetLink, rejected_id)
        assert persisted is not None
        assert persisted.status == "REJECTED"
        assert persisted.rejection_reason == "Synthetic reviewer rejection"
        assert session.scalar(select(func.count(MediaAsset.asset_sha256))) == 1
        assert (
            session.scalar(
                select(func.count(MediaAssetLink.id)).where(
                    MediaAssetLink.owner_kind == "RECEIPT_LINE_CANDIDATE"
                )
            )
            == 2
        )
    engine.dispose()


def test_worker_skips_invalid_image_candidate_without_blocking_receipt(
    tmp_path: Path,
) -> None:
    engine, session_factory = _database(tmp_path / "receipt-invalid-image-candidate.db")
    storage = LocalProtectedFileStore(tmp_path / "receipt-invalid-image-candidate-files")
    source = _pdf_with_label("Synthetic invalid image candidate")
    source_hash = hashlib.sha256(source).hexdigest()
    file_key = storage.save(source_hash, source, "application/pdf")
    with session_factory.begin() as session:
        manager = create_user(session, "invalid-image-manager", "synthetic password", Role.MANAGER)
        setting = session.get(Setting, "receipt_image_extraction_enabled")
        assert setting is not None
        setting.value = "Yes"
        upload = ReceiptUpload(
            source_sha256=source_hash,
            file_key=file_key,
            media_type="application/pdf",
            size_bytes=len(source),
            uploaded_by=manager.id,
            processing_status="QUEUED",
        )
        session.add(upload)
        session.flush()
        upload_pk = upload.upload_pk

    class InvalidImageEngine:
        def extract(self, _source: bytes, _media_type: str) -> dict[str, Any]:
            return _document("SYN-IMAGE-INVALID")

        def extract_image_candidates(
            self,
            _source: bytes,
            _receipt_document: dict[str, Any],
            _minimum_dimension_px: int,
            _max_image_bytes: int,
            _max_dimension_px: int,
        ) -> tuple[EmbeddedPDFImage, ...]:
            return (
                EmbeddedPDFImage(
                    image_bytes=bytes.fromhex("89504e470d0a1a0a") + b"invalid raster",
                    media_type="image/png",
                    page_number=1,
                    region=(10.0, 20.0, 170.0, 140.0),
                    page_width=600.0,
                    page_height=800.0,
                    pixel_width=160,
                    pixel_height=120,
                    item_index=0,
                ),
            )

    processor = PersistedUploadProcessor(session_factory, storage, InvalidImageEngine())
    assert processor.process(upload_pk) == "SUCCEEDED"
    with session_factory() as session:
        invalid_receipt = session.scalar(
            select(Receipt).where(Receipt.receipt_id.like("%SYN-IMAGE-INVALID"))
        )
        assert invalid_receipt is not None
        rejected = session.scalar(
            select(AuditLog).where(AuditLog.event_type == "RECEIPT_IMAGE_CANDIDATE_INGEST_REJECTED")
        )
        assert rejected is not None
        assert rejected.details is not None and "INVALID_IMAGE_CONTENT" in rejected.details
        assert session.scalar(select(func.count(MediaAsset.asset_sha256))) == 0
        assert (
            session.scalar(
                select(func.count(MediaAssetLink.id)).where(
                    MediaAssetLink.owner_kind == "RECEIPT_LINE_CANDIDATE"
                )
            )
            == 0
        )
    engine.dispose()


def test_worker_skips_embedded_image_extraction_when_setting_is_disabled(
    tmp_path: Path,
) -> None:
    engine, session_factory = _database(tmp_path / "receipt-image-extraction-disabled.db")
    storage = LocalProtectedFileStore(tmp_path / "receipt-image-extraction-disabled-files")
    source = _pdf_with_label("Synthetic disabled image extraction")
    source_hash = hashlib.sha256(source).hexdigest()
    file_key = storage.save(source_hash, source, "application/pdf")
    with session_factory.begin() as session:
        upload = ReceiptUpload(
            source_sha256=source_hash,
            file_key=file_key,
            media_type="application/pdf",
            size_bytes=len(source),
            processing_status="QUEUED",
        )
        session.add(upload)
        session.flush()
        upload_pk = upload.upload_pk

    class DisabledImageEngine:
        def extract(self, _source: bytes, _media_type: str) -> dict[str, Any]:
            return _document("SYN-IMAGE-DISABLED")

        def extract_image_candidates(
            self,
            _source: bytes,
            _document: dict[str, Any],
            _minimum_dimension_px: int,
            _max_image_bytes: int,
            _max_dimension_px: int,
        ) -> tuple[Any, ...]:
            raise AssertionError("Disabled image extraction must not call the extractor")

    processor = PersistedUploadProcessor(session_factory, storage, DisabledImageEngine())
    assert processor.process(upload_pk) == "SUCCEEDED"
    with session_factory() as session:
        assert session.scalar(select(func.count(MediaAsset.asset_sha256))) == 0
        assert (
            session.scalar(
                select(func.count(MediaAssetLink.id)).where(
                    MediaAssetLink.owner_kind == "RECEIPT_LINE_CANDIDATE"
                )
            )
            == 0
        )
    engine.dispose()


def test_celery_entry_point_persists_using_database_rules_and_canonical_writer(
    tmp_path: Path,
) -> None:
    engine, session_factory = _database(tmp_path / "receipt-worker.db")
    storage = LocalProtectedFileStore(tmp_path / "worker-files")
    source = _png()
    source_hash = __import__("hashlib").sha256(source).hexdigest()
    file_key = storage.save(source_hash, source, "image/png")

    with session_factory.begin() as session:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        milk_rule = session.scalar(select(CategoryRule).where(CategoryRule.keyword == "milk"))
        assert milk_rule is not None
        milk_rule.keyword = "milk-only-after-review"
        upload = ReceiptUpload(
            source_sha256=source_hash,
            file_key=file_key,
            media_type="image/png",
            size_bytes=len(source),
            uploaded_by=manager.id,
            processing_status="QUEUED",
        )
        session.add(upload)
        session.flush()
        upload_pk = upload.upload_pk

    class MockEngine:
        calls = 0

        def extract(self, source: bytes, media_type: str) -> dict[str, Any]:
            self.calls += 1
            document = _document()
            document["metadata"] = {
                "provider": "synthetic-mock",
                "schema_version": "fixture-v2",
                "page_count": 1,
            }
            return document

    mock_engine = MockEngine()
    configure_persisted_processor(PersistedUploadProcessor(session_factory, storage, mock_engine))
    try:
        result = process_receipt_upload.run(upload_pk)
        duplicate_delivery = process_receipt_upload.run(upload_pk)
    finally:
        configure_persisted_processor(
            PersistedUploadProcessor(
                session_factory,
                storage,
                MockEngine(),
            )
        )

    assert result == "SUCCEEDED"
    assert duplicate_delivery == "SUCCEEDED"
    assert mock_engine.calls == 1
    with session_factory() as session:
        receipt = session.scalar(select(Receipt))
        persisted_upload = session.get(ReceiptUpload, upload_pk)
        assert receipt is not None
        assert receipt.store == "Synthetic Market"
        line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
        )
        assert line is not None and line.category == "Other"
        assert receipt.ocr_provider == "synthetic-mock"
        assert receipt.ocr_schema_version == "fixture-v2"
        assert persisted_upload is not None and persisted_upload.processing_status == "SUCCEEDED"
        assert persisted_upload.ocr_provider == "synthetic-mock"
        assert persisted_upload.ocr_schema_version == "fixture-v2"
        assert persisted_upload.page_count == 1
        assert session.scalar(select(func.count(ReceiptOutboxEvent.id))) == 0
    engine.dispose()


def test_persisted_worker_retries_ocr_failure_without_losing_upload(
    tmp_path: Path,
) -> None:
    engine, session_factory = _database(tmp_path / "receipt-worker-retry.db")
    storage = LocalProtectedFileStore(tmp_path / "worker-retry-files")
    source = _png()
    source_hash = hashlib.sha256(source).hexdigest()
    file_key = storage.save(source_hash, source, "image/png")

    with session_factory.begin() as session:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        upload = ReceiptUpload(
            source_sha256=source_hash,
            file_key=file_key,
            media_type="image/png",
            size_bytes=len(source),
            uploaded_by=manager.id,
            processing_status="QUEUED",
        )
        session.add(upload)
        session.flush()
        upload_pk = upload.upload_pk

    class RetryEngine:
        calls = 0

        def extract(self, source: bytes, media_type: str) -> dict[str, Any]:
            with session_factory() as session:
                claimed = session.get(ReceiptUpload, upload_pk)
                assert claimed is not None
                assert claimed.processing_status == "RUNNING"
                assert claimed.processing_lease_token is not None
                assert claimed.processing_lease_until is not None
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("synthetic transient OCR failure")
            return _document("SYN-802")

    ocr_engine = RetryEngine()
    processor = PersistedUploadProcessor(session_factory, storage, ocr_engine)
    try:
        try:
            processor.process(upload_pk)
        except RuntimeError as error:
            assert "synthetic transient OCR failure" in str(error)
        else:
            raise AssertionError("Expected the first OCR attempt to fail")

        with session_factory() as session:
            after_failure = session.get(ReceiptUpload, upload_pk)
            assert after_failure is not None
            assert after_failure.processing_status == "QUEUED"
            assert after_failure.ocr_attempts == 1

        assert processor.process(upload_pk) == "SUCCEEDED"
        with session_factory() as session:
            after_retry = session.get(ReceiptUpload, upload_pk)
            assert after_retry is not None
            assert after_retry.processing_status == "SUCCEEDED"
            assert after_retry.ocr_attempts == 2
            assert session.scalar(select(func.count(Receipt.receipt_pk))) == 1
    finally:
        engine.dispose()


def test_persisted_worker_moves_to_review_after_max_attempts(tmp_path: Path) -> None:
    engine, session_factory = _database(tmp_path / "receipt-worker-review.db")
    storage = LocalProtectedFileStore(tmp_path / "worker-review-files")
    source = _png()
    source_hash = hashlib.sha256(source).hexdigest()
    file_key = storage.save(source_hash, source, "image/png")

    with session_factory.begin() as session:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        upload = ReceiptUpload(
            source_sha256=source_hash,
            file_key=file_key,
            media_type="image/png",
            size_bytes=len(source),
            uploaded_by=manager.id,
            processing_status="QUEUED",
        )
        session.add(upload)
        session.flush()
        upload_pk = upload.upload_pk

    class FailingEngine:
        calls = 0

        def extract(self, source: bytes, media_type: str) -> dict[str, Any]:
            self.calls += 1
            raise RuntimeError("synthetic permanent OCR failure")

    ocr_engine = FailingEngine()
    processor = PersistedUploadProcessor(session_factory, storage, ocr_engine)
    for attempt in range(MAX_ATTEMPTS):
        try:
            processor.process(upload_pk)
        except RuntimeError as error:
            assert "synthetic permanent OCR failure" in str(error)
        else:
            raise AssertionError("Expected OCR processing to fail")
        with session_factory() as session:
            failed_upload = session.get(ReceiptUpload, upload_pk)
            assert failed_upload is not None
            expected_status = "REVIEW" if attempt == MAX_ATTEMPTS - 1 else "QUEUED"
            assert failed_upload.processing_status == expected_status
            assert failed_upload.ocr_attempts == attempt + 1
            assert failed_upload.processing_lease_token is None

    assert processor.process(upload_pk) == "REVIEW"
    assert ocr_engine.calls == MAX_ATTEMPTS
    with session_factory() as session:
        failures = session.scalars(
            select(AuditLog).where(
                AuditLog.event_type == "RECEIPT_OCR_FAILED",
                AuditLog.entity_id == upload_pk,
            )
        ).all()
        assert len(failures) == MAX_ATTEMPTS
    engine.dispose()


def test_worker_holds_matching_receipt_id_for_source_review(tmp_path: Path) -> None:
    engine, session_factory = _database(tmp_path / "receipt-worker-duplicate.db")
    storage = LocalProtectedFileStore(tmp_path / "worker-duplicate-files")
    first_source = _png()
    second_source = _png((31, 101, 171))
    first_hash = hashlib.sha256(first_source).hexdigest()
    second_hash = hashlib.sha256(second_source).hexdigest()
    first_key = storage.save(first_hash, first_source, "image/png")
    second_key = storage.save(second_hash, second_source, "image/png")

    with session_factory.begin() as session:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        first_upload = ReceiptUpload(
            source_sha256=first_hash,
            file_key=first_key,
            media_type="image/png",
            size_bytes=len(first_source),
            uploaded_by=manager.id,
            processing_status="QUEUED",
        )
        second_upload = ReceiptUpload(
            source_sha256=second_hash,
            file_key=second_key,
            media_type="image/png",
            size_bytes=len(second_source),
            uploaded_by=manager.id,
            processing_status="QUEUED",
        )
        session.add_all([first_upload, second_upload])
        session.flush()
        first_upload_pk = first_upload.upload_pk
        second_upload_pk = second_upload.upload_pk

    class SameReceiptEngine:
        calls = 0

        def extract(self, source: bytes, media_type: str) -> dict[str, Any]:
            self.calls += 1
            return _document("SYN-DUPLICATE")

    ocr_engine = SameReceiptEngine()
    processor = PersistedUploadProcessor(session_factory, storage, ocr_engine)

    assert processor.process(first_upload_pk) == "SUCCEEDED"
    assert processor.process(second_upload_pk) == "REVIEW"
    assert processor.process(second_upload_pk) == "REVIEW"
    assert ocr_engine.calls == 2

    with session_factory() as session:
        candidate_upload = session.get(ReceiptUpload, second_upload_pk)
        assert candidate_upload is not None
        assert candidate_upload.processing_status == "REVIEW"
        assert candidate_upload.duplicate_status == "SOURCE_ASSOCIATION_REVIEW"
        assert session.scalar(select(func.count(Receipt.receipt_pk))) == 1
        sources = session.scalars(select(ReceiptSource).order_by(ReceiptSource.id)).all()
        assert [source.association_kind for source in sources] == ["PRIMARY", "PENDING"]
        raw_header = sources[1].raw_ocr_document.get("receipt")
        assert isinstance(raw_header, dict)
        assert raw_header.get("transaction_number") == "SYN-DUPLICATE"
        line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == sources[0].receipt_pk)
        )
        assert line is not None
        assert line.source_id == sources[0].id
        assert line.source_page == 1 and line.source_line_number == 1
    engine.dispose()


def test_rm_022_worker_correlates_three_synthetic_pdfs_and_supplements_once(
    tmp_path: Path,
) -> None:
    engine, session_factory = _database(tmp_path / "rm-022-worker-profile.db")
    file_store = LocalProtectedFileStore(tmp_path / "rm-022-source-files")
    primary_pdf = _pdf_with_label("SYN-17 full scan page one")
    copy_pdf = _pdf_with_label("SYN-17 overlapping full scan")
    partial_pdf = _pdf_with_label("SYN-17 partial scan page two")

    primary_lines = [
        {
            "description": "Milk",
            "store_product_id": "MILK-SOURCE-17",
            "line_total": "10.00",
            "source_page": 1,
            "source_line_number": 1,
        },
        {
            "description": "Bread",
            "store_product_id": "BREAD-SOURCE-17",
            "line_total": "10.00",
            "source_page": 1,
            "source_line_number": 2,
        },
    ]
    documents = {
        primary_pdf: {
            "receipt": {
                "store": "Synthetic Multi Source Market",
                "date": "2026-10-01",
                "time": "11:20:00",
                "transaction_number": "SYN-17",
                "subtotal": "32.50",
                "tax": "0.00",
                "total": "32.50",
            },
            "items": primary_lines,
        },
        copy_pdf: {
            "receipt": {
                "store": "Synthetic Multi Source Market",
                "date": "2026-10-01",
                "time": "11:20:00",
                "transaction_number": "SYN-17",
                "subtotal": "32.50",
                "tax": "0.00",
                "total": "32.50",
            },
            "items": primary_lines,
        },
        partial_pdf: {
            "receipt": {
                "store": "Synthetic Multi Source Market",
                "date": "2026-10-01",
                "time": "11:20:00",
                "transaction_number": "SYN-17",
                "subtotal": "32.50",
                "tax": "0.00",
                "total": "32.50",
            },
            "items": [
                {
                    "description": "Milk",
                    "store_product_id": "MILK-SOURCE-17",
                    "line_total": "12.50",
                    "source_page": 2,
                    "source_line_number": 4,
                }
            ],
        },
    }
    upload_pks: list[str] = []
    with session_factory.begin() as session:
        manager = create_user(session, "rm-022-worker-manager", "synthetic password", Role.MANAGER)
        for source in (primary_pdf, copy_pdf, partial_pdf):
            source_hash = hashlib.sha256(source).hexdigest()
            file_key = file_store.save(source_hash, source, "application/pdf")
            upload = ReceiptUpload(
                source_sha256=source_hash,
                file_key=file_key,
                media_type="application/pdf",
                size_bytes=len(source),
                uploaded_by=manager.id,
                processing_status="QUEUED",
            )
            session.add(upload)
            session.flush()
            upload_pks.append(upload.upload_pk)

    class SyntheticMultiPdfOCR:
        def extract(self, source: bytes, media_type: str) -> dict[str, Any]:
            assert media_type == "application/pdf"
            return documents[source]

    processor = PersistedUploadProcessor(
        session_factory,
        file_store,
        SyntheticMultiPdfOCR(),
    )
    assert processor.process(upload_pks[0]) == "SUCCEEDED"
    assert processor.process(upload_pks[1]) == "REVIEW"
    assert processor.process(upload_pks[2]) == "REVIEW"

    with session_factory.begin() as session:
        reviewer = session.scalar(
            select(ReceiptUpload).where(ReceiptUpload.upload_pk == upload_pks[0])
        )
        assert reviewer is not None and reviewer.uploaded_by is not None
        source_rows = session.scalars(
            select(ReceiptSource)
            .where(ReceiptSource.upload_pk.in_(upload_pks))
            .order_by(ReceiptSource.id)
        ).all()
        assert [source.association_kind for source in source_rows] == [
            "PRIMARY",
            "PENDING",
            "PENDING",
        ]
        receipt_pk = source_rows[0].receipt_pk
        copy = decide_receipt_source(
            session,
            receipt_pk,
            source_rows[1].id,
            reviewer.uploaded_by,
            SourceDecision.COPY,
            "Synthetic overlapping full scan",
            "rm-022-worker-copy-v1",
        )
        with pytest.raises(ValueError, match="explicitly confirm each repeated source line"):
            decide_receipt_source(
                session,
                receipt_pk,
                source_rows[2].id,
                reviewer.uploaded_by,
                SourceDecision.SUPPLEMENT,
                "Synthetic distinct purchase occurrence",
                "rm-022-worker-supplement-v1",
            )
        supplement = decide_receipt_source(
            session,
            receipt_pk,
            source_rows[2].id,
            reviewer.uploaded_by,
            SourceDecision.SUPPLEMENT,
            "Synthetic distinct purchase occurrence",
            "rm-022-worker-supplement-v1",
            confirmed_repeated_line_indexes=(0,),
        )
        retry = decide_receipt_source(
            session,
            receipt_pk,
            source_rows[2].id,
            reviewer.uploaded_by,
            SourceDecision.SUPPLEMENT,
            "Synthetic distinct purchase occurrence",
            "rm-022-worker-supplement-v1",
            confirmed_repeated_line_indexes=(0,),
        )
        assert copy.added_line_count == 0
        assert supplement.added_line_count == 1
        assert retry.idempotent is True

    with session_factory() as session:
        receipt_count = session.scalar(select(func.count(Receipt.receipt_pk)))
        receipt = session.scalar(select(Receipt))
        lines = session.scalars(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt_pk).order_by(ReceiptItem.id)
        ).all()
        approvals = session.scalar(select(func.count(ReceiptLineApproval.id)))
        routes = session.scalar(select(func.count(ReceiptRoutingRecord.id)))
        corrections = session.scalars(
            select(ReceiptCorrection).where(ReceiptCorrection.receipt_pk == receipt_pk)
        ).all()
        sources = session.scalars(
            select(ReceiptSource)
            .where(ReceiptSource.receipt_pk == receipt_pk)
            .order_by(ReceiptSource.id)
        ).all()
        uploads = session.scalars(
            select(ReceiptUpload).where(ReceiptUpload.upload_pk.in_(upload_pks))
        ).all()

    assert receipt_count == 1
    assert receipt is not None and receipt.subtotal == Decimal("32.50")
    assert receipt.receipt_document["total_mismatch"] is False
    assert [line.line_total for line in lines] == [
        Decimal("10.00"),
        Decimal("10.00"),
        Decimal("12.50"),
    ]
    assert (lines[2].source_id, lines[2].source_page, lines[2].source_line_number) == (
        sources[2].id,
        2,
        4,
    )
    assert [source.association_kind for source in sources] == ["PRIMARY", "COPY", "SUPPLEMENT"]
    assert sources[2].confirmed_repeated_line_indexes == [0]
    assert corrections and len(corrections) == 1
    assert approvals == routes == 0
    assert all(file_store.read(upload.file_key) for upload in uploads)
    engine.dispose()


def test_duplicate_delivery_respects_active_worker_lease(tmp_path: Path) -> None:
    engine, session_factory = _database(tmp_path / "receipt-worker-active-lease.db")
    storage = LocalProtectedFileStore(tmp_path / "worker-active-lease-files")
    source = _png()
    source_hash = hashlib.sha256(source).hexdigest()
    file_key = storage.save(source_hash, source, "image/png")
    lease_token = str(uuid4())

    with session_factory.begin() as session:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        upload = ReceiptUpload(
            source_sha256=source_hash,
            file_key=file_key,
            media_type="image/png",
            size_bytes=len(source),
            uploaded_by=manager.id,
            processing_status="RUNNING",
            processing_lease_token=lease_token,
            processing_lease_until=datetime.now(UTC) + timedelta(minutes=5),
            ocr_attempts=1,
        )
        session.add(upload)
        session.flush()
        upload_pk = upload.upload_pk

    class MustNotRunEngine:
        def extract(self, source: bytes, media_type: str) -> dict[str, Any]:
            raise AssertionError("Active duplicate delivery must not run OCR")

    processor = PersistedUploadProcessor(session_factory, storage, MustNotRunEngine())
    assert processor.process(upload_pk) == "RUNNING"
    with session_factory() as session:
        active_upload = session.get(ReceiptUpload, upload_pk)
        assert active_upload is not None
        assert active_upload.processing_lease_token == lease_token
        assert active_upload.ocr_attempts == 1
        assert session.scalar(select(func.count(Receipt.receipt_pk))) == 0
    engine.dispose()


def test_expired_worker_lease_is_redispatched_and_reclaimed(
    tmp_path: Path, monkeypatch: Any
) -> None:
    engine, session_factory = _database(tmp_path / "receipt-worker-lease.db")
    storage = LocalProtectedFileStore(tmp_path / "worker-lease-files")
    source = _png()
    source_hash = hashlib.sha256(source).hexdigest()
    file_key = storage.save(source_hash, source, "image/png")
    dispatched: list[str] = []
    expired_lease_id = str(uuid4())

    with session_factory.begin() as session:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        upload = ReceiptUpload(
            source_sha256=source_hash,
            file_key=file_key,
            media_type="image/png",
            size_bytes=len(source),
            uploaded_by=manager.id,
            processing_status="RUNNING",
            processing_lease_token=expired_lease_id,
            processing_lease_until=datetime.now(UTC) - timedelta(seconds=1),
            ocr_attempts=1,
        )
        session.add(upload)
        session.flush()
        session.add(
            ReceiptOutboxEvent(
                upload_pk=upload.upload_pk,
                event_type="PROCESS_RECEIPT_UPLOAD",
                dispatched_at=datetime.now(UTC) - timedelta(minutes=20),
                dispatch_attempts=1,
            )
        )
        upload_pk = upload.upload_pk

    monkeypatch.setattr("mbs.receipts.tasks.SessionLocal", session_factory)
    monkeypatch.setattr(process_receipt_upload, "delay", lambda key: dispatched.append(key))
    assert dispatch_pending_receipt_uploads.run() == 1
    assert dispatched == [upload_pk]

    class RetryEngine:
        def extract(self, source: bytes, media_type: str) -> dict[str, Any]:
            return _document("SYN-803")

    processor = PersistedUploadProcessor(session_factory, storage, RetryEngine())
    assert processor.process(upload_pk) == "SUCCEEDED"
    with session_factory() as session:
        recovered = session.get(ReceiptUpload, upload_pk)
        event = session.scalar(select(ReceiptOutboxEvent))
        assert recovered is not None
        assert recovered.processing_status == "SUCCEEDED"
        assert recovered.ocr_attempts == 2
        assert recovered.processing_lease_token is None
        assert event is not None and event.dispatch_attempts == 2
    engine.dispose()


def test_superseded_worker_lease_cannot_commit_stale_ocr_result(tmp_path: Path) -> None:
    engine, session_factory = _database(tmp_path / "receipt-worker-fenced.db")
    storage = LocalProtectedFileStore(tmp_path / "worker-fenced-files")
    source = _png()
    source_hash = hashlib.sha256(source).hexdigest()
    file_key = storage.save(source_hash, source, "image/png")

    with session_factory.begin() as session:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        upload = ReceiptUpload(
            source_sha256=source_hash,
            file_key=file_key,
            media_type="image/png",
            size_bytes=len(source),
            uploaded_by=manager.id,
            processing_status="QUEUED",
        )
        session.add(upload)
        session.flush()
        upload_pk = upload.upload_pk

    class SupersededEngine:
        def extract(self, source: bytes, media_type: str) -> dict[str, Any]:
            replacement_lease_id = str(uuid4())
            with session_factory.begin() as session:
                upload = session.get(ReceiptUpload, upload_pk)
                assert upload is not None
                upload.processing_lease_token = replacement_lease_id
                upload.processing_lease_until = datetime.now(UTC) + timedelta(minutes=10)
                self.replacement_lease_id = replacement_lease_id
            return _document("STALE-RESULT")

    ocr_engine = SupersededEngine()
    processor = PersistedUploadProcessor(session_factory, storage, ocr_engine)
    assert processor.process(upload_pk) == "RUNNING"
    with session_factory() as session:
        latest_upload = session.get(ReceiptUpload, upload_pk)
        assert latest_upload is not None
        assert latest_upload.processing_lease_token == ocr_engine.replacement_lease_id
        assert session.scalar(select(func.count(Receipt.receipt_pk))) == 0
    engine.dispose()


def test_periodic_outbox_publisher_dispatches_only_committed_uploads(
    tmp_path: Path, monkeypatch: Any
) -> None:
    engine, session_factory = _database(tmp_path / "receipt-outbox-publisher.db")
    with session_factory.begin() as session:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        source = _png()
        upload = ReceiptUpload(
            source_sha256="1" * 64,
            file_key="receipts/11/source.png",
            media_type="image/png",
            size_bytes=len(source),
            uploaded_by=manager.id,
            processing_status="QUEUED",
        )
        session.add(upload)
        session.flush()
        session.add(
            ReceiptOutboxEvent(upload_pk=upload.upload_pk, event_type="PROCESS_RECEIPT_UPLOAD")
        )
        upload_pk = upload.upload_pk

    monkeypatch.setattr("mbs.receipts.tasks.SessionLocal", session_factory)
    dispatched: list[str] = []
    monkeypatch.setattr(process_receipt_upload, "delay", lambda key: dispatched.append(key))
    assert dispatch_pending_receipt_uploads.run() == 1
    assert dispatched == [upload_pk]
    with session_factory() as session:
        event = session.scalar(select(ReceiptOutboxEvent))
        assert event is not None and event.dispatched_at is not None
        assert event.dispatch_attempts == 1
    engine.dispose()


def test_receipt_processing_task_requeues_after_worker_process_loss() -> None:
    task = celery_app.tasks["mbs.receipts.process_upload"]

    assert celery_app.conf.task_acks_late is True
    assert task.acks_late is True
    assert task.reject_on_worker_lost is True


def test_near_match_resolution_survives_app_restart_and_requires_csrf(
    tmp_path: Path, monkeypatch: Any
) -> None:
    engine, session_factory = _database(tmp_path / "near-match-route.db")
    monkeypatch.setenv("RECEIPT_STORAGE_PATH", str(tmp_path / "near-match-files"))
    dispatched: list[str] = []

    with session_factory.begin() as session:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        token, csrf = create_session(session, manager)

    def override_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    def dispatch_after_commit() -> None:
        assert dispatch_pending_receipt_uploads.run() == 1
        with session_factory() as session:
            event = session.scalar(select(ReceiptOutboxEvent))
            assert event is not None
            dispatched.append(event.upload_pk)

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    monkeypatch.setattr("mbs.receipts.tasks.SessionLocal", session_factory)
    monkeypatch.setattr(process_receipt_upload, "delay", lambda key: None)
    monkeypatch.setattr(receipt_routes, "_request_outbox_dispatch", dispatch_after_commit)
    try:
        with TestClient(app) as client:
            source = _png()
            manager_csrf_headers = {
                "Cookie": f"mbs_session={token}",
                "X-CSRF-Token": csrf,
            }
            service = app.state.receipt_upload_service
            fingerprint = service._perceptual_hasher.fingerprint(source, "image/png")
            service._perceptual_store.save("f" * 64, fingerprint)
            held = client.post(
                "/api/v1/receipts/upload",
                content=source,
                headers={**manager_csrf_headers, "Content-Type": "image/png"},
            )
            upload_pk = held.json()["upload_pk"]
        with TestClient(app) as restarted_client:
            unresolved = restarted_client.post(
                f"/api/v1/receipt-uploads/{upload_pk}/resolve-near-match",
                json={"process_as_new": True},
                headers={"Cookie": f"mbs_session={token}"},
            )
            resolved = restarted_client.post(
                f"/api/v1/receipt-uploads/{upload_pk}/resolve-near-match",
                json={"process_as_new": True},
                headers=manager_csrf_headers,
            )
    finally:
        app.dependency_overrides.clear()

    assert held.status_code == 200
    assert held.json()["status"] == UploadStatus.POSSIBLE_DUPLICATE.value
    assert unresolved.status_code == 403
    assert resolved.status_code == 200
    assert resolved.json()["status"] == UploadStatus.QUEUED.value
    assert dispatched == [upload_pk]
    with session_factory() as session:
        upload = session.get(ReceiptUpload, upload_pk)
        assert upload is not None and upload.processing_status == "QUEUED"
        assert session.scalar(select(func.count(ReceiptOutboxEvent.id))) == 1
    engine.dispose()


def test_app_startup_rehydrates_accepted_near_match_index(tmp_path: Path, monkeypatch: Any) -> None:
    engine, session_factory = _database(tmp_path / "persisted-fingerprint.db")
    storage_root = tmp_path / "persisted-fingerprint-files"
    storage = LocalProtectedFileStore(storage_root)
    original = _near_match_png()
    original_hash = hashlib.sha256(original).hexdigest()
    file_key = storage.save(original_hash, original, "image/png")
    fingerprint = PillowPerceptualHasher().fingerprint(original, "image/png")
    monkeypatch.setenv("RECEIPT_STORAGE_PATH", str(storage_root))

    with session_factory.begin() as session:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        token, csrf = create_session(session, manager)
        session.add(
            ReceiptUpload(
                source_sha256=original_hash,
                file_key=file_key,
                media_type="image/png",
                size_bytes=len(original),
                uploaded_by=manager.id,
                processing_status="SUCCEEDED",
                scan_status="NOT_SCANNED",
                perceptual_hash=fingerprint,
            )
        )

    def override_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/receipts/upload",
                content=_near_match_png(1),
                headers={
                    "Content-Type": "image/png",
                    "Cookie": f"mbs_session={token}",
                    "X-CSRF-Token": csrf,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == UploadStatus.POSSIBLE_DUPLICATE.value
    with session_factory() as session:
        outbox_count = session.scalar(select(func.count(ReceiptOutboxEvent.id)))
        held_upload = session.get(ReceiptUpload, response.json()["upload_pk"])
        assert outbox_count == 0
        assert held_upload is not None and held_upload.processing_status == "POSSIBLE_DUPLICATE"
    engine.dispose()
