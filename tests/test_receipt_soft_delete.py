from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from mbs.auth import Role, create_session, create_user
from mbs.db import get_session
from mbs.main import app
from mbs.models import AuditLog, Receipt, ReceiptItem
from mbs.receipts.approval import approve_receipt_item
from mbs.receipts.ocr import BusinessDisposition, normalize_receipt
from mbs.receipts.persistence import persist_extracted_receipt
from tests.database import postgres_test_url


def _receipt(transaction_number: str) -> Any:
    return normalize_receipt(
        {
            "receipt": {
                "store": "Synthetic Delete Market",
                "date": "2026-09-30",
                "time": "14:05:06",
                "transaction_number": transaction_number,
                "total": "1.00",
            },
            "items": [{"description": "Personal item", "line_total": "1.00"}],
        }
    )


def test_rm_015_no_hard_delete_or_purge_route_exists() -> None:
    paths = app.openapi()["paths"]
    delete_paths = {
        path for path, methods in paths.items() if "delete" in methods and "receipt" in path
    }
    assert delete_paths == {"/api/v1/receipts/{receipt_pk}"}
    assert not any("purge" in path for path in paths)


def test_rm_015_only_admin_soft_deletes_unapproved_receipts_and_hides_them(
    tmp_path: Path,
) -> None:
    path = tmp_path / "soft-delete.db"
    engine = create_engine(postgres_test_url(path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(path).replace("%", "%%"))
    command.upgrade(config, "head")
    with Session(engine) as session:
        admin = create_user(session, "delete-admin", "synthetic password", Role.ADMIN)
        manager = create_user(session, "delete-manager", "synthetic password", Role.MANAGER)
        admin_token, admin_csrf = create_session(session, admin)
        manager_token, manager_csrf = create_session(session, manager)
        removable = persist_extracted_receipt(session, _receipt("DEL-1"))
        approved = persist_extracted_receipt(session, _receipt("DEL-2"))
        approved_line = session.scalars(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == approved.receipt_pk)
        ).one()
        approve_receipt_item(
            session, approved_line.id, admin.id, BusinessDisposition.PERSONAL_NON_BUSINESS
        )
        session.commit()
        removable_pk, approved_pk = removable.receipt_pk, approved.receipt_pk

    def override_session() -> Iterator[Session]:
        with Session(engine) as active_session:
            yield active_session

    app.dependency_overrides[get_session] = override_session
    admin_headers = {"Cookie": f"mbs_session={admin_token}", "X-CSRF-Token": admin_csrf}
    manager_headers = {"Cookie": f"mbs_session={manager_token}", "X-CSRF-Token": manager_csrf}
    body = {"reason": "Duplicate capture"}
    try:
        client = TestClient(app)
        url = f"/api/v1/receipts/{removable_pk}"
        assert client.request("DELETE", url, json=body).status_code == 401
        assert client.request("DELETE", url, json=body, headers=manager_headers).status_code == 403
        assert (
            client.request(
                "DELETE", url, json=body, headers={"Cookie": f"mbs_session={admin_token}"}
            ).status_code
            == 403
        )
        assert (
            client.request("DELETE", url, json={"reason": ""}, headers=admin_headers).status_code
            == 422
        )
        missing = client.request(
            "DELETE", "/api/v1/receipts/unknown", json=body, headers=admin_headers
        )
        assert missing.status_code == 404
        assert client.get(url, headers=manager_headers).status_code == 200

        deleted = client.request("DELETE", url, json=body, headers=admin_headers)
        assert deleted.status_code == 200 and deleted.json()["idempotent"] is False
        again = client.request("DELETE", url, json=body, headers=admin_headers)
        assert again.status_code == 200 and again.json()["idempotent"] is True
        assert client.get(url, headers=manager_headers).status_code == 404
        assert client.get(f"{url}/review", headers=manager_headers).status_code == 404
        listed = client.get("/api/v1/receipts", headers=manager_headers).json()
        assert [row["receipt_pk"] for row in listed] == [approved_pk]
        stores = client.get("/api/v1/stores", headers=manager_headers).json()
        assert [store["receipt_count"] for store in stores] == [1]

        blocked = client.request(
            "DELETE", f"/api/v1/receipts/{approved_pk}", json=body, headers=admin_headers
        )
        assert blocked.status_code == 409
        assert (
            client.get(f"/api/v1/receipts/{approved_pk}", headers=manager_headers).status_code
            == 200
        )

        with Session(engine) as session:
            stored = session.get(Receipt, removable_pk)
            assert stored is not None and stored.deleted_at is not None
            assert session.scalar(select(func.count(ReceiptItem.id))) == 2
            assert (
                session.scalar(
                    select(func.count(AuditLog.id)).where(
                        AuditLog.event_type == "RECEIPT_SOFT_DELETED"
                    )
                )
                == 1
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
