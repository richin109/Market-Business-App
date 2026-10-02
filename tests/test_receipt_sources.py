from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from mbs.auth import Role, create_session, create_user
from mbs.db import get_session
from mbs.items import confirm_store_item_mapping
from mbs.main import app
from mbs.models import (
    AuditLog,
    Receipt,
    ReceiptCorrection,
    ReceiptItem,
    ReceiptLineApproval,
    ReceiptRoutingRecord,
    ReceiptSource,
    ReceiptUpload,
    StoreItem,
)
from mbs.receipts.approval import DispositionSubtype, approve_receipt_item
from mbs.receipts.ocr import BusinessDisposition, normalize_receipt
from mbs.receipts.persistence import persist_extracted_receipt, persist_source_candidate
from mbs.receipts.sources import SourceDecision, decide_receipt_source
from mbs.receipts.storage import LocalProtectedFileStore
from mbs.receipts.upload import ReceiptUploadService
from mbs.routers.dependencies import get_receipt_upload_service
from tests.database import postgres_test_url


def _database(path: Path, revision: str = "head") -> Any:
    engine = create_engine(postgres_test_url(path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(path).replace("%", "%%"))
    command.upgrade(config, revision)
    return engine


def _document(
    transaction_number: str,
    line_total: str,
    subtotal: str = "3.00",
    total: str = "3.00",
    source_page: int | None = None,
    source_line_number: int | None = None,
) -> dict[str, Any]:
    item: dict[str, object] = {
        "description": "Milk",
        "line_total": line_total,
        "store_product_id": "MILK-SOURCE-1",
    }
    if source_page is not None:
        item["source_page"] = source_page
    if source_line_number is not None:
        item["source_line_number"] = source_line_number
    return {
        "receipt": {
            "store": "Synthetic Source Market",
            "date": "2026-09-30",
            "time": "14:05:06",
            "transaction_number": transaction_number,
            "subtotal": subtotal,
            "tax": "0.00",
            "total": total,
        },
        "items": [item],
    }


def _multi_line_document(
    transaction_number: str,
    lines: list[dict[str, object]],
    subtotal: str,
) -> dict[str, Any]:
    document = _document(transaction_number, subtotal, subtotal=subtotal, total=subtotal)
    document["items"] = lines
    return document


def _upload(source_hash: str, actor_id: int) -> ReceiptUpload:
    return ReceiptUpload(
        source_sha256=source_hash * 64,
        file_key=f"receipts/{source_hash * 64}.pdf",
        media_type="application/pdf",
        size_bytes=100,
        uploaded_by=actor_id,
        processing_status="QUEUED",
    )


def test_copy_and_supplement_keep_occurrence_provenance_and_are_idempotent(
    tmp_path: Path,
) -> None:
    engine = _database(tmp_path / "source-association.db")
    with Session(engine) as session:
        reviewer = create_user(session, "source-review-manager", "synthetic password", Role.MANAGER)
        primary_upload = _upload("a", reviewer.id)
        session.add(primary_upload)
        session.flush()
        receipt = persist_extracted_receipt(
            session,
            normalize_receipt(_document("SOURCE-ORDER-1", "1.00")),
            primary_upload,
        )
        primary_line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
        )
        assert primary_line is not None and primary_line.store_item_id is not None
        primary_store_item = session.get(StoreItem, primary_line.store_item_id)
        assert primary_store_item is not None and primary_line.item_id is not None
        confirm_store_item_mapping(
            session,
            primary_store_item.store_item_id,
            primary_line.item_id,
            reviewer.id,
        )
        with pytest.raises(ValueError, match="totals must reconcile"):
            approve_receipt_item(
                session,
                primary_line.id,
                reviewer.id,
                BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
                "source-primary-expense-approval",
                DispositionSubtype.DIRECT_EXPENSE,
            )
        overlapping_upload = _upload("b", reviewer.id)
        supplemental_upload = _upload("c", reviewer.id)
        rejected_upload = _upload("k", reviewer.id)
        session.add_all([overlapping_upload, supplemental_upload, rejected_upload])
        session.flush()
        overlapping_source = persist_source_candidate(
            session,
            normalize_receipt(_document("SOURCE-ORDER-1", "1.00")),
            overlapping_upload,
            receipt,
        )
        supplemental_source = persist_source_candidate(
            session,
            normalize_receipt(
                _document("SOURCE-ORDER-1", "2.00", source_page=2, source_line_number=4)
            ),
            supplemental_upload,
            receipt,
        )
        rejected_source = persist_source_candidate(
            session,
            normalize_receipt(_document("SOURCE-ORDER-1", "1.00")),
            rejected_upload,
            receipt,
        )
        receipt_pk = receipt.receipt_pk
        overlapping_source_id = overlapping_source.id
        supplemental_source_id = supplemental_source.id
        rejected_source_id = rejected_source.id
        overlapping_upload_pk = overlapping_upload.upload_pk
        supplemental_upload_pk = supplemental_upload.upload_pk
        rejected_upload_pk = rejected_upload.upload_pk
        session.commit()

        copied = decide_receipt_source(
            session,
            receipt_pk,
            overlapping_source_id,
            reviewer.id,
            SourceDecision.COPY,
            "The second full scan overlaps the accepted source",
            "source-copy-event-1",
        )
        rejected = decide_receipt_source(
            session,
            receipt_pk,
            rejected_source_id,
            reviewer.id,
            SourceDecision.REJECT,
            "This source is not part of the accepted order",
            "source-reject-event-1",
        )
        with pytest.raises(ValueError, match="explicitly confirm each repeated source line"):
            decide_receipt_source(
                session,
                receipt_pk,
                supplemental_source_id,
                reviewer.id,
                SourceDecision.SUPPLEMENT,
                "The second line is an additional purchase occurrence",
                "source-supplement-event-1",
            )
        supplemented = decide_receipt_source(
            session,
            receipt_pk,
            supplemental_source_id,
            reviewer.id,
            SourceDecision.SUPPLEMENT,
            "The second line is an additional purchase occurrence",
            "source-supplement-event-1",
            confirmed_repeated_line_indexes=(0,),
        )
        approve_receipt_item(
            session,
            primary_line.id,
            reviewer.id,
            BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
            "source-primary-expense-approval",
            DispositionSubtype.DIRECT_EXPENSE,
        )
        retry = decide_receipt_source(
            session,
            receipt_pk,
            supplemental_source_id,
            reviewer.id,
            SourceDecision.SUPPLEMENT,
            "The second line is an additional purchase occurrence",
            "source-supplement-event-1",
            confirmed_repeated_line_indexes=(0,),
        )
        with pytest.raises(ValueError, match="reused with another request"):
            decide_receipt_source(
                session,
                receipt_pk,
                supplemental_source_id,
                reviewer.id,
                SourceDecision.REJECT,
                "Different decision",
                "source-supplement-event-1",
            )
        with pytest.raises(ValueError, match="Source decision event ID was reused"):
            decide_receipt_source(
                session,
                receipt_pk,
                supplemental_source_id,
                reviewer.id,
                SourceDecision.SUPPLEMENT,
                "The second line is an additional purchase occurrence",
                "source-supplement-event-1",
                confirmed_repeated_line_indexes=(),
            )
        session.commit()

        lines = session.scalars(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt_pk).order_by(ReceiptItem.id)
        ).all()
        saved_receipt = session.get(Receipt, receipt_pk)
        sources = session.scalars(
            select(ReceiptSource).where(ReceiptSource.receipt_pk == receipt_pk)
        ).all()
        audit_rows = session.scalars(
            select(AuditLog).where(AuditLog.event_type == "RECEIPT_SOURCE_DECIDED")
        ).all()
        corrections = session.scalars(
            select(ReceiptCorrection).where(ReceiptCorrection.receipt_pk == receipt_pk)
        ).all()
        approval_count = session.scalar(
            select(func.count(ReceiptLineApproval.id))
            .join(ReceiptItem, ReceiptItem.id == ReceiptLineApproval.receipt_item_id)
            .where(ReceiptItem.receipt_pk == receipt_pk)
        )
        route_count = session.scalar(
            select(func.count(ReceiptRoutingRecord.id))
            .join(ReceiptItem, ReceiptItem.id == ReceiptRoutingRecord.receipt_item_id)
            .where(ReceiptItem.receipt_pk == receipt_pk)
        )

    assert copied.added_line_count == 0
    assert rejected.added_line_count == 0
    assert supplemented.added_line_count == 1
    assert retry.idempotent is True
    assert supplemented.source.confirmed_repeated_line_indexes == [0]
    assert len(lines) == 2
    assert lines[0].source_id != lines[1].source_id
    assert (lines[0].source_page, lines[0].source_line_number) == (1, 1)
    assert (lines[1].source_page, lines[1].source_line_number) == (2, 4)
    assert saved_receipt is not None and saved_receipt.receipt_document_version == 2
    assert saved_receipt.receipt_document is not None
    saved_items = saved_receipt.receipt_document.get("items")
    assert isinstance(saved_items, list)
    assert len(saved_items) == 2
    assert sum((line.line_total for line in lines), start=0) == 3
    assert {source.association_kind for source in sources} == {
        "PRIMARY",
        "COPY",
        "SUPPLEMENT",
        "REJECTED",
    }
    assert len(audit_rows) == 3
    assert len(corrections) == 1
    assert approval_count == 1
    assert route_count == 1
    with Session(engine) as session:
        upload_statuses = dict(
            session.execute(
                select(ReceiptUpload.upload_pk, ReceiptUpload.processing_status).where(
                    ReceiptUpload.upload_pk.in_(
                        [overlapping_upload_pk, supplemental_upload_pk, rejected_upload_pk]
                    )
                )
            ).all()
        )
    assert upload_statuses[overlapping_upload_pk] == "DUPLICATE"
    assert upload_statuses[supplemental_upload_pk] == "SUCCEEDED"
    assert upload_statuses[rejected_upload_pk] == "DUPLICATE"
    engine.dispose()


def test_rm_022_full_copy_and_repeated_supplement_reconcile_once(tmp_path: Path) -> None:
    engine = _database(tmp_path / "rm-022-multi-source.db")
    with Session(engine) as session:
        reviewer = create_user(session, "rm-022-manager", "synthetic password", Role.MANAGER)
        transaction_number = "SYN-17"
        full_lines: list[dict[str, object]] = [
            {
                "description": "Milk",
                "line_total": "10.00",
                "store_product_id": "MILK-SOURCE-17",
                "source_page": 1,
                "source_line_number": 1,
            },
            {
                "description": "Bread",
                "line_total": "10.00",
                "store_product_id": "BREAD-SOURCE-17",
                "source_page": 1,
                "source_line_number": 2,
            },
        ]
        primary_upload = _upload("l", reviewer.id)
        session.add(primary_upload)
        session.flush()
        receipt = persist_extracted_receipt(
            session,
            normalize_receipt(_multi_line_document(transaction_number, full_lines, "32.50")),
            primary_upload,
        )
        copy_upload = _upload("m", reviewer.id)
        partial_upload = _upload("n", reviewer.id)
        session.add_all([copy_upload, partial_upload])
        session.flush()
        copy_source = persist_source_candidate(
            session,
            normalize_receipt(_multi_line_document(transaction_number, full_lines, "32.50")),
            copy_upload,
            receipt,
        )
        partial_lines: list[dict[str, object]] = [
            {
                "description": "Milk",
                "line_total": "12.50",
                "store_product_id": "MILK-SOURCE-17",
                "source_page": 2,
                "source_line_number": 4,
            }
        ]
        partial_source = persist_source_candidate(
            session,
            normalize_receipt(_multi_line_document(transaction_number, partial_lines, "32.50")),
            partial_upload,
            receipt,
        )
        primary_snapshot = json.loads(json.dumps(receipt.raw_ocr_document))
        copy_snapshot = json.loads(json.dumps(copy_source.raw_ocr_document))
        partial_snapshot = json.loads(json.dumps(partial_source.raw_ocr_document))
        receipt_pk = receipt.receipt_pk
        copy_source_id = copy_source.id
        partial_source_id = partial_source.id
        session.commit()

        copy_decision = decide_receipt_source(
            session,
            receipt_pk,
            copy_source_id,
            reviewer.id,
            SourceDecision.COPY,
            "The full scan overlaps the accepted source",
            "rm-022-copy-v1",
        )
        with pytest.raises(ValueError, match="explicitly confirm each repeated source line"):
            decide_receipt_source(
                session,
                receipt_pk,
                partial_source_id,
                reviewer.id,
                SourceDecision.SUPPLEMENT,
                "The partial scan proves a separate purchase occurrence",
                "rm-022-supplement-v1",
            )
        supplemental = decide_receipt_source(
            session,
            receipt_pk,
            partial_source_id,
            reviewer.id,
            SourceDecision.SUPPLEMENT,
            "The partial scan proves a separate purchase occurrence",
            "rm-022-supplement-v1",
            confirmed_repeated_line_indexes=(0,),
        )
        retry = decide_receipt_source(
            session,
            receipt_pk,
            partial_source_id,
            reviewer.id,
            SourceDecision.SUPPLEMENT,
            "The partial scan proves a separate purchase occurrence",
            "rm-022-supplement-v1",
            confirmed_repeated_line_indexes=(0,),
        )
        session.commit()
        saved_receipt = session.get(Receipt, receipt_pk)
        lines = session.scalars(
            select(ReceiptItem)
            .where(ReceiptItem.receipt_pk == receipt_pk, ReceiptItem.is_excluded.is_(False))
            .order_by(ReceiptItem.id)
        ).all()
        sources = session.scalars(
            select(ReceiptSource)
            .where(ReceiptSource.receipt_pk == receipt_pk)
            .order_by(ReceiptSource.id)
        ).all()
        correction_count = session.scalar(
            select(func.count(ReceiptCorrection.id)).where(
                ReceiptCorrection.receipt_pk == receipt_pk
            )
        )
        approval_count = session.scalar(
            select(func.count(ReceiptLineApproval.id))
            .join(ReceiptItem, ReceiptItem.id == ReceiptLineApproval.receipt_item_id)
            .where(ReceiptItem.receipt_pk == receipt_pk)
        )
        routing_count = session.scalar(
            select(func.count(ReceiptRoutingRecord.id))
            .join(ReceiptItem, ReceiptItem.id == ReceiptRoutingRecord.receipt_item_id)
            .where(ReceiptItem.receipt_pk == receipt_pk)
        )

        assert copy_decision.added_line_count == 0
        assert supplemental.added_line_count == 1
        assert retry.idempotent is True
        assert saved_receipt is not None and saved_receipt.receipt_document is not None
        assert len(lines) == 3
        assert sum((line.line_total for line in lines), Decimal("0")) == Decimal("32.50")
        assert saved_receipt.subtotal == Decimal("32.50")
        assert saved_receipt.receipt_document["total_mismatch"] is False
        assert (lines[2].source_id, lines[2].source_page, lines[2].source_line_number) == (
            partial_source_id,
            2,
            4,
        )
        assert [source.association_kind for source in sources] == [
            "PRIMARY",
            "COPY",
            "SUPPLEMENT",
        ]
        assert sources[2].confirmed_repeated_line_indexes == [0]
        assert sources[0].raw_ocr_document == primary_snapshot
        assert sources[1].raw_ocr_document == copy_snapshot
        assert sources[2].raw_ocr_document == partial_snapshot
        assert correction_count == 1
        assert approval_count == routing_count == 0
    engine.dispose()


def test_supplement_subtotal_mismatch_remains_held_and_retry_does_not_mutate(
    tmp_path: Path,
) -> None:
    engine = _database(tmp_path / "source-subtotal-hold.db")
    with Session(engine) as session:
        reviewer = create_user(session, "source-hold-manager", "synthetic password", Role.MANAGER)
        primary_upload = _upload("d", reviewer.id)
        session.add(primary_upload)
        session.flush()
        receipt = persist_extracted_receipt(
            session,
            normalize_receipt(_document("SOURCE-ORDER-2", "1.00")),
            primary_upload,
        )
        candidate_upload = _upload("e", reviewer.id)
        session.add(candidate_upload)
        session.flush()
        source = persist_source_candidate(
            session,
            normalize_receipt(_document("SOURCE-ORDER-2", "3.00")),
            candidate_upload,
            receipt,
        )
        receipt_pk = receipt.receipt_pk
        source_id = source.id
        session.commit()

        first = decide_receipt_source(
            session,
            receipt_pk,
            source_id,
            reviewer.id,
            SourceDecision.SUPPLEMENT,
            "Attempt supplement",
            "source-hold-event-1",
        )
        with pytest.raises(ValueError, match="reused with another request"):
            decide_receipt_source(
                session,
                receipt_pk,
                source_id,
                reviewer.id,
                SourceDecision.SUPPLEMENT,
                "Altered hold reason",
                "source-hold-event-1",
            )
        replay = decide_receipt_source(
            session,
            receipt_pk,
            source_id,
            reviewer.id,
            SourceDecision.SUPPLEMENT,
            "Attempt supplement",
            "source-hold-event-1",
        )
        line_count = session.scalar(
            select(func.count(ReceiptItem.id)).where(ReceiptItem.receipt_pk == receipt_pk)
        )
        current_source = session.get(ReceiptSource, source_id)
        source_state = (
            current_source.association_kind if current_source is not None else None,
            current_source.hold_reason if current_source is not None else None,
            current_source.decision_event_id if current_source is not None else None,
        )
        session.commit()

    assert first.held is True
    assert replay.held is True and replay.idempotent is True
    assert line_count == 1
    assert source_state[0] == "PENDING"
    assert source_state[1] is not None
    assert source_state[2] is None
    engine.dispose()


def test_source_migration_backfills_existing_upload_and_line_provenance(
    tmp_path: Path,
) -> None:
    path = tmp_path / "source-backfill.db"
    engine = _database(path)
    with Session(engine) as session:
        actor = create_user(session, "source-migration-manager", "synthetic password", Role.MANAGER)
        upload = _upload("f", actor.id)
        session.add(upload)
        session.flush()
        receipt = persist_extracted_receipt(
            session,
            normalize_receipt(_document("SOURCE-ORDER-3", "3.00")),
            upload,
        )
        receipt.page_number = 3
        receipt_pk = receipt.receipt_pk
        session.commit()
    engine.dispose()

    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(path).replace("%", "%%"))
    command.downgrade(config, "0017_receipt_approval_versions")
    command.upgrade(config, "head")
    engine = create_engine(postgres_test_url(path))
    with Session(engine) as session:
        source = session.scalar(select(ReceiptSource).where(ReceiptSource.receipt_pk == receipt_pk))
        line = session.scalar(select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt_pk))
        saved_receipt = session.get(Receipt, receipt_pk)
    assert source is not None and source.association_kind == "PRIMARY"
    raw_header = source.raw_ocr_document.get("receipt")
    assert isinstance(raw_header, dict)
    assert raw_header.get("transaction_number") == "SOURCE-ORDER-3"
    assert line is not None and line.source_id == source.id
    assert line.source_page == 3 and line.source_line_number == 1
    extracted_document = json.loads(json.dumps(source.extracted_document))
    assert extracted_document["items"][0]["description"] == "Milk"
    assert extracted_document["items"][0]["source_page"] == 3
    assert saved_receipt is not None and saved_receipt.receipt_document is not None
    saved_items = saved_receipt.receipt_document.get("items")
    assert isinstance(saved_items, list) and isinstance(saved_items[0], dict)
    assert saved_items[0].get("source_id") == source.id
    engine.dispose()


def test_supplement_header_conflict_remains_held(tmp_path: Path) -> None:
    engine = _database(tmp_path / "source-header-hold.db")
    with Session(engine) as session:
        reviewer = create_user(session, "source-header-manager", "synthetic password", Role.MANAGER)
        primary_upload = _upload("i", reviewer.id)
        session.add(primary_upload)
        session.flush()
        receipt = persist_extracted_receipt(
            session,
            normalize_receipt(_document("SOURCE-ORDER-4", "1.00")),
            primary_upload,
        )
        candidate_upload = _upload("j", reviewer.id)
        session.add(candidate_upload)
        session.flush()
        source = persist_source_candidate(
            session,
            normalize_receipt(_document("SOURCE-ORDER-4", "2.00", total="4.00")),
            candidate_upload,
            receipt,
        )
        receipt_pk = receipt.receipt_pk
        source_id = source.id
        session.commit()

        result = decide_receipt_source(
            session,
            receipt_pk,
            source_id,
            reviewer.id,
            SourceDecision.SUPPLEMENT,
            "Conflicting total should remain held",
            "source-header-hold-1",
        )
        line_count = session.scalar(
            select(func.count(ReceiptItem.id)).where(ReceiptItem.receipt_pk == receipt_pk)
        )
        current_source = session.get(ReceiptSource, source_id)
        hold_reason = current_source.hold_reason if current_source is not None else None
        session.commit()

    assert result.held is True
    assert line_count == 1
    assert hold_reason == "Source total conflicts with the accepted receipt header"
    engine.dispose()


def test_source_decision_api_requires_manager_csrf_and_exposes_provenance(
    tmp_path: Path,
) -> None:
    engine = _database(tmp_path / "source-decision-api.db")
    with Session(engine) as session:
        manager = create_user(session, "source-api-manager", "synthetic password", Role.MANAGER)
        viewer = create_user(session, "source-api-viewer", "synthetic password", Role.VIEWER)
        manager_token, manager_csrf = create_session(session, manager)
        viewer_token, viewer_csrf = create_session(session, viewer)
        primary_upload = _upload("g", manager.id)
        session.add(primary_upload)
        session.flush()
        receipt = persist_extracted_receipt(
            session,
            normalize_receipt(_document("SOURCE-ORDER-API", "1.00")),
            primary_upload,
        )
        candidate_upload = _upload("h", manager.id)
        session.add(candidate_upload)
        session.flush()
        candidate = persist_source_candidate(
            session,
            normalize_receipt(_document("SOURCE-ORDER-API", "2.00")),
            candidate_upload,
            receipt,
        )
        receipt_pk = receipt.receipt_pk
        source_id = candidate.id
        session.commit()

    def override_session() -> Any:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    path = f"/api/v1/receipts/{receipt_pk}/sources/{source_id}/decision"
    payload = {
        "decision": "SUPPLEMENT",
        "reason": "The second line is a distinct purchase occurrence",
        "source_event_id": "source-api-supplement-1",
    }
    confirmed_payload = {
        **payload,
        "confirmed_repeated_line_indexes": [0],
    }
    try:
        client = TestClient(app)
        no_csrf = client.post(
            path,
            json=payload,
            headers={"Cookie": f"mbs_session={manager_token}"},
        )
        denied = client.post(
            path,
            json=payload,
            headers={
                "Cookie": f"mbs_session={viewer_token}",
                "X-CSRF-Token": viewer_csrf,
            },
        )
        unconfirmed = client.post(
            path,
            json=payload,
            headers={
                "Cookie": f"mbs_session={manager_token}",
                "X-CSRF-Token": manager_csrf,
            },
        )
        accepted = client.post(
            path,
            json=confirmed_payload,
            headers={
                "Cookie": f"mbs_session={manager_token}",
                "X-CSRF-Token": manager_csrf,
            },
        )
        retry = client.post(
            path,
            json=confirmed_payload,
            headers={
                "Cookie": f"mbs_session={manager_token}",
                "X-CSRF-Token": manager_csrf,
            },
        )
        details = client.get(
            f"/api/v1/receipts/{receipt_pk}",
            headers={"Cookie": f"mbs_session={manager_token}"},
        )
    finally:
        app.dependency_overrides.clear()

    assert no_csrf.status_code == 403
    assert denied.status_code == 403
    assert unconfirmed.status_code == 409
    assert accepted.status_code == 200
    assert accepted.json()["association_kind"] == "SUPPLEMENT"
    assert accepted.json()["added_line_count"] == 1
    assert retry.status_code == 200 and retry.json()["idempotent"] is True
    assert details.status_code == 200
    assert [source["association_kind"] for source in details.json()["sources"]] == [
        "PRIMARY",
        "SUPPLEMENT",
    ]
    assert details.json()["sources"][1]["confirmed_repeated_line_indexes"] == [0]
    assert len(details.json()["items"]) == 2
    assert details.json()["items"][1]["source_id"] == source_id
    engine.dispose()


def test_source_content_is_manager_only_and_receipt_scoped(tmp_path: Path) -> None:
    engine = _database(tmp_path / "source-content-api.db")
    source_bytes = b"%PDF-1.7 synthetic protected source"
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    file_store = LocalProtectedFileStore(tmp_path / "source-content-files")
    file_key = file_store.save(source_hash, source_bytes, "application/pdf")
    service = ReceiptUploadService(file_store=file_store)
    with Session(engine) as session:
        manager = create_user(session, "source-content-manager", "synthetic password", Role.MANAGER)
        viewer = create_user(session, "source-content-viewer", "synthetic password", Role.VIEWER)
        manager_token, _ = create_session(session, manager)
        viewer_token, _ = create_session(session, viewer)
        upload = ReceiptUpload(
            source_sha256=source_hash,
            file_key=file_key,
            media_type="application/pdf",
            size_bytes=len(source_bytes),
            uploaded_by=manager.id,
            processing_status="SUCCEEDED",
            page_count=3,
        )
        session.add(upload)
        session.flush()
        receipt = persist_extracted_receipt(
            session,
            normalize_receipt(_document("SOURCE-CONTENT-1", "3.00")),
            upload,
        )
        source_id = session.scalar(
            select(ReceiptSource.id).where(ReceiptSource.receipt_pk == receipt.receipt_pk)
        )
        receipt_pk = receipt.receipt_pk
        assert source_id is not None
        session.commit()

    def override_session() -> Any:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_receipt_upload_service] = lambda: service
    try:
        client = TestClient(app)
        path = f"/api/v1/receipts/{receipt_pk}/sources/{source_id}/content"
        manager_response = client.get(path, headers={"Cookie": f"mbs_session={manager_token}"})
        viewer_response = client.get(path, headers={"Cookie": f"mbs_session={viewer_token}"})
        wrong_receipt = client.get(
            f"/api/v1/receipts/not-the-owner/sources/{source_id}/content",
            headers={"Cookie": f"mbs_session={manager_token}"},
        )
    finally:
        app.dependency_overrides.clear()

    assert manager_response.status_code == 200
    assert manager_response.content == source_bytes
    assert manager_response.headers["content-type"] == "application/pdf"
    assert manager_response.headers["cache-control"] == "private, no-store, max-age=0"
    assert manager_response.headers["x-content-type-options"] == "nosniff"
    assert "inline" in manager_response.headers["content-disposition"]
    assert viewer_response.status_code == 403
    assert wrong_receipt.status_code == 404
    engine.dispose()
