from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from mbs.models import Receipt, ReceiptItem, ReceiptUpload
from mbs.receipts.ocr import normalize_receipt
from mbs.receipts.persistence import create_upload, persist_extracted_receipt


def _receipt() -> Any:
    return normalize_receipt(
        {
            "metadata": {
                "provider": "synthetic-local",
                "schema_version": "test-v1",
                "page_count": 1,
            },
            "receipt": {
                "store": "Synthetic Market",
                "date": "2026-09-30",
                "time": "14:05:06",
                "transaction_number": "TC-900",
                "subtotal": "2.00",
                "tax": "0.14",
                "total": "2.14",
            },
            "items": [
                {"description": "Milk", "line_total": "2.14", "quantity": "1"},
            ],
        }
    )


def test_receipt_migration_round_trips_raw_snapshot_and_normalized_items(tmp_path: Path) -> None:
    database_path = tmp_path / "receipts.db"
    engine = create_engine(f"sqlite:///{database_path}")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")
    extracted = _receipt()
    original_raw = extracted.raw_ocr_document

    with Session(engine) as session:
        upload = create_upload(session, "a" * 64, "receipts/aa/file.png", "image/png", 128)
        upload_pk = upload.upload_pk
        receipt = persist_extracted_receipt(session, extracted, upload)
        session.commit()
        receipt_pk = receipt.receipt_pk

    with Session(engine) as session:
        stored = session.get(Receipt, receipt_pk)
        items = session.scalars(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt_pk)
        ).all()
        stored_upload = session.get(ReceiptUpload, upload_pk)

    assert stored is not None
    assert stored.raw_ocr_document == original_raw
    assert stored.receipt_document["receipt_id"] == extracted.receipt_id
    assert stored.total == extracted.total
    assert len(items) == 1
    assert items[0].description == "Milk"
    assert stored_upload is not None
    assert stored_upload.processing_status == "SUCCEEDED"
    assert stored_upload.ocr_attempts == 1


def test_receipt_id_is_unique_in_the_database(tmp_path: Path) -> None:
    database_path = tmp_path / "unique.db"
    engine = create_engine(f"sqlite:///{database_path}")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")
    extracted = _receipt()

    with Session(engine) as session:
        persist_extracted_receipt(session, extracted)
        session.commit()
        try:
            persist_extracted_receipt(session, extracted)
            session.commit()
        except Exception:
            session.rollback()
            duplicate_rejected = True
        else:
            duplicate_rejected = False

    assert duplicate_rejected
