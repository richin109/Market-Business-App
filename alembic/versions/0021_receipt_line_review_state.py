"""Retain reviewer-excluded receipt lines without deleting evidence.

Revision ID: 0021_receipt_line_review_state
Revises: 0020_receipt_item_package_capture
"""

import sqlalchemy as sa
from alembic import op

revision = "0021_receipt_line_review_state"
down_revision = "0020_receipt_item_package_capture"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tbl_receipt_items",
        sa.Column("is_excluded", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("tbl_receipt_items", sa.Column("exclusion_reason", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_tbl_receipt_items_exclusion_reason",
        "tbl_receipt_items",
        "(is_excluded = FALSE AND exclusion_reason IS NULL) OR "
        "(is_excluded = TRUE AND exclusion_reason IS NOT NULL "
        "AND length(trim(exclusion_reason)) > 0)",
    )


def downgrade() -> None:
    connection = op.get_bind()
    excluded_lines = connection.scalar(
        sa.text("SELECT COUNT(*) FROM tbl_receipt_items WHERE is_excluded = TRUE")
    )
    if excluded_lines:
        raise RuntimeError("Cannot downgrade while reviewer-excluded receipt lines exist.")
    op.drop_constraint("ck_tbl_receipt_items_exclusion_reason", "tbl_receipt_items", type_="check")
    op.drop_column("tbl_receipt_items", "exclusion_reason")
    op.drop_column("tbl_receipt_items", "is_excluded")
