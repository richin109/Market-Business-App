from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from mbs.auth import Role, create_user
from mbs.models import ReceiptItem, ReceiptLineApproval
from mbs.receipts.approval import PostingKind, PostingStatus, approve_receipt_item
from mbs.receipts.ocr import BusinessDisposition, normalize_receipt
from mbs.receipts.persistence import persist_extracted_receipt


def _engine(path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{path}")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, "head")
    return engine


def _receipt() -> Any:
    return normalize_receipt(
        {
            "receipt": {
                "store": "Synthetic Market",
                "date": "2026-09-30",
                "time": "14:05:06",
                "transaction_number": "TC-999",
                "total": "4.00",
            },
            "items": [
                {"description": "Personal item", "line_total": "1.00"},
                {"description": "Milk", "line_total": "1.00"},
                {"description": "Flour", "line_total": "1.00"},
                {"description": "Equipment", "line_total": "1.00"},
            ],
        }
    )


def test_all_four_dispositions_route_once_and_retries_are_idempotent(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "approval.db")
    with Session(engine) as session:
        reviewer = create_user(session, "manager", "password", Role.MANAGER)
        receipt = persist_extracted_receipt(session, _receipt())
        session.commit()
        ids = [
            item.id
            for item in session.scalars(
                select(ReceiptItem)
                .where(ReceiptItem.receipt_pk == receipt.receipt_pk)
                .order_by(ReceiptItem.id)
            )
        ]
        dispositions = (
            BusinessDisposition.PERSONAL_NON_BUSINESS,
            BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
            BusinessDisposition.RECIPE_INGREDIENT,
            BusinessDisposition.CAPITAL_ASSET_EQUIPMENT,
        )
        results = [
            approve_receipt_item(session, item_id, reviewer.id, disposition)
            for item_id, disposition in zip(ids, dispositions, strict=True)
        ]
        retry = approve_receipt_item(session, ids[0], reviewer.id, dispositions[0])
        session.commit()
        approvals = session.scalars(select(ReceiptLineApproval)).all()

    assert [result.approval.posting_kind for result in results] == [
        PostingKind.NO_POST,
        PostingKind.ORDINARY_EXPENSE,
        PostingKind.INGREDIENT_PURCHASE,
        PostingKind.CAPITAL_ASSET,
    ]
    assert results[0].approval.posting_status == PostingStatus.NO_POST
    assert retry.idempotent is True
    assert len(approvals) == 4


def test_approval_cannot_change_an_existing_disposition(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "approval-change.db")
    with Session(engine) as session:
        reviewer = create_user(session, "manager", "password", Role.MANAGER)
        receipt = persist_extracted_receipt(session, _receipt())
        session.commit()
        first_item_id = session.scalar(
            select(ReceiptItem.id).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
        )
        assert first_item_id is not None
        approve_receipt_item(
            session,
            first_item_id,
            reviewer.id,
            BusinessDisposition.PERSONAL_NON_BUSINESS,
        )
        session.commit()
        with pytest.raises(ValueError, match="another disposition"):
            approve_receipt_item(
                session,
                first_item_id,
                reviewer.id,
                BusinessDisposition.RECIPE_INGREDIENT,
            )
