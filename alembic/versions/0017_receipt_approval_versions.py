"""Allow audited receipt approval revisions.

Revision ID: 0017_receipt_approval_versions
Revises: 0016_receipt_routing
"""

import sqlalchemy as sa
from alembic import op

revision = "0017_receipt_approval_versions"
down_revision = "0016_receipt_routing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_tbl_receipt_line_approvals_item",
        "tbl_receipt_line_approvals",
        type_="unique",
    )
    op.add_column(
        "tbl_receipt_line_approvals",
        sa.Column("approval_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_unique_constraint(
        "uq_tbl_receipt_line_approvals_item_version",
        "tbl_receipt_line_approvals",
        ["receipt_item_id", "approval_version"],
    )

    op.execute(
        sa.text(
            """UPDATE tbl_receipt_routing_records
            SET approved_version = 1
            WHERE receipt_item_id IN (
                SELECT receipt_item_id FROM tbl_receipt_line_approvals
            )"""
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    revised_count = connection.scalar(
        sa.text("SELECT COUNT(*) FROM tbl_receipt_line_approvals WHERE approval_version > 1")
    )
    if revised_count:
        raise RuntimeError(
            "Cannot downgrade receipt approval versions while revised approvals exist."
        )
    op.drop_constraint(
        "uq_tbl_receipt_line_approvals_item_version",
        "tbl_receipt_line_approvals",
        type_="unique",
    )
    op.drop_column("tbl_receipt_line_approvals", "approval_version")
    op.create_unique_constraint(
        "uq_tbl_receipt_line_approvals_item",
        "tbl_receipt_line_approvals",
        ["receipt_item_id"],
    )
