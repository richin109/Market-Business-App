from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mbs.auth import Role, create_user
from mbs.items import (
    assign_manual_store_product_identifier,
    assign_reviewed_store_product_identifier,
    confirm_store_item_mapping,
    displayed_item_name,
    register_store_item,
    set_item_common_name,
    set_store_item_common_name,
)
from mbs.models import AuditLog, Item, ReceiptItem, StoreItem
from mbs.receipts.approval import approve_receipt_item
from mbs.receipts.ocr import BusinessDisposition, normalize_receipt
from mbs.receipts.persistence import persist_extracted_receipt
from tests.database import postgres_test_url


def _database(path: Path, revision: str = "head") -> tuple[Any, sessionmaker[Session], Config]:
    engine = create_engine(postgres_test_url(path))

    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(path).replace("%", "%%"))
    command.upgrade(config, revision)
    return engine, sessionmaker(engine, expire_on_commit=False), config


def _receipt(transaction_number: str, store: str, items: list[dict[str, Any]]) -> Any:
    return normalize_receipt(
        {
            "receipt": {
                "store": store,
                "date": "2026-09-30",
                "time": "14:05:06",
                "transaction_number": transaction_number,
                "total": "1.00",
            },
            "items": items,
        }
    )


def _line(description: str, store_product_id: str | None) -> dict[str, Any]:
    item: dict[str, Any] = {"description": description, "line_total": "1.00"}
    if store_product_id is not None:
        item["store_product_id"] = store_product_id
    return item


def test_store_product_id_defines_identity_and_description_is_only_display_data(
    tmp_path: Path,
) -> None:
    engine, session_factory, _ = _database(tmp_path / "item-identity.db")
    try:
        with session_factory.begin() as session:
            first_receipt = persist_extracted_receipt(
                session,
                _receipt("IT-101", "Market One", [_line("GV STRWBRY 1LB", "445566")]),
            )
            second_receipt = persist_extracted_receipt(
                session,
                _receipt("IT-102", "Market One", [_line("Great Value Strawberry", "445566")]),
            )
            third_receipt = persist_extracted_receipt(
                session,
                _receipt("IT-103", "Market One", [_line("Great Value Strawberry", "778899")]),
            )
            other_store_receipt = persist_extracted_receipt(
                session,
                _receipt("IT-104", "Market Two", [_line("Great Value Strawberry", "445566")]),
            )
            session.flush()
            lines = {
                receipt.receipt_id: session.scalar(
                    select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
                )
                for receipt in (
                    first_receipt,
                    second_receipt,
                    third_receipt,
                    other_store_receipt,
                )
            }
            assert all(line is not None for line in lines.values())
            first = lines[first_receipt.receipt_id]
            changed = lines[second_receipt.receipt_id]
            separate_sku = lines[third_receipt.receipt_id]
            other_store = lines[other_store_receipt.receipt_id]

            assert first is not None and changed is not None
            assert separate_sku is not None and other_store is not None
            assert first.store_item_id == changed.store_item_id
            assert first.item_id == changed.item_id
            assert separate_sku.store_item_id != first.store_item_id
            assert other_store.store_item_id != first.store_item_id
            assert other_store.item_id != first.item_id
            assert first.description == "GV STRWBRY 1LB"
            latest_store_item = session.get(StoreItem, first.store_item_id)
            assert latest_store_item is not None
            assert latest_store_item.latest_description == "Great Value Strawberry"
            assert first_receipt.receipt_document is not None
            canonical_items = first_receipt.receipt_document["items"]
            assert isinstance(canonical_items, list)
            assert isinstance(canonical_items[0], dict)
            assert canonical_items[0]["store_product_id"] == "445566"
            assert first.raw_ocr_item is not None
            assert first.raw_ocr_item["description"] == "GV STRWBRY 1LB"
            assert session.scalar(select(func.count(StoreItem.store_item_id))) == 3
    finally:
        engine.dispose()


def test_explicitly_confirmed_store_items_can_share_one_canonical_item(
    tmp_path: Path,
) -> None:
    engine, session_factory, _ = _database(tmp_path / "shared-item-identity.db")
    try:
        with session_factory.begin() as session:
            first_receipt = persist_extracted_receipt(
                session,
                _receipt("IT-151", "Market One", []),
            )
            second_receipt = persist_extracted_receipt(
                session,
                _receipt("IT-152", "Market Two", []),
            )
            canonical_item = Item(common_name="Strawberries", is_store_observed=False)
            session.add(canonical_item)
            session.flush()

            first = register_store_item(
                session,
                first_receipt.store_id,
                "MARKET-ONE-445566",
                "GV STRWBRY 1LB",
                confirmed_item_id=canonical_item.item_id,
                actor_id=19,
            )
            second = register_store_item(
                session,
                second_receipt.store_id,
                "MARKET-TWO-SB-1",
                "Strawberries 1 lb",
                confirmed_item_id=canonical_item.item_id,
                actor_id=19,
            )

            assert first.store_item_id != second.store_item_id
            assert first.item_id == second.item_id == canonical_item.item_id
            assert first.mapping_confirmed and second.mapping_confirmed
            observed_item = session.get(Item, canonical_item.item_id)
            assert observed_item is not None and observed_item.is_store_observed is True
            assert (
                session.scalar(
                    select(func.count(StoreItem.store_item_id)).where(
                        StoreItem.item_id == canonical_item.item_id
                    )
                )
                == 2
            )
            assert (
                session.scalar(
                    select(func.count(AuditLog.id)).where(
                        AuditLog.event_type == "STORE_ITEM_MAPPING_CONFIRMED",
                        AuditLog.actor == "19",
                    )
                )
                == 2
            )
    finally:
        engine.dispose()


def test_unidentified_lines_cannot_post_and_manual_identity_is_audited(
    tmp_path: Path,
) -> None:
    engine, session_factory, _ = _database(tmp_path / "manual-item-identity.db")
    try:
        with session_factory.begin() as session:
            reviewer = create_user(session, "manual-reviewer", "synthetic password", Role.MANAGER)
            receipt = persist_extracted_receipt(
                session,
                _receipt("IT-201", "Market One", [_line("Milk", "  ")]),
            )
            line = session.scalar(
                select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
            )
            assert line is not None
            assert line.store_item_id is None and line.item_id is None
            assert line.raw_ocr_item == {
                "description": "Milk",
                "line_total": "1.00",
                "store_product_id": "  ",
            }
            assert receipt.receipt_document is not None
            canonical_items = receipt.receipt_document["items"]
            assert isinstance(canonical_items, list)
            assert isinstance(canonical_items[0], dict)
            assert canonical_items[0]["store_product_id"] is None
            assert line.raw_ocr_item is not None
            with pytest.raises(ValueError, match="store product identifier"):
                approve_receipt_item(
                    session,
                    line.id,
                    reviewer.id,
                    BusinessDisposition.RECIPE_INGREDIENT,
                )

            with pytest.raises(ValueError, match="manually entered receipt"):
                assign_manual_store_product_identifier(session, line.id, reviewer.id)
            receipt.source_type = "MANUAL"
            store_item = assign_manual_store_product_identifier(session, line.id, reviewer.id)
            assert store_item.store_product_id.startswith("MANUAL:")
            assert store_item.identifier_source == "MANUAL"
            assert line.raw_ocr_item["store_product_id"] == "  "
            assert (
                session.scalar(
                    select(AuditLog).where(
                        AuditLog.event_type == "MANUAL_STORE_PRODUCT_ID_ASSIGNED",
                        AuditLog.entity_id == str(line.id),
                    )
                )
                is not None
            )
            assert store_item.mapping_confirmed is True
            line.package_count = Decimal("1")
            line.pack_size = Decimal("1")
            line.pack_unit = "EACH"
            approved = approve_receipt_item(
                session,
                line.id,
                reviewer.id,
                BusinessDisposition.RECIPE_INGREDIENT,
            )
            assert approved.approval.posting_status == "ROUTED"
    finally:
        engine.dispose()


def test_reviewer_supplies_missing_ocr_identifier_without_rewriting_evidence(
    tmp_path: Path,
) -> None:
    engine, session_factory, _ = _database(tmp_path / "reviewed-identifier.db")
    try:
        with session_factory.begin() as session:
            reviewer = create_user(session, "sku-reviewer", "synthetic password", Role.MANAGER)
            receipt = persist_extracted_receipt(
                session,
                _receipt("IT-251", "Market One", [_line("Milk", None)]),
            )
            line = session.scalar(
                select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
            )
            assert line is not None and line.raw_ocr_item is not None
            line.package_count = Decimal("1")
            line.pack_size = Decimal("1")
            line.pack_unit = "EACH"
            before_raw_item = dict(line.raw_ocr_item)
            store_item = assign_reviewed_store_product_identifier(
                session,
                line.id,
                "MILK-REVIEWED-1",
                reviewer.id,
            )

            assert store_item.store_product_id == "MILK-REVIEWED-1"
            assert store_item.identifier_source == "MERCHANT"
            assert store_item.mapping_confirmed is False
            assert line.raw_ocr_item == before_raw_item
            assert "store_product_id" not in line.raw_ocr_item
            with pytest.raises(ValueError, match="mapping must be confirmed"):
                approve_receipt_item(
                    session,
                    line.id,
                    reviewer.id,
                    BusinessDisposition.RECIPE_INGREDIENT,
                )

            confirm_store_item_mapping(
                session,
                store_item.store_item_id,
                store_item.item_id,
                reviewer.id,
            )
            approve_receipt_item(
                session,
                line.id,
                reviewer.id,
                BusinessDisposition.RECIPE_INGREDIENT,
            )
            assert (
                session.scalar(
                    select(AuditLog).where(
                        AuditLog.event_type == "RECEIPT_LINE_STORE_PRODUCT_ID_REVIEWED",
                        AuditLog.entity_id == str(line.id),
                    )
                )
                is not None
            )
    finally:
        engine.dispose()


def test_mapping_protects_last_observed_item_and_common_names_do_not_rekey(
    tmp_path: Path,
) -> None:
    engine, session_factory, _ = _database(tmp_path / "item-mapping-invariants.db")
    try:
        with session_factory.begin() as session:
            first = persist_extracted_receipt(
                session,
                _receipt("IT-301", "Market One", [_line("Milk", "MILK-1")]),
            )
            second = persist_extracted_receipt(
                session,
                _receipt("IT-302", "Market Two", [_line("Whole Milk", "MILK-2")]),
            )
            first_line = session.scalar(
                select(ReceiptItem).where(ReceiptItem.receipt_pk == first.receipt_pk)
            )
            second_line = session.scalar(
                select(ReceiptItem).where(ReceiptItem.receipt_pk == second.receipt_pk)
            )
            assert first_line is not None and second_line is not None
            assert first_line.item_id is not None and second_line.item_id is not None
            assert first_line.store_item_id is not None
            with pytest.raises(ValueError, match="last store item"):
                confirm_store_item_mapping(
                    session,
                    first_line.store_item_id,
                    second_line.item_id,
                    19,
                )

            store_item = session.get(StoreItem, first_line.store_item_id)
            item = session.get(Item, first_line.item_id)
            assert store_item is not None and item is not None
            initial_identity = (store_item.store_item_id, store_item.item_id)
            assert displayed_item_name(session, first_line) == "Milk"
            set_item_common_name(session, item.item_id, "  Dairy Milk  ", 19)
            assert displayed_item_name(session, first_line) == "Dairy Milk"
            set_store_item_common_name(session, store_item.store_item_id, "Organic Milk", 19)
            assert displayed_item_name(session, first_line) == "Organic Milk"
            assert (store_item.store_item_id, store_item.item_id) == initial_identity
            assert (
                session.scalar(
                    select(AuditLog).where(
                        AuditLog.event_type == "ITEM_COMMON_NAME_UPDATED",
                        AuditLog.entity_id == item.item_id,
                    )
                )
                is not None
            )
    finally:
        engine.dispose()


def test_receipt_line_can_retain_historical_item_id_after_remap(tmp_path: Path) -> None:
    engine, session_factory, _ = _database(tmp_path / "item-identity-fk.db")
    try:
        with session_factory.begin() as session:
            first = persist_extracted_receipt(
                session,
                _receipt("IT-401", "Market One", [_line("Milk", "MILK-1")]),
            )
            second = persist_extracted_receipt(
                session,
                _receipt("IT-402", "Market One", [_line("Flour", "FLOUR-1")]),
            )
            first_line = session.scalar(
                select(ReceiptItem).where(ReceiptItem.receipt_pk == first.receipt_pk)
            )
            second_line = session.scalar(
                select(ReceiptItem).where(ReceiptItem.receipt_pk == second.receipt_pk)
            )
            assert first_line is not None and second_line is not None
            assert first_line.item_id != second_line.item_id
            historical_item_id = first_line.item_id
            session.add(
                ReceiptItem(
                    receipt_pk=first.receipt_pk,
                    description="Historical mapping snapshot",
                    line_total=1,
                    category="Other",
                    business_disposition="UNCLASSIFIED",
                    store_item_id=first_line.store_item_id,
                    item_id=second_line.item_id,
                )
            )
            session.flush()
            historical_line = session.scalar(
                select(ReceiptItem).where(ReceiptItem.description == "Historical mapping snapshot")
            )
            assert historical_line is not None
            assert historical_line.item_id == second_line.item_id
            assert historical_item_id == first_line.item_id
    finally:
        engine.dispose()


def test_item_identity_migration_refuses_existing_lines_and_round_trips_empty_schema(
    tmp_path: Path,
) -> None:
    engine, session_factory, config = _database(
        tmp_path / "item-identity-migration.db", "0013_store_registry"
    )
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO tbl_stores (store_id, display_name) "
                    "VALUES ('legacy-store', 'Legacy Market')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO tbl_store_aliases (normalized_key, store_id) "
                    "VALUES ('legacy market', 'legacy-store')"
                )
            )
            connection.execute(
                text(
                    """INSERT INTO tbl_receipts
                    (receipt_pk, receipt_id, store_id, store_alias_key, store,
                     receipt_date, receipt_time, transaction_number, total,
                     raw_ocr_document, receipt_document)
                    VALUES ('legacy-receipt', 'Legacy|2026-09-30|14:05:06|IT-501',
                            'legacy-store', 'legacy market', 'Legacy Market',
                            '2026-09-30', '14:05:06', 'IT-501', 1, '{}', '{}')"""
                )
            )
            connection.execute(
                text(
                    """INSERT INTO tbl_receipt_items
                    (receipt_pk, description, line_total, category, business_disposition)
                    VALUES ('legacy-receipt', 'Milk', 1, 'Dairy', 'UNCLASSIFIED')"""
                )
            )

        with pytest.raises(RuntimeError, match="tbl_receipt_items contains rows"):
            command.upgrade(config, "head")

        assert "tbl_items" not in inspect(engine).get_table_names()
        assert "store_item_id" not in {
            column["name"] for column in inspect(engine).get_columns("tbl_receipt_items")
        }
    finally:
        engine.dispose()

    empty_engine, _, empty_config = _database(
        tmp_path / "item-identity-empty.db", "0013_store_registry"
    )
    try:
        command.upgrade(empty_config, "head")
        assert "tbl_items" in inspect(empty_engine).get_table_names()
        assert "source_type" in {
            column["name"] for column in inspect(empty_engine).get_columns("tbl_receipts")
        }
        assert {"store_item_id", "item_id"} <= {
            column["name"] for column in inspect(empty_engine).get_columns("tbl_receipt_items")
        }
        command.downgrade(empty_config, "0013_store_registry")
        assert "tbl_items" not in inspect(empty_engine).get_table_names()
        assert "source_type" not in {
            column["name"] for column in inspect(empty_engine).get_columns("tbl_receipts")
        }
        assert "store_item_id" not in {
            column["name"] for column in inspect(empty_engine).get_columns("tbl_receipt_items")
        }
    finally:
        empty_engine.dispose()


def test_manual_identifier_cannot_be_claimed_as_merchant_evidence(tmp_path: Path) -> None:
    engine, session_factory, _ = _database(tmp_path / "manual-prefix.db")
    try:
        with session_factory.begin() as session:
            receipt = persist_extracted_receipt(
                session,
                _receipt("IT-601", "Market One", []),
            )
            with pytest.raises(ValueError, match="reserved MANUAL: prefix"):
                register_store_item(
                    session,
                    receipt.store_id,
                    "MANUAL:printed-text",
                    "Product",
                )
            assert session.scalar(select(func.count(StoreItem.store_item_id))) == 0
            session.add(Item(item_id="synthetic-item", is_store_observed=False))
            session.flush()
            with pytest.raises(IntegrityError, match="ck_tbl_store_items_identifier_provenance"):
                with session.begin_nested():
                    session.execute(
                        text(
                            """INSERT INTO tbl_store_items
                            (store_item_id, store_id, store_product_id, item_id,
                             latest_description, identifier_source, mapping_confirmed)
                            VALUES ('bad-id', :store_id, 'MANUAL:printed-text', 'synthetic-item',
                                    'Product', 'MERCHANT', FALSE)"""
                        ),
                        {"store_id": receipt.store_id},
                    )
    finally:
        engine.dispose()
