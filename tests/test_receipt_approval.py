from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbs.auth import Role, create_session, create_user
from mbs.items import confirm_store_item_mapping
from mbs.models import (
    AuditLog,
    ReceiptExpenseDraft,
    ReceiptItem,
    ReceiptLineApproval,
    ReceiptRoutingRecord,
    StoreItem,
)
from mbs.receipts.approval import (
    DispositionSubtype,
    PostingKind,
    PostingStatus,
    approve_receipt_item,
    reclassify_expense_routing,
)
from mbs.receipts.corrections import review_receipt
from mbs.receipts.ocr import BusinessDisposition, normalize_receipt
from mbs.receipts.persistence import persist_extracted_receipt
from tests.database import postgres_test_url


def _engine(path: Path, revision: str = "head") -> Engine:
    engine = create_engine(postgres_test_url(path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(path).replace("%", "%%"))
    command.upgrade(config, revision)
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
                {"description": "Milk", "line_total": "1.00", "store_product_id": "MILK-1"},
                {"description": "Flour", "line_total": "1.00", "store_product_id": "FLOUR-1"},
                {
                    "description": "Equipment",
                    "line_total": "1.00",
                    "store_product_id": "EQUIPMENT-1",
                },
            ],
        }
    )


def test_all_four_dispositions_route_once_and_retries_are_idempotent(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "approval.db")
    with Session(engine) as session:
        reviewer = create_user(session, "manager", "synthetic password", Role.MANAGER)
        receipt = persist_extracted_receipt(session, _receipt())
        session.commit()
        items = list(
            session.scalars(
                select(ReceiptItem)
                .where(ReceiptItem.receipt_pk == receipt.receipt_pk)
                .order_by(ReceiptItem.id)
            )
        )
        ids = [item.id for item in items]
        for item in items[1:]:
            assert item.store_item_id is not None and item.item_id is not None
            confirm_store_item_mapping(session, item.store_item_id, item.item_id, reviewer.id)
        items[2].package_count = Decimal("1")
        items[2].pack_size = Decimal("1")
        items[2].pack_unit = "EACH"
        session.commit()
        dispositions = (
            BusinessDisposition.PERSONAL_NON_BUSINESS,
            BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
            BusinessDisposition.RECIPE_INGREDIENT,
            BusinessDisposition.CAPITAL_ASSET_EQUIPMENT,
        )
        subtypes = (
            DispositionSubtype.NONE,
            DispositionSubtype.DIRECT_EXPENSE,
            DispositionSubtype.NONE,
            DispositionSubtype.NONE,
        )
        results = [
            approve_receipt_item(
                session, item_id, reviewer.id, disposition, disposition_subtype=subtype
            )
            for item_id, disposition, subtype in zip(ids, dispositions, subtypes, strict=True)
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


def test_receipt_total_mismatch_blocks_line_approval(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "approval-mismatch.db")
    with Session(engine) as session:
        reviewer = create_user(session, "manager", "synthetic password", Role.MANAGER)
        receipt = persist_extracted_receipt(session, _receipt())
        session.commit()
        item_id = session.scalar(
            select(ReceiptItem.id)
            .where(ReceiptItem.receipt_pk == receipt.receipt_pk)
            .order_by(ReceiptItem.id)
        )
        assert item_id is not None
        receipt.subtotal = Decimal("3.00")
        receipt.receipt_document = {**receipt.receipt_document, "total_mismatch": False}
        session.commit()

        with pytest.raises(ValueError, match="totals must reconcile"):
            approve_receipt_item(
                session,
                item_id,
                reviewer.id,
                BusinessDisposition.PERSONAL_NON_BUSINESS,
            )

        assert session.scalar(select(ReceiptLineApproval)) is None


def test_recipe_ingredient_approval_requires_reviewed_package_fields(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "approval-package.db")
    with Session(engine) as session:
        reviewer = create_user(session, "manager", "synthetic password", Role.MANAGER)
        receipt = persist_extracted_receipt(session, _receipt())
        session.commit()
        line = session.scalar(
            select(ReceiptItem)
            .where(ReceiptItem.receipt_pk == receipt.receipt_pk)
            .order_by(ReceiptItem.id)
            .offset(1)
        )
        assert line is not None and line.store_item_id is not None and line.item_id is not None
        confirm_store_item_mapping(session, line.store_item_id, line.item_id, reviewer.id)
        session.commit()

        with pytest.raises(ValueError, match="package count, size, and unit"):
            approve_receipt_item(
                session,
                line.id,
                reviewer.id,
                BusinessDisposition.RECIPE_INGREDIENT,
            )

        assert session.scalar(select(ReceiptLineApproval)) is None


def test_approval_cannot_change_an_existing_disposition(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "approval-change.db")
    with Session(engine) as session:
        reviewer = create_user(session, "manager", "synthetic password", Role.MANAGER)
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


def test_approval_source_event_collision_is_rejected_cleanly(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "approval-event-collision.db")
    with Session(engine) as session:
        reviewer = create_user(session, "manager", "synthetic password", Role.MANAGER)
        receipt = persist_extracted_receipt(session, _receipt())
        session.commit()
        item_ids = list(
            session.scalars(
                select(ReceiptItem.id)
                .where(ReceiptItem.receipt_pk == receipt.receipt_pk)
                .order_by(ReceiptItem.id)
            )
        )
        approve_receipt_item(
            session,
            item_ids[0],
            reviewer.id,
            BusinessDisposition.PERSONAL_NON_BUSINESS,
            source_event_id="shared-approval-event",
        )
        session.commit()

        with pytest.raises(ValueError, match="source event ID is already used"):
            approve_receipt_item(
                session,
                item_ids[1],
                reviewer.id,
                BusinessDisposition.PERSONAL_NON_BUSINESS,
                source_event_id="shared-approval-event",
            )


def test_rm_028(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path / "approval-subtypes.db")
    with Session(engine) as session:
        reviewer = create_user(session, "subtype-manager", "synthetic password", Role.MANAGER)
        receipt = normalize_receipt(
            {
                "receipt": {
                    "store": "Synthetic Market",
                    "date": "2026-09-30",
                    "time": "14:05:06",
                    "transaction_number": "TC-SUBTYPE-1",
                    "total": "5.00",
                },
                "items": [
                    {"description": "Cups", "line_total": "1.00", "store_product_id": "CUP-1"},
                    {"description": "Ice", "line_total": "1.00", "store_product_id": "ICE-1"},
                    {"description": "Water", "line_total": "1.00", "store_product_id": "WATER-1"},
                    {
                        "description": "Strawberries",
                        "line_total": "1.00",
                        "store_product_id": "BERRY-1",
                    },
                    {
                        "description": "Personal",
                        "line_total": "1.00",
                        "store_product_id": "PERSONAL-1",
                    },
                ],
            }
        )
        persisted = persist_extracted_receipt(session, receipt)
        session.commit()
        lines = list(
            session.scalars(
                select(ReceiptItem)
                .where(ReceiptItem.receipt_pk == persisted.receipt_pk)
                .order_by(ReceiptItem.id)
            )
        )
        for line in lines:
            assert line.store_item_id is not None and line.item_id is not None
            item = session.get(StoreItem, line.store_item_id)
            assert item is not None
            confirm_store_item_mapping(session, item.store_item_id, item.item_id, reviewer.id)
        lines[0].package_count = Decimal("1")
        lines[0].pack_size = Decimal("1")
        lines[0].pack_unit = "EACH"
        lines[3].package_count = Decimal("1")
        lines[3].pack_size = Decimal("1")
        lines[3].pack_unit = "EACH"
        session.commit()

        with pytest.raises(ValueError, match="requires a disposition subtype"):
            approve_receipt_item(
                session,
                lines[0].id,
                reviewer.id,
                BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
            )
        with pytest.raises(ValueError, match="Only Ordinary Business Purchase"):
            approve_receipt_item(
                session,
                lines[3].id,
                reviewer.id,
                BusinessDisposition.RECIPE_INGREDIENT,
                disposition_subtype=DispositionSubtype.STOCKED_SUPPLY,
            )
        with pytest.raises(ValueError, match="requires subtype NONE"):
            review_receipt(
                session,
                persisted.receipt_pk,
                reviewer.id,
                "Reject invalid subtype pairing",
                "rm028-invalid-correction",
                item_updates={
                    3: {
                        "business_disposition": BusinessDisposition.RECIPE_INGREDIENT.value,
                        "disposition_subtype": DispositionSubtype.STOCKED_SUPPLY.value,
                    }
                },
            )
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.execute(
                    update(ReceiptItem)
                    .where(ReceiptItem.id == lines[3].id)
                    .values(disposition_subtype=DispositionSubtype.STOCKED_SUPPLY.value)
                )

        [
            approve_receipt_item(
                session,
                lines[0].id,
                reviewer.id,
                BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
                "rm028-cups",
                DispositionSubtype.STOCKED_SUPPLY,
            ),
            approve_receipt_item(
                session,
                lines[1].id,
                reviewer.id,
                BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
                "rm028-ice",
                DispositionSubtype.DIRECT_EXPENSE,
            ),
            approve_receipt_item(
                session,
                lines[2].id,
                reviewer.id,
                BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
                "rm028-water",
                DispositionSubtype.DIRECT_SELL_RESTOCK,
            ),
            approve_receipt_item(
                session,
                lines[3].id,
                reviewer.id,
                BusinessDisposition.RECIPE_INGREDIENT,
                "rm028-ingredient",
            ),
            approve_receipt_item(
                session,
                lines[4].id,
                reviewer.id,
                BusinessDisposition.PERSONAL_NON_BUSINESS,
                "rm028-personal",
            ),
        ]
        retry = approve_receipt_item(
            session,
            lines[1].id,
            reviewer.id,
            BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
            "rm028-ice",
            DispositionSubtype.DIRECT_EXPENSE,
        )
        with pytest.raises(ValueError, match="another disposition"):
            approve_receipt_item(
                session,
                lines[1].id,
                reviewer.id,
                BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
                "rm028-ice-restock",
                DispositionSubtype.DIRECT_SELL_RESTOCK,
            )
        session.commit()

        routes = session.scalars(select(ReceiptRoutingRecord)).all()
        expense_drafts = session.scalars(select(ReceiptExpenseDraft)).all()
        approval_rows = session.scalars(
            select(ReceiptLineApproval).order_by(ReceiptLineApproval.receipt_item_id)
        ).all()
        posting_kinds = [approval.posting_kind for approval in approval_rows]
        personal_posting_status = approval_rows[-1].posting_status
        stored_lines = session.scalars(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == persisted.receipt_pk)
        ).all()
        remembered_defaults = [
            (store_item.last_disposition, store_item.last_disposition_subtype)
            for store_item in session.scalars(select(StoreItem)).all()
        ]

    assert posting_kinds == [
        PostingKind.STOCKED_SUPPLY,
        PostingKind.DIRECT_EXPENSE,
        PostingKind.DIRECT_SELL_RESTOCK,
        PostingKind.INGREDIENT_PURCHASE,
        PostingKind.NO_POST,
    ]
    assert all(route.status == "PENDING" for route in routes)
    assert {route.destination_kind for route in routes} == {
        "STOCKED_SUPPLY",
        "DIRECT_EXPENSE",
        "DIRECT_SELL_RESTOCK",
        "INGREDIENT_PURCHASE",
    }
    assert len(routes) == 4
    assert len(expense_drafts) == 1
    assert expense_drafts[0].description == "Ice"
    assert expense_drafts[0].amount == 1
    assert retry.idempotent is True
    assert len({line.disposition_subtype for line in stored_lines}) == 4
    assert set(remembered_defaults) == {
        (BusinessDisposition.ORDINARY_BUSINESS_PURCHASE.value, "STOCKED_SUPPLY"),
        (BusinessDisposition.ORDINARY_BUSINESS_PURCHASE.value, "DIRECT_EXPENSE"),
        (BusinessDisposition.ORDINARY_BUSINESS_PURCHASE.value, "DIRECT_SELL_RESTOCK"),
        (BusinessDisposition.RECIPE_INGREDIENT.value, "NONE"),
        (BusinessDisposition.PERSONAL_NON_BUSINESS.value, "NONE"),
    }
    assert personal_posting_status == PostingStatus.NO_POST.value
    engine.dispose()


def test_expense_reroute_holds_both_destinations_and_retries_idempotently(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path / "expense-reroute-hold.db")
    with Session(engine) as session:
        reviewer = create_user(session, "reroute-manager", "synthetic password", Role.MANAGER)
        receipt = persist_extracted_receipt(session, _receipt())
        session.commit()
        line = session.scalar(
            select(ReceiptItem).where(
                ReceiptItem.receipt_pk == receipt.receipt_pk,
                ReceiptItem.description == "Milk",
            )
        )
        assert line is not None and line.store_item_id is not None and line.item_id is not None
        store_item = session.get(StoreItem, line.store_item_id)
        assert store_item is not None
        confirm_store_item_mapping(session, store_item.store_item_id, line.item_id, reviewer.id)
        approve_receipt_item(
            session,
            line.id,
            reviewer.id,
            BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
            "reroute-expense-initial",
            DispositionSubtype.DIRECT_EXPENSE,
        )
        session.commit()
        expense_route = session.scalar(
            select(ReceiptRoutingRecord).where(
                ReceiptRoutingRecord.receipt_item_id == line.id,
                ReceiptRoutingRecord.destination_kind == PostingKind.DIRECT_EXPENSE.value,
            )
        )
        assert expense_route is not None
        expense_route.status = "POSTED"
        expense_draft = session.scalar(
            select(ReceiptExpenseDraft).where(
                ReceiptExpenseDraft.routing_record_id == expense_route.id
            )
        )
        assert expense_draft is not None
        expense_draft.status = "POSTED"
        session.commit()

        rerouted = reclassify_expense_routing(
            session,
            line.id,
            reviewer.id,
            BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
            DispositionSubtype.DIRECT_SELL_RESTOCK,
            "Expense classification was confirmed as resale stock",
            "reroute-expense-to-stock",
        )
        replay = reclassify_expense_routing(
            session,
            line.id,
            reviewer.id,
            BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
            DispositionSubtype.DIRECT_SELL_RESTOCK,
            "Expense classification was confirmed as resale stock",
            "reroute-expense-to-stock",
        )
        with pytest.raises(ValueError, match="already used"):
            reclassify_expense_routing(
                session,
                line.id,
                reviewer.id,
                BusinessDisposition.RECIPE_INGREDIENT,
                DispositionSubtype.NONE,
                "Different target",
                "reroute-expense-to-stock",
            )
        session.commit()

        routes = session.scalars(
            select(ReceiptRoutingRecord)
            .where(ReceiptRoutingRecord.receipt_item_id == line.id)
            .order_by(ReceiptRoutingRecord.id)
        ).all()
        drafts = session.scalars(
            select(ReceiptExpenseDraft).where(ReceiptExpenseDraft.receipt_item_id == line.id)
        ).all()
        approvals = session.scalars(
            select(ReceiptLineApproval)
            .where(ReceiptLineApproval.receipt_item_id == line.id)
            .order_by(ReceiptLineApproval.approval_version)
        ).all()
        correction = session.scalar(
            select(AuditLog).where(
                AuditLog.event_type == "RECEIPT_EXPENSE_REROUTE_HELD",
                AuditLog.entity_id == str(line.id),
            )
        )

    assert rerouted.approval.approval_version == 2
    assert rerouted.approval.posting_status == PostingStatus.HELD
    assert replay.idempotent is True
    assert [approval.approval_version for approval in approvals] == [1, 2]
    assert [route.status for route in routes] == ["HELD", "HELD"]
    assert routes[1].supersedes_routing_record_id == routes[0].id
    assert len(drafts) == 1 and drafts[0].status == "POSTED"
    assert correction is not None
    assert "Expense classification" in str(correction.details)
    assert '"prior_routing_status": "POSTED"' in str(correction.details)
    assert '"prior_expense_draft_status": "POSTED"' in str(correction.details)
    engine.dispose()


def test_approval_version_migration_preserves_existing_routes_as_version_one(
    tmp_path: Path,
) -> None:
    path = tmp_path / "approval-version-migration.db"
    engine = _engine(path)
    with Session(engine) as session:
        reviewer = create_user(
            session, "approval-migration-manager", "synthetic password", Role.MANAGER
        )
        receipt = persist_extracted_receipt(session, _receipt())
        line = session.scalar(
            select(ReceiptItem).where(
                ReceiptItem.receipt_pk == receipt.receipt_pk,
                ReceiptItem.description == "Milk",
            )
        )
        assert line is not None and line.item_id is not None
        store_item = session.get(StoreItem, line.store_item_id)
        assert store_item is not None
        confirm_store_item_mapping(session, store_item.store_item_id, line.item_id, reviewer.id)
        approve_receipt_item(
            session,
            line.id,
            reviewer.id,
            BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
            "legacy-approval",
            DispositionSubtype.DIRECT_EXPENSE,
        )
        route = session.scalar(
            select(ReceiptRoutingRecord).where(ReceiptRoutingRecord.receipt_item_id == line.id)
        )
        assert route is not None
        route.approved_version = 7
        line_id = line.id
        session.commit()
    engine.dispose()

    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(path).replace("%", "%%"))
    command.downgrade(config, "0016_receipt_routing")
    command.upgrade(config, "head")
    engine = create_engine(postgres_test_url(path))
    with Session(engine) as session:
        approval = session.scalar(
            select(ReceiptLineApproval).where(ReceiptLineApproval.receipt_item_id == line_id)
        )
        route = session.scalar(
            select(ReceiptRoutingRecord).where(ReceiptRoutingRecord.receipt_item_id == line_id)
        )
    assert approval is not None and approval.approval_version == 1
    assert route is not None and route.approved_version == 1
    engine.dispose()


def test_receipt_approval_api_requires_manager_csrf_and_returns_route_identity(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path / "approval-api.db")
    with Session(engine) as session:
        manager = create_user(session, "approval-api-manager", "synthetic password", Role.MANAGER)
        viewer = create_user(session, "approval-api-viewer", "synthetic password", Role.VIEWER)
        manager_token, manager_csrf = create_session(session, manager)
        viewer_token, viewer_csrf = create_session(session, viewer)
        receipt = persist_extracted_receipt(session, _receipt())
        session.commit()
        line = session.scalar(
            select(ReceiptItem).where(
                ReceiptItem.receipt_pk == receipt.receipt_pk,
                ReceiptItem.description == "Milk",
            )
        )
        assert line is not None and line.store_item_id is not None and line.item_id is not None
        store_item = session.get(StoreItem, line.store_item_id)
        assert store_item is not None
        confirm_store_item_mapping(
            session, store_item.store_item_id, store_item.item_id, manager.id
        )
        receipt_pk = receipt.receipt_pk
        line_id = line.id
        session.commit()

    from fastapi.testclient import TestClient

    from mbs.db import get_session
    from mbs.main import app

    def override_session() -> Any:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        path = f"/api/v1/receipts/{receipt_pk}/items/{line_id}/approval"
        reroute_path = f"/api/v1/receipts/{receipt_pk}/items/{line_id}/reroute"
        reroute_payload = {
            "disposition": "ORDINARY_BUSINESS_PURCHASE",
            "disposition_subtype": "DIRECT_SELL_RESTOCK",
            "reason": "Receipt was a resale purchase, not an expense",
            "source_event_id": "approval-api-reroute-event",
        }
        payload = {
            "disposition": "ORDINARY_BUSINESS_PURCHASE",
            "disposition_subtype": "DIRECT_EXPENSE",
            "source_event_id": "approval-api-event",
        }
        no_csrf = client.post(
            path,
            json=payload,
            headers={"Cookie": f"mbs_session={manager_token}"},
        )
        viewer_response = client.post(
            path,
            json=payload,
            headers={
                "Cookie": f"mbs_session={viewer_token}",
                "X-CSRF-Token": viewer_csrf,
            },
        )
        no_csrf_reroute = client.post(
            reroute_path,
            json=reroute_payload,
            headers={"Cookie": f"mbs_session={manager_token}"},
        )
        viewer_reroute = client.post(
            reroute_path,
            json=reroute_payload,
            headers={
                "Cookie": f"mbs_session={viewer_token}",
                "X-CSRF-Token": viewer_csrf,
            },
        )
        approved = client.post(
            path,
            json=payload,
            headers={
                "Cookie": f"mbs_session={manager_token}",
                "X-CSRF-Token": manager_csrf,
            },
        )
        rerouted = client.post(
            reroute_path,
            json=reroute_payload,
            headers={
                "Cookie": f"mbs_session={manager_token}",
                "X-CSRF-Token": manager_csrf,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert no_csrf.status_code == 403
    assert viewer_response.status_code == 403
    assert no_csrf_reroute.status_code == 403
    assert viewer_reroute.status_code == 403
    assert approved.status_code == 200
    assert approved.json()["disposition_subtype"] == "DIRECT_EXPENSE"
    assert approved.json()["routing_record_id"] is not None
    assert rerouted.status_code == 200
    assert rerouted.json()["disposition_subtype"] == "DIRECT_SELL_RESTOCK"
    assert rerouted.json()["posting_status"] == "HELD"
    with Session(engine) as session:
        reroute_rows = session.scalars(
            select(ReceiptRoutingRecord).where(ReceiptRoutingRecord.receipt_item_id == line_id)
        ).all()
    assert len(reroute_rows) == 2
    assert {record.status for record in reroute_rows} == {"HELD"}
    engine.dispose()


def test_routing_migration_refuses_existing_unclassified_subtypes(tmp_path: Path) -> None:
    database_path = tmp_path / "routing-migration-guard.db"
    engine = _engine(database_path, "0015_item_mapping_admin")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tbl_stores (store_id, display_name) "
                "VALUES ('legacy-store', 'Legacy store')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO tbl_store_aliases (normalized_key, store_id) "
                "VALUES ('legacy store', 'legacy-store')"
            )
        )
        connection.execute(
            text(
                """INSERT INTO tbl_receipts
                (receipt_pk, receipt_id, store_id, store_alias_key, store,
                 receipt_date, receipt_time, transaction_number, total,
                 raw_ocr_document, receipt_document)
                VALUES ('legacy-receipt', 'Legacy|2026-09-30|14:00:00|MIG-1',
                        'legacy-store', 'legacy store', 'Legacy store',
                        '2026-09-30', '14:00:00', 'MIG-1', 1, '{}', '{}')"""
            )
        )
        connection.execute(
            text(
                """INSERT INTO tbl_receipt_items
                (receipt_pk, description, line_total, category, business_disposition)
                VALUES ('legacy-receipt', 'Unresolved purchase', 1, 'Other',
                        'ORDINARY_BUSINESS_PURCHASE')"""
            )
        )
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(database_path).replace("%", "%%"))

    with pytest.raises(RuntimeError, match="ordinary-business lines exist"):
        command.upgrade(config, "head")

    assert "tbl_receipt_routing_records" not in inspect(engine).get_table_names()
    assert "disposition_subtype" not in {
        column["name"] for column in inspect(engine).get_columns("tbl_receipt_items")
    }
    engine.dispose()


def test_existing_remembered_rule_changes_only_when_the_reviewer_opts_in(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "remembered-rule-update.db")

    def milk_receipt(transaction_number: str) -> Any:
        return normalize_receipt(
            {
                "receipt": {
                    "store": "Synthetic Market",
                    "date": "2026-09-30",
                    "time": "14:05:06",
                    "transaction_number": transaction_number,
                    "total": "1.00",
                },
                "items": [
                    {"description": "Milk", "line_total": "1.00", "store_product_id": "MILK-1"}
                ],
            }
        )

    with Session(engine) as session:
        reviewer = create_user(session, "rule-update-manager", "synthetic password", Role.MANAGER)
        line_ids: list[int] = []
        for number in ("RULE-A", "RULE-B", "RULE-C"):
            persisted = persist_extracted_receipt(session, milk_receipt(number))
            line = session.scalars(
                select(ReceiptItem).where(ReceiptItem.receipt_pk == persisted.receipt_pk)
            ).one()
            line.package_count, line.pack_size, line.pack_unit = (
                Decimal("1"),
                Decimal("1"),
                "EACH",
            )
            line_ids.append(line.id)
        store_item = session.scalars(select(StoreItem)).one()
        confirm_store_item_mapping(
            session, store_item.store_item_id, store_item.item_id, reviewer.id
        )
        session.commit()

        first = approve_receipt_item(
            session,
            line_ids[0],
            reviewer.id,
            BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
            "rule-a",
            DispositionSubtype.STOCKED_SUPPLY,
        )
        kept = approve_receipt_item(
            session, line_ids[1], reviewer.id, BusinessDisposition.PERSONAL_NON_BUSINESS, "rule-b"
        )
        session.commit()
        assert first.remembered_rule_differs is False
        assert kept.remembered_rule_differs is True
        assert store_item.last_disposition == "ORDINARY_BUSINESS_PURCHASE"
        assert store_item.last_disposition_subtype == "STOCKED_SUPPLY"

        updated = approve_receipt_item(
            session,
            line_ids[2],
            reviewer.id,
            BusinessDisposition.PERSONAL_NON_BUSINESS,
            "rule-c",
            update_remembered_rule=True,
        )
        session.commit()
        session.refresh(store_item)
        assert updated.remembered_rule_differs is False
        assert (store_item.last_disposition, store_item.last_disposition_subtype) == (
            "PERSONAL_NON_BUSINESS",
            "NONE",
        )
    engine.dispose()
