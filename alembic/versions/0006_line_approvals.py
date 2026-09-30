"""Add idempotent receipt line approvals.

Revision ID: 0006_line_approvals
Revises: 0005_correction_holds
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_line_approvals"
down_revision = "0005_correction_holds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tbl_receipt_line_approvals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("receipt_item_id", sa.Integer(), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), nullable=False),
        sa.Column("disposition", sa.String(length=50), nullable=False),
        sa.Column("posting_kind", sa.String(length=50), nullable=False),
        sa.Column("posting_status", sa.String(length=20), nullable=False),
        sa.Column("source_event_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["receipt_item_id"], ["tbl_receipt_items.id"]),
        sa.ForeignKeyConstraint(["reviewer_id"], ["tbl_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("receipt_item_id", name="uq_tbl_receipt_line_approvals_item"),
        sa.UniqueConstraint("source_event_id", name="uq_tbl_receipt_line_approvals_event"),
    )


def downgrade() -> None:
    op.drop_table("tbl_receipt_line_approvals")