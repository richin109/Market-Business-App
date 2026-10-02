from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

ROOT = Path(__file__).parents[1]


def test_postgres_migrations_round_trip_receipt_json_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.environ.get("MBS_TEST_DATABASE_URL")
    if not database_url:
        pytest.fail("Run docker compose run --rm test, or set MBS_TEST_DATABASE_URL")

    base_url = make_url(database_url)
    if base_url.get_backend_name() != "postgresql":
        pytest.fail("MBS_TEST_DATABASE_URL must use PostgreSQL")

    schema_name = f"migration_test_{uuid4().hex}"
    admin_engine = create_engine(base_url)
    migration_engine = None
    with admin_engine.begin() as connection:
        connection.execute(CreateSchema(schema_name))

    try:
        query = dict(base_url.query)
        query["options"] = f"-csearch_path={schema_name}"
        isolated_url = base_url.set(query=query)
        monkeypatch.setenv("DATABASE_URL", isolated_url.render_as_string(hide_password=False))
        migration_engine = create_engine(isolated_url)
        config = Config(str(ROOT / "alembic.ini"))

        command.upgrade(config, "0008_receipt_upload_outbox")
        upload_pk = str(uuid4())
        receipt_pk = str(uuid4())
        source_sha256 = uuid4().hex * 2
        receipt_document = {
            "receipt_id": "Synthetic Market|2026-09-30|14:05:06|PG-001",
            "store": "Synthetic Market",
            "items": [{"description": "Milk", "line_total": "1.00"}],
        }
        raw_document = {
            "receipt": {"store": "Synthetic Market", "transaction_number": "PG-001"},
            "items": [{"description": "Milk", "line_total": "1.00"}],
        }
        raw_item = {"description": "Milk", "line_total": "1.00", "source_line": 1}

        with migration_engine.begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO tbl_receipt_uploads
                        (upload_pk, source_sha256, file_key, media_type, size_bytes,
                         processing_status)
                        VALUES (:upload_pk, :source_sha256, :file_key, :media_type,
                            :size_bytes, :status)"""
                ),
                {
                    "upload_pk": upload_pk,
                    "source_sha256": source_sha256,
                    "file_key": f"receipts/{source_sha256}.png",
                    "media_type": "image/png",
                    "size_bytes": 8,
                    "status": "SUCCEEDED",
                },
            )
            connection.execute(
                text(
                    """INSERT INTO tbl_receipts
                    (receipt_pk, receipt_id, store, receipt_date, receipt_time,
                     transaction_number, total, upload_pk, raw_ocr_document, receipt_document)
                    VALUES (:receipt_pk, :receipt_id, :store, :receipt_date, :receipt_time,
                            :transaction_number, :total, :upload_pk,
                            CAST(:raw_document AS JSON), CAST(:receipt_document AS JSON))"""
                ),
                {
                    "receipt_pk": receipt_pk,
                    "receipt_id": receipt_document["receipt_id"],
                    "store": "Synthetic Market",
                    "receipt_date": "2026-09-30",
                    "receipt_time": "14:05:06",
                    "transaction_number": "PG-001",
                    "total": "1.00",
                    "upload_pk": upload_pk,
                    "raw_document": json.dumps(raw_document),
                    "receipt_document": json.dumps(receipt_document),
                },
            )
            connection.execute(
                text(
                    """INSERT INTO tbl_receipt_items
                    (receipt_pk, description, line_total, category,
                     business_disposition, raw_ocr_item)
                    VALUES (:receipt_pk, :description, :line_total, :category, :disposition,
                            CAST(:raw_item AS JSON))"""
                ),
                {
                    "receipt_pk": receipt_pk,
                    "description": "Milk",
                    "line_total": "1.00",
                    "category": "Dairy",
                    "disposition": "UNCLASSIFIED",
                    "raw_item": json.dumps(raw_item),
                },
            )

        command.upgrade(config, "0012_settings_catalog")

        inspector = inspect(migration_engine)
        columns = {
            table: {column["name"]: column["type"] for column in inspector.get_columns(table)}
            for table in ("tbl_receipts", "tbl_receipt_items")
        }
        assert isinstance(columns["tbl_receipts"]["raw_ocr_document"], JSONB)
        assert isinstance(columns["tbl_receipts"]["receipt_document"], JSONB)
        assert isinstance(columns["tbl_receipt_items"]["raw_ocr_item"], JSONB)
        auth_session_indexes = {
            index["name"] for index in inspect(migration_engine).get_indexes("tbl_auth_sessions")
        }
        assert "ix_tbl_auth_sessions_user_id" in auth_session_indexes
        with migration_engine.begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO tbl_category_rules (category, keyword, priority)
                    VALUES ('Test Category', 'sequence-check', 100)"""
                )
            )
        with migration_engine.connect() as connection:
            persisted = (
                connection.execute(
                    text(
                        """SELECT r.raw_ocr_document, r.receipt_document, i.raw_ocr_item
                    FROM tbl_receipts AS r
                    JOIN tbl_receipt_items AS i ON i.receipt_pk = r.receipt_pk
                    WHERE r.receipt_pk = :receipt_pk"""
                    ),
                    {"receipt_pk": receipt_pk},
                )
                .mappings()
                .one()
            )
        assert persisted["raw_ocr_document"] == raw_document
        assert persisted["receipt_document"] == receipt_document
        assert persisted["raw_ocr_item"] == raw_item

        with migration_engine.begin() as connection:
            connection.execute(text("DELETE FROM tbl_receipt_items"))
            connection.execute(text("DELETE FROM tbl_receipts"))

        command.upgrade(config, "head")

        identity_inspector = inspect(migration_engine)
        assert {"tbl_items", "tbl_store_items"} <= set(identity_inspector.get_table_names())
        assert {
            "tbl_store_item_mappings",
            "tbl_store_admin_events",
            "tbl_item_mapping_events",
            "tbl_receipt_routing_records",
            "tbl_receipt_expense_drafts",
            "tbl_receipt_sources",
            "tbl_media_assets",
            "tbl_media_asset_links",
        } <= set(identity_inspector.get_table_names())
        media_asset_indexes = {
            index["name"]: index for index in identity_inspector.get_indexes("tbl_media_assets")
        }
        assert media_asset_indexes["uq_tbl_media_assets_perceptual_hash"]["unique"] is True
        media_link_indexes = {
            index["name"]: index
            for index in identity_inspector.get_indexes("tbl_media_asset_links")
        }
        assert media_link_indexes["uq_tbl_media_asset_links_active_primary"]["unique"] is True
        assert media_link_indexes["uq_tbl_media_asset_links_candidate_key"]["unique"] is True
        receipt_item_columns = {
            column["name"] for column in identity_inspector.get_columns("tbl_receipt_items")
        }
        assert {
            "store_item_id",
            "item_id",
            "source_id",
            "source_page",
            "source_line_number",
            "package_count",
            "pack_size",
            "pack_unit",
            "is_excluded",
            "exclusion_reason",
        } <= receipt_item_columns
        assert "source_type" in {
            column["name"] for column in identity_inspector.get_columns("tbl_receipts")
        }
        store_item_constraints = {
            constraint["name"]
            for constraint in identity_inspector.get_unique_constraints("tbl_store_items")
        }
        assert "uq_tbl_store_items_store_product" in store_item_constraints
        receipt_item_foreign_keys = identity_inspector.get_foreign_keys("tbl_receipt_items")
        assert any(
            foreign_key["constrained_columns"] == ["store_item_id"]
            and foreign_key["referred_table"] == "tbl_store_items"
            for foreign_key in receipt_item_foreign_keys
        )
        assert not any(
            foreign_key["constrained_columns"] == ["store_item_id", "item_id"]
            for foreign_key in receipt_item_foreign_keys
        )
        mapping_unique_constraints = {
            constraint["name"]
            for constraint in identity_inspector.get_unique_constraints("tbl_store_item_mappings")
        }
        assert "uq_tbl_store_item_mappings_effective_from" in mapping_unique_constraints
        receipt_item_check_names = {
            constraint["name"]
            for constraint in identity_inspector.get_check_constraints("tbl_receipt_items")
        }
        assert "ck_tbl_receipt_items_disposition_subtype" in receipt_item_check_names
        assert "ck_tbl_receipt_items_exclusion_reason" in receipt_item_check_names
        assert "disposition_subtype" in {
            column["name"]
            for column in identity_inspector.get_columns("tbl_receipt_line_approvals")
        }
        assert "approval_version" in {
            column["name"]
            for column in identity_inspector.get_columns("tbl_receipt_line_approvals")
        }
        source_column_types = {
            column["name"]: column["type"]
            for column in identity_inspector.get_columns("tbl_receipt_sources")
        }
        assert "confirmed_repeated_line_indexes" in source_column_types
        assert isinstance(source_column_types["raw_ocr_document"], JSONB)
        assert isinstance(source_column_types["extracted_document"], JSONB)
        store_item_columns = {
            column["name"] for column in identity_inspector.get_columns("tbl_store_items")
        }
        assert {"remembered_pack_size", "remembered_pack_unit"} <= store_item_columns
        store_item_check_names = {
            constraint["name"]
            for constraint in identity_inspector.get_check_constraints("tbl_store_items")
        }
        assert "ck_tbl_store_items_remembered_package" in store_item_check_names
        identity_checks = {
            constraint["name"]
            for constraint in identity_inspector.get_check_constraints("tbl_store_items")
        }
        assert "ck_tbl_store_items_identifier_provenance" in identity_checks

        with migration_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO tbl_store_resolution_holds "
                    "(upload_pk, reason, raw_ocr_document) "
                    "VALUES (:upload_pk, 'synthetic unresolved store', CAST(:document AS JSONB))"
                ),
                {"upload_pk": upload_pk, "document": json.dumps(raw_document)},
            )
        command.downgrade(config, "0025_media_asset_candidate_keys")
        command.upgrade(config, "head")
        with migration_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT raw_ocr_document FROM tbl_store_resolution_holds"))
                == raw_document
            )
        hold_type = next(
            column["type"]
            for column in inspect(migration_engine).get_columns("tbl_store_resolution_holds")
            if column["name"] == "raw_ocr_document"
        )
        assert isinstance(hold_type, JSONB)

        command.downgrade(config, "base")
        remaining_tables = set(inspect(migration_engine).get_table_names())
        assert (
            not {
                "tbl_receipt_uploads",
                "tbl_receipts",
                "tbl_receipt_items",
            }
            & remaining_tables
        )
    finally:
        if migration_engine is not None:
            migration_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(DropSchema(schema_name, cascade=True))
        admin_engine.dispose()
