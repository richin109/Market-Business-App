"""Capture reviewed receipt package composition.

Revision ID: 0020_receipt_item_package_capture
Revises: 0019_receipt_extraction_review
"""

import sqlalchemy as sa
from alembic import op

revision = "0020_receipt_item_package_capture"
down_revision = "0019_receipt_extraction_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=128),
        existing_nullable=False,
    )
    columns = (
        sa.Column("package_count", sa.Numeric(14, 4), nullable=True),
        sa.Column("pack_size", sa.Numeric(14, 4), nullable=True),
        sa.Column("pack_unit", sa.String(length=30), nullable=True),
    )
    for column in columns:
        op.add_column("tbl_receipt_items", column)
    op.create_check_constraint(
        "ck_tbl_receipt_items_package_count_positive",
        "tbl_receipt_items",
        "package_count IS NULL OR package_count > 0",
    )
    op.create_check_constraint(
        "ck_tbl_receipt_items_pack_size_positive",
        "tbl_receipt_items",
        "pack_size IS NULL OR pack_size > 0",
    )


def downgrade() -> None:
    connection = op.get_bind()
    captured_packages = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM tbl_receipt_items "
            "WHERE package_count IS NOT NULL OR pack_size IS NOT NULL OR pack_unit IS NOT NULL"
        )
    )
    if captured_packages:
        raise RuntimeError("Cannot downgrade while reviewed receipt package data exists.")
    op.drop_constraint(
        "ck_tbl_receipt_items_package_count_positive",
        "tbl_receipt_items",
        type_="check",
    )
    op.drop_constraint(
        "ck_tbl_receipt_items_pack_size_positive", "tbl_receipt_items", type_="check"
    )
    op.drop_column("tbl_receipt_items", "pack_unit")
    op.drop_column("tbl_receipt_items", "pack_size")
    op.drop_column("tbl_receipt_items", "package_count")
