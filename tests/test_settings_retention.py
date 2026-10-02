from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from mbs.auth import Role, create_session, create_user
from mbs.db import get_session
from mbs.main import app
from mbs.models import AuditLog, Receipt
from mbs.receipts.ocr import normalize_receipt
from mbs.receipts.persistence import persist_extracted_receipt
from mbs.settings import read_retention_settings
from tests.database import postgres_test_url

URL = "/api/v1/settings/retention"


def test_retention_settings_are_admin_only_audited_and_never_purge(tmp_path: Path) -> None:
    path = tmp_path / "retention.db"
    engine = create_engine(postgres_test_url(path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(path).replace("%", "%%"))
    command.upgrade(config, "head")
    with Session(engine) as session:
        admin = create_user(session, "retention-admin", "synthetic password", Role.ADMIN)
        manager = create_user(session, "retention-manager", "synthetic password", Role.MANAGER)
        admin_token, admin_csrf = create_session(session, admin)
        manager_token, manager_csrf = create_session(session, manager)
        admin_id = admin.id
        persist_extracted_receipt(
            session,
            normalize_receipt(
                {
                    "receipt": {
                        "store": "Synthetic Retention Market",
                        "date": "2020-01-01",
                        "time": "10:00:00",
                        "transaction_number": "RET-1",
                        "total": "1.00",
                    },
                    "items": [{"description": "Old item", "line_total": "1.00"}],
                }
            ),
        )
        session.commit()
        assert read_retention_settings(session) == {
            "receipt_source_retention_days": None,
            "receipt_raw_retention_days": None,
        }

    def override_session() -> Iterator[Session]:
        with Session(engine) as active_session:
            yield active_session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        admin_headers = {"Cookie": f"mbs_session={admin_token}", "X-CSRF-Token": admin_csrf}
        manager_headers = {"Cookie": f"mbs_session={manager_token}", "X-CSRF-Token": manager_csrf}
        body = {"receipt_source_retention_days": 365, "reason": "Owner policy"}

        assert client.get(URL, headers=manager_headers).status_code == 403
        assert client.put(URL, json=body, headers=manager_headers).status_code == 403
        assert client.put(URL, json=body).status_code == 401
        assert client.get(URL, headers=admin_headers).json() == {
            "receipt_source_retention_days": None,
            "receipt_raw_retention_days": None,
        }

        updated = client.put(URL, json=body, headers=admin_headers)
        assert updated.status_code == 200
        assert updated.json() == {
            "receipt_source_retention_days": 365,
            "receipt_raw_retention_days": None,
        }
        # No-op repeat and an omitted key do not add audit rows or change the other value.
        assert client.put(URL, json=body, headers=admin_headers).status_code == 200

        for invalid in (0, -5, 40000):
            rejected = client.put(
                URL,
                json={"receipt_raw_retention_days": invalid, "reason": "bad"},
                headers=admin_headers,
            )
            assert rejected.status_code == 422
        assert (
            client.put(
                URL, json={"receipt_raw_retention_days": 30, "reason": "  "}, headers=admin_headers
            ).status_code
            == 400
        )

        cleared = client.put(
            URL,
            json={"receipt_source_retention_days": None, "reason": "Policy withdrawn"},
            headers=admin_headers,
        )
        assert cleared.json() == {
            "receipt_source_retention_days": None,
            "receipt_raw_retention_days": None,
        }

        with Session(engine) as session:
            audits = session.scalars(
                select(AuditLog)
                .where(AuditLog.event_type == "RETENTION_SETTING_UPDATED")
                .order_by(AuditLog.id)
            ).all()
            assert [row.details for row in audits] == [
                "old=None; new=365; reason=Owner policy",
                "old=365; new=None; reason=Policy withdrawn",
            ]
            assert {row.entity_id for row in audits} == {"receipt_source_retention_days"}
            assert audits[0].actor == str(admin_id)
            # Retention values are recorded only; the old receipt is never purged (D-15).
            assert session.scalar(select(func.count(Receipt.receipt_pk))) == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
