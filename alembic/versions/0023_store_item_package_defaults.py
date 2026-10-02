"""Remember confirmed package size and unit for store items.

Revision ID: 0023_store_item_package_defaults
Revises: 0022_receipt_repeat_line_confirmation
"""

import sqlalchemy as sa
from alembic import op

revision = "0023_store_item_package_defaults"
down_revision = "0022_receipt_repeat_line_confirmation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tbl_store_items", sa.Column("remembered_pack_size", sa.Numeric(14, 4)))
    op.add_column("tbl_store_items", sa.Column("remembered_pack_unit", sa.String(length=30)))
    op.create_check_constraint(
        "ck_tbl_store_items_remembered_package",
        "tbl_store_items",
        "(remembered_pack_size IS NULL AND remembered_pack_unit IS NULL) OR "
        "(remembered_pack_size IS NOT NULL AND remembered_pack_size > 0 "
        "AND remembered_pack_unit IS NOT NULL AND length(trim(remembered_pack_unit)) > 0)",
    )


def downgrade() -> None:
    connection = op.get_bind()
    remembered_packages = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM tbl_store_items "
            "WHERE remembered_pack_size IS NOT NULL OR remembered_pack_unit IS NOT NULL"
        )
    )
    if remembered_packages:
        raise RuntimeError("Cannot downgrade while store-item package defaults are recorded.")
    op.drop_constraint("ck_tbl_store_items_remembered_package", "tbl_store_items", type_="check")
    op.drop_column("tbl_store_items", "remembered_pack_unit")
    op.drop_column("tbl_store_items", "remembered_pack_size")
