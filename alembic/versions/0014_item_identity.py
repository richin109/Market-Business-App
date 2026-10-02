"""Add canonical purchased-item and store-item identity.

Revision ID: 0014_item_identity
Revises: 0013_store_registry
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_item_identity"
down_revision = "0013_store_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    line_count = connection.scalar(sa.text("SELECT COUNT(*) FROM tbl_receipt_items"))
    if line_count:
        raise RuntimeError(
            "Cannot add purchased-item identity: tbl_receipt_items contains rows; "
            "review and migrate line identities before upgrading."
        )

    op.add_column(
        "tbl_receipts",
        sa.Column("source_type", sa.String(length=20), server_default="OCR", nullable=False),
    )
    op.create_table(
        "tbl_items",
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("common_name", sa.String(length=255), nullable=True),
        sa.Column("is_store_observed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("item_id"),
    )
    op.create_table(
        "tbl_store_items",
        sa.Column("store_item_id", sa.String(length=36), nullable=False),
        sa.Column("store_id", sa.String(length=36), nullable=False),
        sa.Column("store_product_id", sa.String(length=255), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("latest_description", sa.String(length=255), nullable=False),
        sa.Column("upc", sa.String(length=50), nullable=True),
        sa.Column("common_name", sa.String(length=255), nullable=True),
        sa.Column(
            "identifier_source", sa.String(length=20), server_default="MERCHANT", nullable=False
        ),
        sa.Column("mapping_confirmed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "identifier_source IN ('MERCHANT', 'USER_ENTERED', 'MANUAL')",
            name="ck_tbl_store_items_identifier_source",
        ),
        sa.CheckConstraint(
            "(identifier_source = 'MANUAL' AND store_product_id LIKE 'MANUAL:%') OR "
            "(identifier_source IN ('MERCHANT', 'USER_ENTERED') "
            "AND store_product_id NOT LIKE 'MANUAL:%')",
            name="ck_tbl_store_items_identifier_provenance",
        ),
        sa.ForeignKeyConstraint(["store_id"], ["tbl_stores.store_id"]),
        sa.ForeignKeyConstraint(["item_id"], ["tbl_items.item_id"]),
        sa.PrimaryKeyConstraint("store_item_id"),
        sa.UniqueConstraint(
            "store_id", "store_product_id", name="uq_tbl_store_items_store_product"
        ),
        sa.UniqueConstraint("store_item_id", "item_id", name="uq_tbl_store_items_identity"),
    )
    op.create_index("ix_tbl_store_items_item_id", "tbl_store_items", ["item_id"])

    op.add_column(
        "tbl_receipt_items", sa.Column("store_item_id", sa.String(length=36), nullable=True)
    )
    op.add_column("tbl_receipt_items", sa.Column("item_id", sa.String(length=36), nullable=True))
    op.create_check_constraint(
        "ck_tbl_receipt_items_identity_pair",
        "tbl_receipt_items",
        "(store_item_id IS NULL) = (item_id IS NULL)",
    )
    op.create_foreign_key(
        "fk_tbl_receipt_items_store_item_identity",
        "tbl_receipt_items",
        "tbl_store_items",
        ["store_item_id", "item_id"],
        ["store_item_id", "item_id"],
    )
    op.create_foreign_key(
        "fk_tbl_receipt_items_item_id",
        "tbl_receipt_items",
        "tbl_items",
        ["item_id"],
        ["item_id"],
    )
    op.create_index("ix_tbl_receipt_items_item_id", "tbl_receipt_items", ["item_id"])


def downgrade() -> None:
    op.drop_index("ix_tbl_receipt_items_item_id", table_name="tbl_receipt_items")
    op.drop_constraint("fk_tbl_receipt_items_item_id", "tbl_receipt_items", type_="foreignkey")
    op.drop_constraint(
        "fk_tbl_receipt_items_store_item_identity",
        "tbl_receipt_items",
        type_="foreignkey",
    )
    op.drop_constraint("ck_tbl_receipt_items_identity_pair", "tbl_receipt_items", type_="check")
    op.drop_column("tbl_receipt_items", "item_id")
    op.drop_column("tbl_receipt_items", "store_item_id")
    op.drop_index("ix_tbl_store_items_item_id", table_name="tbl_store_items")
    op.drop_table("tbl_store_items")
    op.drop_table("tbl_items")
    op.drop_column("tbl_receipts", "source_type")
