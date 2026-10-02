from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from mbs.auth import Role, create_user
from mbs.models import (
    AuditLog,
    Receipt,
    ReceiptCorrection,
    ReceiptCorrectionHold,
    ReceiptItem,
    ReceiptSource,
    ReceiptUpload,
    StoreItem,
)
from mbs.receipts.approval import approve_receipt_item
from mbs.receipts.corrections import CorrectionStatus, review_receipt
from mbs.receipts.ocr import BusinessDisposition, normalize_receipt
from mbs.receipts.persistence import persist_extracted_receipt
from mbs.receipts.units import normalize_unit_alias
from tests.database import postgres_test_url


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
        reviewer = create_user(session, "manager", "synthetic password", Role.MANAGER)
        second_reviewer = create_user(session, "manager-two", "synthetic password", Role.MANAGER)
        receipt = persist_extracted_receipt(session, _receipt("TC-100"))
        raw = receipt.raw_ocr_document
        session.commit()

        result = review_receipt(
            session,
            receipt.receipt_pk,
            reviewer.id,
            reason="Correct receipt line description",
            source_event_id="correction:milk-description:v1",
            item_updates={0: {"description": "Whole Milk", "category": "Dairy"}},
        )
        session.commit()

        assert result.status is CorrectionStatus.UPDATED
        assert receipt.raw_ocr_document == raw
        document = receipt.receipt_document
        assert isinstance(document["items"], list)
        assert document["items"][0]["description"] == "Whole Milk"
        assert receipt.reviewed_by == reviewer.id
        assert receipt.receipt_document_version == 2
        correction = session.scalar(select(ReceiptCorrection))
        assert correction is not None
        assert correction.reason == "Correct receipt line description"
        assert correction.before_document["items"][0]["description"] == "Milk"
        assert correction.after_document["items"][0]["description"] == "Whole Milk"
        assert (
            session.scalar(select(AuditLog).where(AuditLog.event_type == "RECEIPT_CORRECTED"))
            is not None
        )
        second_result = review_receipt(
            session,
            receipt.receipt_pk,
            second_reviewer.id,
            reason="Correct payment method",
            source_event_id="correction:payment-method:v1",
            header_updates={"payment_method": "CASH"},
        )
        session.commit()
        assert second_result.status is CorrectionStatus.UPDATED
        assert receipt.receipt_document_version == 3
        corrections = session.scalars(
            select(ReceiptCorrection).order_by(ReceiptCorrection.id)
        ).all()
        assert len(corrections) == 2
        assert corrections[0].actor_id == reviewer.id
        assert corrections[1].actor_id == second_reviewer.id
        second_before_items = cast(list[dict[str, object]], corrections[1].before_document["items"])
        assert second_before_items[0]["description"] == "Whole Milk"
        replay = review_receipt(
            session,
            receipt.receipt_pk,
            reviewer.id,
            reason="Correct receipt line description",
            source_event_id="correction:milk-description:v1",
            item_updates={0: {"description": "Whole Milk", "category": "Dairy"}},
        )
        session.commit()
        assert replay.idempotent is True
        assert receipt.receipt_document_version == 3
        corrected_items = cast(list[dict[str, object]], receipt.receipt_document["items"])
        assert corrected_items[0]["description"] == "Whole Milk"
        with pytest.raises(ValueError, match="source event ID is already used"):
            review_receipt(
                session,
                receipt.receipt_pk,
                reviewer.id,
                reason="Different correction request",
                source_event_id="correction:milk-description:v1",
                item_updates={0: {"description": "Other Milk"}},
            )


def test_correction_cannot_mutate_a_receipt_after_line_approval(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "approved-correction.db")
    with Session(engine) as session:
        reviewer = create_user(session, "manager", "synthetic password", Role.MANAGER)
        receipt = persist_extracted_receipt(session, _receipt("TC-150"))
        session.commit()
        item_id = session.scalar(
            select(ReceiptItem.id).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
        )
        assert item_id is not None
        approve_receipt_item(
            session,
            item_id,
            reviewer.id,
            BusinessDisposition.PERSONAL_NON_BUSINESS,
        )
        session.commit()

        with pytest.raises(ValueError, match="linked reversal or replacement"):
            review_receipt(
                session,
                receipt.receipt_pk,
                reviewer.id,
                reason="Attempted post-approval correction",
                source_event_id="correction:approved-receipt:v1",
                item_updates={0: {"description": "Changed after approval"}},
            )
        assert receipt.receipt_document_version == 1
        unchanged_items = cast(list[dict[str, object]], receipt.receipt_document["items"])
        assert unchanged_items[0]["description"] == "Milk"


def test_numeric_item_correction_keeps_decimal_rows_and_canonical_snapshot_aligned(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path / "numeric-correction.db")
    with Session(engine) as session:
        reviewer = create_user(session, "manager", "synthetic password", Role.MANAGER)
        receipt = persist_extracted_receipt(session, _receipt("TC-160"))
        session.commit()

        review_receipt(
            session,
            receipt.receipt_pk,
            reviewer.id,
            reason="Capture reviewed package composition and price",
            source_event_id="correction:numeric-fields:v1",
            item_updates={
                0: {
                    "package_count": "2.5000",
                    "pack_size": "1",
                    "pack_unit": "pt",
                    "unit_price": "0.40",
                }
            },
        )
        session.commit()

        line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
        )
        assert line is not None
        assert line.quantity is None
        assert line.weight_lb is None
        assert line.package_count == Decimal("2.5000")
        assert line.pack_size == Decimal("1.0000")
        assert line.pack_unit == "PINT"
        assert line.unit_price == Decimal("0.40")
        assert line.line_total == Decimal("1.00")
        snapshot_items = cast(list[dict[str, object]], receipt.receipt_document["items"])
        assert snapshot_items[0]["quantity"] is None
        assert snapshot_items[0]["package_count"] == "2.5000"
        assert snapshot_items[0]["pack_size"] == "1"
        assert snapshot_items[0]["pack_unit"] == "PINT"
        assert snapshot_items[0]["unit_price"] == "0.40"
        assert receipt.receipt_document["total_mismatch"] is False


@pytest.mark.parametrize(
    ("package_count", "pack_size", "unit_price", "expected_total"),
    [
        ("3", "1", "4.99", "14.97"),
        ("1", "3", "4.99", "4.99"),
    ],
)
def test_package_count_and_pack_size_remain_distinct(
    tmp_path: Path,
    package_count: str,
    pack_size: str,
    unit_price: str,
    expected_total: str,
) -> None:
    engine = _engine(tmp_path / f"package-values-{package_count}-{pack_size}.db")
    with Session(engine) as session:
        reviewer = create_user(session, "manager", "manager password", Role.MANAGER)
        receipt = persist_extracted_receipt(session, _receipt("TC-PACK-VALUES"))
        result = review_receipt(
            session,
            receipt.receipt_pk,
            reviewer.id,
            reason="Confirm receipt package quantities",
            source_event_id=f"correction:package-values:{package_count}:{pack_size}",
            header_updates={"subtotal": expected_total, "total": expected_total},
            item_updates={
                0: {
                    "description": "Strawberries",
                    "package_count": package_count,
                    "pack_size": pack_size,
                    "pack_unit": "pt",
                    "unit_price": unit_price,
                }
            },
        )
        session.commit()
        line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
        )
        assert result.status is CorrectionStatus.UPDATED
        assert line is not None
        assert line.package_count == Decimal(package_count)
        assert line.pack_size == Decimal(pack_size)
        assert line.pack_unit == "PINT"
        assert line.line_total == Decimal(expected_total)
        assert line.quantity is None and line.weight_lb is None
        assert receipt.receipt_document["total_mismatch"] is False


def test_correction_excludes_and_adds_lines_without_rewriting_ocr_evidence(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path / "line-occurrence-correction.db")
    with Session(engine) as session:
        reviewer = create_user(session, "manager", "synthetic password", Role.MANAGER)
        receipt = persist_extracted_receipt(session, _receipt("TC-170"))
        original_raw_document = receipt.raw_ocr_document.copy()
        original_raw_items = cast(list[dict[str, object]], original_raw_document["items"])
        original_line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
        )
        assert original_line is not None
        original_line_id = original_line.id
        upload = ReceiptUpload(
            source_sha256="a" * 64,
            file_key="receipts/source.pdf",
            media_type="application/pdf",
            size_bytes=100,
            uploaded_by=reviewer.id,
            processing_status="SUCCEEDED",
        )
        session.add(upload)
        session.flush()
        source = ReceiptSource(
            receipt_pk=receipt.receipt_pk,
            upload_pk=upload.upload_pk,
            source_sha256=upload.source_sha256,
            association_kind="PRIMARY",
            raw_ocr_document={"items": []},
            extracted_document={"items": []},
        )
        session.add(source)
        session.flush()
        source_id = source.id
        session.commit()

        result = review_receipt(
            session,
            receipt.receipt_pk,
            reviewer.id,
            reason="Exclude the misread line and add the visible purchase",
            source_event_id="correction:line-occurrences:v1",
            header_updates={"subtotal": "0.50", "total": "0.50"},
            item_additions=[
                {
                    "description": "Second Milk",
                    "category": "Dairy",
                    "package_count": "1",
                    "pack_size": "1",
                    "pack_unit": "each",
                    "unit_price": "0.50",
                    "source_id": source_id,
                    "source_page": 1,
                    "source_line_number": 2,
                }
            ],
            item_exclusions=[original_line_id],
        )
        session.commit()

        retry = review_receipt(
            session,
            receipt.receipt_pk,
            reviewer.id,
            reason="Exclude the misread line and add the visible purchase",
            source_event_id="correction:line-occurrences:v1",
            header_updates={"subtotal": "0.50", "total": "0.50"},
            item_additions=[
                {
                    "description": "Second Milk",
                    "category": "Dairy",
                    "package_count": "1",
                    "pack_size": "1",
                    "pack_unit": "each",
                    "unit_price": "0.50",
                    "source_id": source_id,
                    "source_page": 1,
                    "source_line_number": 2,
                }
            ],
            item_exclusions=[original_line_id],
        )
        session.commit()
        lines = session.scalars(
            select(ReceiptItem)
            .where(ReceiptItem.receipt_pk == receipt.receipt_pk)
            .order_by(ReceiptItem.id)
        ).all()
        correction = session.scalar(select(ReceiptCorrection))

        assert result.status is CorrectionStatus.UPDATED
        assert retry.idempotent is True
        assert len(lines) == 2
        assert lines[0].raw_ocr_item == original_raw_items[0]
        assert lines[0].is_excluded is True
        assert lines[0].exclusion_reason == "Exclude the misread line and add the visible purchase"
        assert lines[1].description == "Second Milk"
        assert lines[1].raw_ocr_item is None
        assert lines[1].line_total == Decimal("0.50")
        assert lines[1].source_id == source_id
        assert lines[1].source_page == 1 and lines[1].source_line_number == 2
        assert receipt.raw_ocr_document == original_raw_document
        assert receipt.receipt_document["total_mismatch"] is False
        assert correction is not None
        corrected_items = cast(list[dict[str, object]], correction.after_document["items"])
        assert corrected_items[1]["description"] == "Second Milk"
        with pytest.raises(ValueError, match="Excluded receipt lines cannot be approved"):
            approve_receipt_item(
                session,
                lines[0].id,
                reviewer.id,
                BusinessDisposition.PERSONAL_NON_BUSINESS,
            )


def test_repeated_product_addition_requires_explicit_occurrence_confirmation(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path / "repeated-occurrence-correction.db")
    with Session(engine) as session:
        reviewer = create_user(session, "manager", "manager password", Role.MANAGER)
        receipt = persist_extracted_receipt(session, _receipt("TC-171"))
        original_line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
        )
        assert original_line is not None
        upload = ReceiptUpload(
            source_sha256="b" * 64,
            file_key="receipts/repeated-source.pdf",
            media_type="application/pdf",
            size_bytes=100,
            uploaded_by=reviewer.id,
            processing_status="SUCCEEDED",
        )
        session.add(upload)
        session.flush()
        source = ReceiptSource(
            receipt_pk=receipt.receipt_pk,
            upload_pk=upload.upload_pk,
            source_sha256=upload.source_sha256,
            association_kind="PRIMARY",
            raw_ocr_document={"items": []},
            extracted_document={"items": []},
        )
        session.add(source)
        session.flush()
        original_line.source_id = source.id
        original_line.source_page = 1
        original_line.source_line_number = 1
        addition = {
            "description": "Milk",
            "category": "Dairy",
            "package_count": "1",
            "pack_size": "1",
            "pack_unit": "each",
            "unit_price": "1.00",
            "source_id": source.id,
            "source_page": 1,
            "source_line_number": 2,
        }
        session.commit()

        with pytest.raises(ValueError, match="explicitly confirm this repeated product"):
            review_receipt(
                session,
                receipt.receipt_pk,
                reviewer.id,
                reason="Confirm a second purchase occurrence",
                source_event_id="correction:repeat-confirmation:v1",
                header_updates={"subtotal": "2.00", "total": "2.00"},
                item_additions=[addition],
            )

        addition["confirm_repeated_occurrence"] = True
        result = review_receipt(
            session,
            receipt.receipt_pk,
            reviewer.id,
            reason="Confirm a second purchase occurrence",
            source_event_id="correction:repeat-confirmation:v1",
            header_updates={"subtotal": "2.00", "total": "2.00"},
            item_additions=[addition],
        )
        session.commit()
        lines = session.scalars(
            select(ReceiptItem)
            .where(ReceiptItem.receipt_pk == receipt.receipt_pk)
            .order_by(ReceiptItem.id)
        ).all()

        assert result.status is CorrectionStatus.UPDATED
        assert len(lines) == 2
        assert lines[0].source_line_number == 1
        assert lines[1].source_line_number == 2
        assert receipt.receipt_document["total_mismatch"] is False

        bulk_first = {**addition, "source_line_number": 3}
        bulk_second = {
            **addition,
            "source_line_number": 4,
            "confirm_repeated_occurrence": False,
        }
        with pytest.raises(ValueError, match="explicitly confirm this repeated product"):
            review_receipt(
                session,
                receipt.receipt_pk,
                reviewer.id,
                reason="Add two separate repeated purchases",
                source_event_id="correction:repeat-confirmation-batch:v1",
                header_updates={"subtotal": "4.00", "total": "4.00"},
                item_additions=[bulk_first, bulk_second],
            )

        bulk_second["confirm_repeated_occurrence"] = True
        bulk_result = review_receipt(
            session,
            receipt.receipt_pk,
            reviewer.id,
            reason="Add two separate repeated purchases",
            source_event_id="correction:repeat-confirmation-batch:v1",
            header_updates={"subtotal": "4.00", "total": "4.00"},
            item_additions=[bulk_first, bulk_second],
        )
        session.commit()
        assert bulk_result.status is CorrectionStatus.UPDATED
        assert (
            len(
                session.scalars(
                    select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
                ).all()
            )
            == 4
        )
        with pytest.raises(ValueError, match="source line occurrence is already present"):
            review_receipt(
                session,
                receipt.receipt_pk,
                reviewer.id,
                reason="Retry an existing source row as another line",
                source_event_id="correction:duplicate-source-row:v1",
                header_updates={"subtotal": "5.00", "total": "5.00"},
                item_additions=[{**bulk_first, "confirm_repeated_occurrence": True}],
            )


def test_pack_unit_alias_is_exact_case_insensitive_and_rejects_typo() -> None:
    assert normalize_unit_alias(" PT ") == "PINT"
    assert normalize_unit_alias("Pints") == "PINT"
    assert normalize_unit_alias("points") is None


def test_confirmed_pack_size_is_remembered_without_autofilling_future_ocr_lines(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path / "remembered-package-default.db")
    with Session(engine) as session:
        reviewer = create_user(session, "manager", "manager password", Role.MANAGER)

        def receipt_document(transaction_number: str) -> dict[str, Any]:
            return {
                "receipt": {
                    "store": "Synthetic Market",
                    "date": "2026-09-30",
                    "time": "14:05:06",
                    "transaction_number": transaction_number,
                    "subtotal": "2.00",
                    "tax": "0.00",
                    "total": "2.00",
                },
                "items": [
                    {
                        "description": "Strawberries",
                        "store_product_id": "STRAWBERRIES-1",
                        "line_total": "2.00",
                        "unit_price": "2.00",
                    }
                ],
            }

        first_receipt = persist_extracted_receipt(
            session, normalize_receipt(receipt_document("TC-PACK-1"))
        )
        first_line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == first_receipt.receipt_pk)
        )
        assert first_line is not None and first_line.store_item_id is not None
        raw_ocr_item = dict(first_line.raw_ocr_item or {})
        review_receipt(
            session,
            first_receipt.receipt_pk,
            reviewer.id,
            reason="Confirm strawberries are sold in one pint packages",
            source_event_id="correction:remember-strawberries-pack:v1",
            item_updates={0: {"package_count": "1", "pack_size": "1", "pack_unit": "pint"}},
            remember_package_default_indexes=[0],
        )
        second_receipt = persist_extracted_receipt(
            session, normalize_receipt(receipt_document("TC-PACK-2"))
        )
        second_line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == second_receipt.receipt_pk)
        )
        store_item = session.get(StoreItem, first_line.store_item_id)
        audit = session.scalar(
            select(AuditLog).where(
                AuditLog.event_type == "STORE_ITEM_PACKAGE_DEFAULT_UPDATED",
                AuditLog.entity_id == first_line.store_item_id,
            )
        )

        assert store_item is not None
        assert store_item.remembered_pack_size == Decimal("1")
        assert store_item.remembered_pack_unit == "PINT"
        assert second_line is not None
        assert second_line.pack_size is None and second_line.pack_unit is None
        assert first_line.raw_ocr_item == raw_ocr_item
        assert audit is not None
        session.commit()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        postgres_test_url(tmp_path / "remembered-package-default.db"),
    )
    with pytest.raises(RuntimeError, match="store-item package defaults are recorded"):
        command.downgrade(config, "0022_receipt_repeat_line_confirmation")


def test_receipt_id_collision_creates_hold_without_rekeying_receipt(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "collision.db")
    with Session(engine) as session:
        reviewer = create_user(session, "manager", "synthetic password", Role.MANAGER)
        first = persist_extracted_receipt(session, _receipt("TC-101"))
        second = persist_extracted_receipt(session, _receipt("TC-102"))
        first_receipt_id = first.receipt_id
        second_receipt_id = second.receipt_id
        first_pk = first.receipt_pk
        second_pk = second.receipt_pk
        session.commit()

        result = review_receipt(
            session,
            second.receipt_pk,
            reviewer.id,
            reason="Receipt transaction number was misread",
            source_event_id="correction:collision:v1",
            header_updates={"transaction_number": "TC-101"},
        )
        session.commit()
        replay = review_receipt(
            session,
            second_pk,
            reviewer.id,
            reason="Receipt transaction number was misread",
            source_event_id="correction:collision:v1",
            header_updates={"transaction_number": "TC-101"},
        )
        session.commit()
        holds = session.scalars(select(ReceiptCorrectionHold)).all()
        persisted = {
            receipt.receipt_pk: receipt.receipt_id
            for receipt in session.scalars(select(Receipt)).all()
        }

    assert result.status is CorrectionStatus.HELD_FOR_ADMIN
    assert result.hold is not None
    assert result.hold.reason == "Receipt transaction number was misread"
    assert result.hold.source_event_id == "correction:collision:v1"
    assert replay.idempotent is True
    assert replay.hold is not None and replay.hold.id == result.hold.id
    assert second_receipt_id != first_receipt_id
    assert len(holds) == 1
    assert persisted[first_pk] == first_receipt_id
    assert persisted[second_pk] == second_receipt_id


def test_receipt_id_unique_constraint_race_creates_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _engine(tmp_path / "collision-race.db")
    with Session(engine) as session:
        reviewer = create_user(session, "manager", "synthetic password", Role.MANAGER)
        persist_extracted_receipt(session, _receipt("TC-201"))
        second = persist_extracted_receipt(session, _receipt("TC-202"))
        second_pk = second.receipt_pk
        session.commit()

        original_scalar = session.scalar
        collision_checks = 0

        def miss_first_collision_check(statement: Any, *args: Any, **kwargs: Any) -> Any:
            nonlocal collision_checks
            if "WHERE tbl_receipts.receipt_id =" in str(statement):
                collision_checks += 1
                if collision_checks == 1:
                    return None
            return original_scalar(statement, *args, **kwargs)

        monkeypatch.setattr(session, "scalar", miss_first_collision_check)
        result = review_receipt(
            session,
            second_pk,
            reviewer.id,
            reason="Exercise the uniqueness fallback",
            source_event_id="correction:collision-race:v1",
            header_updates={"transaction_number": "TC-201"},
        )
        session.commit()
        persisted = session.get(Receipt, second_pk)
        holds = session.scalars(select(ReceiptCorrectionHold)).all()

    assert collision_checks == 2
    assert result.status is CorrectionStatus.HELD_FOR_ADMIN
    assert persisted is not None and persisted.receipt_id.endswith("|TC-202")
    assert len(holds) == 1 and holds[0].status == "PENDING"


def _engine(path: Path) -> Engine:
    engine = create_engine(postgres_test_url(path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(path).replace("%", "%%"))
    command.upgrade(config, "head")
    return engine
