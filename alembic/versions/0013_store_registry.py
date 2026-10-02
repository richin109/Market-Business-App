"""Add canonical store identity and exact alias keys.

Revision ID: 0013_store_registry
Revises: 0012_settings_catalog
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_store_registry"
down_revision = "0012_settings_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    receipt_count = connection.scalar(sa.text("SELECT COUNT(*) FROM tbl_receipts"))
    if receipt_count:
        raise RuntimeError(
            "Cannot add canonical store identity: tbl_receipts contains rows; "
            "review and migrate store identities before upgrading."
        )

    op.create_table(
        "tbl_stores",
        sa.Column("store_id", sa.String(length=36), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("superseded_by_store_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["superseded_by_store_id"], ["tbl_stores.store_id"]),
        sa.PrimaryKeyConstraint("store_id"),
    )
    op.create_table(
        "tbl_store_aliases",
        sa.Column("normalized_key", sa.String(length=255), nullable=False),
        sa.Column("store_id", sa.String(length=36), nullable=False),
        sa.Column("location_signature", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["store_id"], ["tbl_stores.store_id"]),
        sa.PrimaryKeyConstraint("normalized_key"),
    )
    op.create_table(
        "tbl_store_alias_spellings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("normalized_key", sa.String(length=255), nullable=False),
        sa.Column("raw_alias", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["normalized_key"], ["tbl_store_aliases.normalized_key"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_key", "raw_alias"),
    )
    op.create_table(
        "tbl_store_resolution_holds",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("upload_pk", sa.String(length=36), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("raw_ocr_document", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["upload_pk"], ["tbl_receipt_uploads.upload_pk"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("upload_pk"),
    )
    op.add_column("tbl_receipts", sa.Column("store_id", sa.String(length=36), nullable=False))
    op.add_column(
        "tbl_receipts", sa.Column("store_alias_key", sa.String(length=255), nullable=False)
    )
    op.create_foreign_key(
        "fk_tbl_receipts_store_id", "tbl_receipts", "tbl_stores", ["store_id"], ["store_id"]
    )
    op.create_foreign_key(
        "fk_tbl_receipts_store_alias_key",
        "tbl_receipts",
        "tbl_store_aliases",
        ["store_alias_key"],
        ["normalized_key"],
    )
    op.drop_index("ix_tbl_receipts_store_date", table_name="tbl_receipts")
    op.create_index("ix_tbl_receipts_store_date", "tbl_receipts", ["store_id", "receipt_date"])


def downgrade() -> None:
    op.drop_index("ix_tbl_receipts_store_date", table_name="tbl_receipts")
    op.drop_constraint("fk_tbl_receipts_store_alias_key", "tbl_receipts", type_="foreignkey")
    op.drop_constraint("fk_tbl_receipts_store_id", "tbl_receipts", type_="foreignkey")
    op.drop_column("tbl_receipts", "store_alias_key")
    op.drop_column("tbl_receipts", "store_id")
    op.create_index("ix_tbl_receipts_store_date", "tbl_receipts", ["store", "receipt_date"])
    op.drop_table("tbl_store_resolution_holds")
    op.drop_table("tbl_store_alias_spellings")
    op.drop_table("tbl_store_aliases")
    op.drop_table("tbl_stores")
