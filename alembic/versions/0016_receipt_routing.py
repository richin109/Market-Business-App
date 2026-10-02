"""Add receipt disposition subtypes and pending routing records.

Revision ID: 0016_receipt_routing
Revises: 0015_item_mapping_admin
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_receipt_routing"
down_revision = "0015_item_mapping_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    ordinary_approvals = connection.scalar(
        sa.text(
            """SELECT COUNT(*) FROM tbl_receipt_items
            WHERE business_disposition = 'ORDINARY_BUSINESS_PURCHASE'"""
        )
    )
    if ordinary_approvals:
        raise RuntimeError(
            "Cannot add required receipt disposition subtypes: ordinary-business lines exist; "
            "review and classify them before upgrading."
        )

    op.add_column(
        "tbl_receipts", sa.Column("source_event_id", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "tbl_receipts",
        sa.Column("source_request_signature", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        "uq_tbl_receipts_source_event_id", "tbl_receipts", ["source_event_id"]
    )
    op.add_column(
        "tbl_receipt_items",
        sa.Column(
            "disposition_subtype",
            sa.String(length=30),
            server_default="NONE",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_tbl_receipt_items_disposition_subtype",
        "tbl_receipt_items",
        "(business_disposition = 'ORDINARY_BUSINESS_PURCHASE' AND "
        "disposition_subtype IN ('DIRECT_EXPENSE', 'STOCKED_SUPPLY', 'DIRECT_SELL_RESTOCK')) "
        "OR (business_disposition IN ('UNCLASSIFIED', 'PERSONAL_NON_BUSINESS', "
        "'RECIPE_INGREDIENT', 'CAPITAL_ASSET_EQUIPMENT') AND disposition_subtype = 'NONE')",
    )
    op.add_column(
        "tbl_receipt_line_approvals",
        sa.Column("disposition_subtype", sa.String(length=30), nullable=True),
    )
    op.execute(
        sa.text(
            """UPDATE tbl_receipt_line_approvals
            SET disposition_subtype = 'NONE'"""
        )
    )
    op.alter_column("tbl_receipt_line_approvals", "disposition_subtype", nullable=False)
    op.create_check_constraint(
        "ck_tbl_receipt_line_approvals_disposition_subtype",
        "tbl_receipt_line_approvals",
        "(disposition = 'ORDINARY_BUSINESS_PURCHASE' AND "
        "disposition_subtype IN ('DIRECT_EXPENSE', 'STOCKED_SUPPLY', 'DIRECT_SELL_RESTOCK')) "
        "OR (disposition IN ('PERSONAL_NON_BUSINESS', 'RECIPE_INGREDIENT', "
        "'CAPITAL_ASSET_EQUIPMENT') AND disposition_subtype = 'NONE')",
    )
    op.add_column("tbl_store_items", sa.Column("last_disposition", sa.String(length=50)))
    op.add_column("tbl_store_items", sa.Column("last_disposition_subtype", sa.String(length=30)))

    op.create_table(
        "tbl_receipt_routing_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("receipt_item_id", sa.Integer(), nullable=False),
        sa.Column("approved_version", sa.Integer(), nullable=False),
        sa.Column("destination_kind", sa.String(length=30), nullable=False),
        sa.Column("destination_identity", sa.String(length=255), nullable=False),
        sa.Column("source_event_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("supersedes_routing_record_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "destination_kind IN ('DIRECT_EXPENSE', 'STOCKED_SUPPLY', "
            "'DIRECT_SELL_RESTOCK', 'INGREDIENT_PURCHASE', 'CAPITAL_ASSET')",
            name="ck_tbl_receipt_routing_destination_kind",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'HELD', 'POSTED', 'REVERSED')",
            name="ck_tbl_receipt_routing_status",
        ),
        sa.ForeignKeyConstraint(["receipt_item_id"], ["tbl_receipt_items.id"]),
        sa.ForeignKeyConstraint(
            ["supersedes_routing_record_id"], ["tbl_receipt_routing_records.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "receipt_item_id",
            "destination_kind",
            "approved_version",
            name="uq_tbl_receipt_routing_occurrence_destination_version",
        ),
        sa.UniqueConstraint("source_event_key", name="uq_tbl_receipt_routing_source_event"),
    )
    op.create_index(
        "ix_tbl_receipt_routing_status",
        "tbl_receipt_routing_records",
        ["status", "destination_kind"],
    )
    op.create_table(
        "tbl_receipt_expense_drafts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("receipt_item_id", sa.Integer(), nullable=False),
        sa.Column("routing_record_id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.String(length=36), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["item_id"], ["tbl_items.item_id"]),
        sa.ForeignKeyConstraint(["receipt_item_id"], ["tbl_receipt_items.id"]),
        sa.ForeignKeyConstraint(["routing_record_id"], ["tbl_receipt_routing_records.id"]),
        sa.ForeignKeyConstraint(["store_id"], ["tbl_stores.store_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("receipt_item_id"),
        sa.UniqueConstraint("routing_record_id"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    manual_event_count = connection.scalar(
        sa.text("SELECT COUNT(*) FROM tbl_receipts WHERE source_event_id IS NOT NULL")
    )
    if manual_event_count:
        raise RuntimeError(
            "Cannot downgrade manual receipt idempotency while manual receipt events exist."
        )
    routing_count = connection.scalar(sa.text("SELECT COUNT(*) FROM tbl_receipt_routing_records"))
    if routing_count:
        raise RuntimeError(
            "Cannot downgrade receipt routing while routing records exist; "
            "their approval handoff must remain auditable."
        )
    op.drop_table("tbl_receipt_expense_drafts")
    op.drop_index("ix_tbl_receipt_routing_status", table_name="tbl_receipt_routing_records")
    op.drop_table("tbl_receipt_routing_records")
    op.drop_column("tbl_store_items", "last_disposition_subtype")
    op.drop_column("tbl_store_items", "last_disposition")
    op.drop_constraint(
        "ck_tbl_receipt_line_approvals_disposition_subtype",
        "tbl_receipt_line_approvals",
        type_="check",
    )
    op.drop_column("tbl_receipt_line_approvals", "disposition_subtype")
    op.drop_constraint(
        "ck_tbl_receipt_items_disposition_subtype",
        "tbl_receipt_items",
        type_="check",
    )
    op.drop_column("tbl_receipt_items", "disposition_subtype")
    op.drop_constraint("uq_tbl_receipts_source_event_id", "tbl_receipts", type_="unique")
    op.drop_column("tbl_receipts", "source_request_signature")
    op.drop_column("tbl_receipts", "source_event_id")
