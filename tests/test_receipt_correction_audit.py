from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from mbs.auth import Role, create_session, create_user
from mbs.db import get_session
from mbs.main import app
from mbs.models import (
    AuditLog,
    Receipt,
    ReceiptCorrection,
    ReceiptCorrectionHold,
    ReceiptItem,
    StoreItem,
)
from mbs.receipts.ocr import normalize_receipt
from mbs.receipts.persistence import persist_extracted_receipt
from tests.database import postgres_test_url


def test_correction_audit_migration_downgrades_and_reupgrades(tmp_path: Path) -> None:
    database_path = tmp_path / "correction-migration.db"
    engine = create_engine(postgres_test_url(database_path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(database_path).replace("%", "%%"))
    command.upgrade(config, "head")

    assert inspect(engine).has_table("tbl_receipt_corrections")
    assert "receipt_document_version" in {
        column["name"] for column in inspect(engine).get_columns("tbl_receipts")
    }

    command.downgrade(config, "0006_line_approvals")
    assert not inspect(engine).has_table("tbl_receipt_corrections")
    assert "receipt_document_version" not in {
        column["name"] for column in inspect(engine).get_columns("tbl_receipts")
    }
    command.upgrade(config, "head")
    assert inspect(engine).has_table("tbl_receipt_corrections")
    engine.dispose()


def test_line_review_migration_refuses_downgrade_with_excluded_evidence(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "excluded-line-downgrade.db"
    engine = create_engine(postgres_test_url(database_path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(database_path).replace("%", "%%"))
    command.upgrade(config, "head")

    with Session(engine) as session:
        create_user(session, "manager", "manager password", Role.MANAGER)
        receipt = persist_extracted_receipt(session, _receipt("TC-EXCLUDED-MIGRATION"))
        line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
        )
        assert line is not None
        line.is_excluded = True
        line.exclusion_reason = "Preserve reviewed source evidence"
        session.commit()

    with pytest.raises(RuntimeError, match="reviewer-excluded receipt lines"):
        command.downgrade(config, "0020_receipt_item_package_capture")
    engine.dispose()


def test_correction_and_admin_hold_resolution_routes_are_audited(tmp_path: Path) -> None:
    database_path = tmp_path / "receipt-correction-audit.db"
    engine = create_engine(postgres_test_url(database_path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(database_path).replace("%", "%%"))
    command.upgrade(config, "head")

    with Session(engine) as session:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        admin = create_user(session, "admin", "admin password", Role.ADMIN)
        admin_id = admin.id
        manager_token, manager_csrf = create_session(session, manager)
        admin_token, admin_csrf = create_session(session, admin)
        receipts = [
            persist_extracted_receipt(session, _receipt(f"TC-{number}"))
            for number in range(101, 105)
        ]
        receipts[0].source_type = "MANUAL"
        session.commit()

        def override_session() -> Iterator[Session]:
            yield session

        app.dependency_overrides[get_session] = override_session
        try:
            client = TestClient(app)
            manager_headers = {"Cookie": f"mbs_session={manager_token}"}
            manager_csrf_headers = {
                **manager_headers,
                "X-CSRF-Token": manager_csrf,
            }
            added_line_id = session.scalar(
                select(ReceiptItem.id).where(ReceiptItem.receipt_pk == receipts[0].receipt_pk)
            )
            assert added_line_id is not None
            manual_correction_url = f"/api/v1/receipts/{receipts[0].receipt_pk}/corrections"
            manual_correction_payload: dict[str, Any] = {
                "reason": "Correct manual line count and retain the misread row",
                "source_event_id": "receipt-correction:manual-lines:v1",
                "header_updates": {"subtotal": "0.50", "total": "0.50"},
                "item_exclusions": [added_line_id],
                "item_additions": [
                    {
                        "description": "Milk",
                        "category": "Dairy",
                        "package_count": "1",
                        "pack_size": "1",
                        "pack_unit": "each",
                        "unit_price": "0.50",
                        "confirm_repeated_occurrence": True,
                    }
                ],
            }
            unconfirmed_repeat = {
                **manual_correction_payload,
                "source_event_id": "receipt-correction:manual-lines-unconfirmed:v1",
                "item_exclusions": [],
                "header_updates": {},
                "item_additions": [
                    {
                        **manual_correction_payload["item_additions"][0],
                        "confirm_repeated_occurrence": False,
                    }
                ],
            }
            unconfirmed_response = client.post(
                manual_correction_url,
                json=unconfirmed_repeat,
                headers=manager_csrf_headers,
            )
            assert unconfirmed_response.status_code == 400
            manual_correction = client.post(
                manual_correction_url,
                json=manual_correction_payload,
                headers=manager_csrf_headers,
            )
            manual_retry = client.post(
                manual_correction_url,
                json=manual_correction_payload,
                headers=manager_csrf_headers,
            )
            assert manual_correction.status_code == manual_retry.status_code == 200
            assert manual_retry.json()["idempotent"] is True
            admin_headers = {"Cookie": f"mbs_session={admin_token}"}
            admin_csrf_headers = {
                **admin_headers,
                "X-CSRF-Token": admin_csrf,
            }

            correction_url = f"/api/v1/receipts/{receipts[1].receipt_pk}/corrections"
            correction_payload = {
                "reason": "Correct the transaction number",
                "source_event_id": "receipt-correction:second:v1",
                "header_updates": {"transaction_number": "TC-101"},
            }
            missing_reason = client.post(
                correction_url,
                json={"source_event_id": "receipt-correction:no-reason:v1"},
                headers=manager_csrf_headers,
            )
            assert missing_reason.status_code == 422
            denied = client.post(
                correction_url,
                json=correction_payload,
                headers=manager_headers,
            )
            assert denied.status_code == 403
            created = client.post(
                correction_url,
                json=correction_payload,
                headers=manager_csrf_headers,
            )
            assert created.status_code == 200
            hold_id = created.json()["hold_id"]
            assert created.json()["status"] == "HELD_FOR_ADMIN"
            retried = client.post(
                correction_url,
                json=correction_payload,
                headers=manager_csrf_headers,
            )
            assert retried.status_code == 200
            assert retried.json()["hold_id"] == hold_id
            assert retried.json()["idempotent"] is True
            manager_holds = client.get("/api/v1/receipt-correction-holds", headers=manager_headers)
            admin_holds = client.get("/api/v1/receipt-correction-holds", headers=admin_headers)
            assert manager_holds.status_code == 403
            assert admin_holds.json()[0]["id"] == hold_id

            resolution_url = f"/api/v1/receipt-correction-holds/{hold_id}/resolve"
            rekey_payload = {
                "action": "REKEY",
                "reason": "Preserve both distinct purchases",
                "new_transaction_number": "TC-201",
            }
            denied_manager = client.post(
                resolution_url,
                json=rekey_payload,
                headers=manager_csrf_headers,
            )
            denied_csrf = client.post(
                resolution_url,
                json=rekey_payload,
                headers=admin_headers,
            )
            assert denied_manager.status_code == 403
            assert denied_csrf.status_code == 403
            resolved = client.post(
                resolution_url,
                json=rekey_payload,
                headers=admin_csrf_headers,
            )
            assert resolved.status_code == 200
            assert resolved.json()["status"] == "REKEY"

            additional_holds: list[int] = []
            for index, receipt in enumerate(receipts[2:], start=2):
                response = client.post(
                    f"/api/v1/receipts/{receipt.receipt_pk}/corrections",
                    json={
                        "reason": "Resolve duplicate transaction identity",
                        "source_event_id": f"receipt-correction:hold:{index}",
                        "header_updates": {"transaction_number": "TC-101"},
                    },
                    headers=manager_csrf_headers,
                )
                assert response.status_code == 200
                additional_holds.append(response.json()["hold_id"])

            keep_response = client.post(
                f"/api/v1/receipt-correction-holds/{additional_holds[0]}/resolve",
                json={"action": "KEEP", "reason": "The original values are authoritative"},
                headers=admin_csrf_headers,
            )
            reject_response = client.post(
                f"/api/v1/receipt-correction-holds/{additional_holds[1]}/resolve",
                json={"action": "REJECT", "reason": "This upload is not a valid receipt"},
                headers=admin_csrf_headers,
            )
            assert keep_response.status_code == reject_response.status_code == 200
            assert keep_response.json()["status"] == "KEEP"
            assert reject_response.json()["status"] == "REJECT"
            session.expire_all()
            persisted = session.get(Receipt, receipts[1].receipt_pk)
            rekey_hold = session.get(ReceiptCorrectionHold, hold_id)
            rejected = session.get(Receipt, receipts[3].receipt_pk)
            corrections = session.scalars(select(ReceiptCorrection)).all()
            audit_types = set(session.scalars(select(AuditLog.event_type)).all())
            corrected_manual_lines = session.scalars(
                select(ReceiptItem)
                .where(ReceiptItem.receipt_pk == receipts[0].receipt_pk)
                .order_by(ReceiptItem.id)
            ).all()
            generated_store_item = session.get(StoreItem, corrected_manual_lines[1].store_item_id)
        finally:
            app.dependency_overrides.clear()

    assert persisted is not None
    assert persisted.receipt_id.endswith("|TC-201")
    assert persisted.receipt_document_version == 2
    assert rekey_hold is not None
    assert rekey_hold.resolution_action == "REKEY"
    assert rejected is not None and rejected.deleted_at is not None
    assert len(corrections) == 2
    admin_correction = next(
        correction
        for correction in corrections
        if correction.request_document.get("new_transaction_number") == "TC-201"
    )
    manual_correction_record = next(
        correction
        for correction in corrections
        if correction.source_event_id == "receipt-correction:manual-lines:v1"
    )
    assert admin_correction.actor_id == admin_id
    added_items = manual_correction_record.after_document["items"]
    assert isinstance(added_items, list)
    assert isinstance(added_items[1], dict)
    assert added_items[1]["description"] == "Milk"
    assert "RECEIPT_CORRECTION_HOLD_RESOLVED" in audit_types
    assert "RECEIPT_CORRECTED" in audit_types
    assert len(corrected_manual_lines) == 2
    assert corrected_manual_lines[0].is_excluded is True
    assert corrected_manual_lines[1].raw_ocr_item is None
    assert generated_store_item is not None
    assert generated_store_item.store_product_id.startswith("MANUAL:")
    assert generated_store_item.identifier_source == "MANUAL"


def _receipt(transaction_number: str) -> Any:
    return normalize_receipt(
        {
            "receipt": {
                "store": "Synthetic Market",
                "date": "2026-09-30",
                "time": "14:05:06",
                "transaction_number": transaction_number,
                "total": "1.00",
            },
            "items": [{"description": "Milk", "line_total": "1.00"}],
        }
    )
