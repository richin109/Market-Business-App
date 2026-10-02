from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from mbs.auth import Role, create_session, create_user
from mbs.db import get_session
from mbs.main import app
from mbs.models import ReceiptItem
from mbs.receipts.ocr import normalize_receipt
from mbs.receipts.persistence import persist_extracted_receipt
from tests.database import postgres_test_url


def _receipt(store: str, purchase_date: str, transaction_number: str) -> Any:
    return normalize_receipt(
        {
            "receipt": {
                "store": store,
                "date": purchase_date,
                "time": "14:05:06",
                "transaction_number": transaction_number,
                "total": "2.14",
            },
            "items": [{"description": "Milk", "line_total": "2.14", "quantity": "3"}],
        }
    )


def test_receipt_read_apis_use_persisted_rows_and_line_counts(tmp_path: Path) -> None:
    database_path = tmp_path / "read-api.db"
    engine = create_engine(postgres_test_url(database_path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(database_path).replace("%", "%%"))
    command.upgrade(config, "head")

    with Session(engine) as database_session:
        viewer = create_user(database_session, "viewer", "viewer password", Role.VIEWER)
        session_token, _ = create_session(database_session, viewer)
        newest = persist_extracted_receipt(
            database_session, _receipt("New Store", "2026-09-30", "TC-902")
        )
        newest_line = database_session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == newest.receipt_pk)
        )
        assert newest_line is not None
        newest_line.is_excluded = True
        newest_line.exclusion_reason = "Synthetic exclusion for read-model coverage"
        persist_extracted_receipt(database_session, _receipt("Old Store", "2026-09-29", "TC-901"))
        deleted = persist_extracted_receipt(
            database_session, _receipt("Deleted Store", "2026-09-28", "TC-900")
        )
        deleted.deleted_at = datetime.now(UTC)
        database_session.commit()

        def override_session() -> Any:
            yield database_session

        item_count_queries: list[str] = []

        def capture_item_count_query(
            connection: Any,
            cursor: Any,
            statement: str,
            parameters: Any,
            context: Any,
            executemany: bool,
        ) -> None:
            if "FROM TBL_RECEIPT_ITEMS" in statement.upper():
                item_count_queries.append(statement)

        app.dependency_overrides[get_session] = override_session
        try:
            client = TestClient(app)
            headers = {"Cookie": f"mbs_session={session_token}"}
            event.listen(engine, "before_cursor_execute", capture_item_count_query)
            listing = client.get("/api/v1/receipts", headers=headers)
            listing_item_count_query_count = len(item_count_queries)
            canonical_listing = client.get(
                "/api/v1/receipts",
                params={"store_id": newest.store_id},
                headers=headers,
            )
            canonical_item_count_query_count = (
                len(item_count_queries) - listing_item_count_query_count
            )
            event.remove(engine, "before_cursor_execute", capture_item_count_query)
            detail = client.get(f"/api/v1/receipts/{newest.receipt_pk}", headers=headers)
            items = client.get(f"/api/v1/receipts/{newest.receipt_pk}/items", headers=headers)
        finally:
            app.dependency_overrides.clear()

    assert listing.status_code == 200
    rows = listing.json()
    assert [row["store"] for row in rows] == ["New Store", "Old Store"]
    assert [row["store_id"] for row in canonical_listing.json()] == [newest.store_id]
    assert rows[0]["item_count"] == 0
    assert listing_item_count_query_count == 1
    assert canonical_item_count_query_count == 1
    assert detail.status_code == 200
    assert detail.json()["items"][0]["quantity"] == "3.0000"
    assert detail.json()["items"][0]["is_excluded"] is True
    assert items.status_code == 200
    assert len(items.json()) == 1
    assert items.json()[0]["exclusion_reason"] == "Synthetic exclusion for read-model coverage"
