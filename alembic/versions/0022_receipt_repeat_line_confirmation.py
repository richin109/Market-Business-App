"""Persist per-occurrence confirmation for supplementary source lines.

Revision ID: 0022_receipt_repeat_line_confirmation
Revises: 0021_receipt_line_review_state
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0022_receipt_repeat_line_confirmation"
down_revision = "0021_receipt_line_review_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tbl_receipt_sources",
        sa.Column(
            "confirmed_repeated_line_indexes",
            sa.JSON().with_variant(JSONB, "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    confirmed_sources = op.get_bind().scalar(
        sa.text(
            "SELECT COUNT(*) FROM tbl_receipt_sources "
            "WHERE confirmed_repeated_line_indexes IS NOT NULL"
        )
    )
    if confirmed_sources:
        raise RuntimeError(
            "Cannot downgrade while repeated source-line confirmations are recorded."
        )
    op.drop_column("tbl_receipt_sources", "confirmed_repeated_line_indexes")
