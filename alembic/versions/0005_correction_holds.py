"""Add receipt correction holds.

Revision ID: 0005_correction_holds
Revises: 0004_category_rules
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_correction_holds"
down_revision = "0004_category_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tbl_receipt_correction_holds",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("receipt_pk", sa.String(length=36), nullable=False),
        sa.Column("proposed_receipt_id", sa.String(length=255), nullable=False),
        sa.Column("proposed_document", sa.JSON(), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["receipt_pk"], ["tbl_receipts.receipt_pk"]),
        sa.ForeignKeyConstraint(["reviewer_id"], ["tbl_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("tbl_receipt_correction_holds")