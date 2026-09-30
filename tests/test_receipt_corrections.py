from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from mbs.auth import Role, create_user
from mbs.models import ReceiptCorrectionHold
from mbs.receipts.corrections import CorrectionStatus, review_receipt
from mbs.receipts.ocr import normalize_receipt
from mbs.receipts.persistence import persist_extracted_receipt


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


def test_correction_updates_canonical_rows_but_preserves_raw_ocr(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "correction.db")
    with Session(engine) as session:
        reviewer = create_user(session, "manager", "password", Role.MANAGER)
        receipt = persist_extracted_receipt(session, _receipt("TC-100"))
        raw = receipt.raw_ocr_document
        session.commit()

        result = review_receipt(
            session,
            receipt.receipt_pk,
            reviewer.id,
            item_updates={0: {"description": "Whole Milk", "category": "Dairy"}},
        )
        session.commit()

        assert result.status is CorrectionStatus.UPDATED
        assert receipt.raw_ocr_document == raw
        document = receipt.receipt_document
        assert isinstance(document["items"], list)
        assert document["items"][0]["description"] == "Whole Milk"
        assert receipt.reviewed_by == reviewer.id


def test_receipt_id_collision_creates_hold_without_rekeying_receipt(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "collision.db")
    with Session(engine) as session:
        reviewer = create_user(session, "manager", "password", Role.MANAGER)
        first = persist_extracted_receipt(session, _receipt("TC-101"))
        second = persist_extracted_receipt(session, _receipt("TC-102"))
        first_receipt_id = first.receipt_id
        second_receipt_id = second.receipt_id
        session.commit()

        result = review_receipt(
            session,
            second.receipt_pk,
            reviewer.id,
            header_updates={"transaction_number": "TC-101"},
        )
        session.commit()
        holds = session.scalars(select(ReceiptCorrectionHold)).all()

    assert result.status is CorrectionStatus.HELD_FOR_ADMIN
    assert result.hold is not None
    assert second_receipt_id != first_receipt_id
    assert len(holds) == 1


def _engine(path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{path}")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, "head")
    return engine
