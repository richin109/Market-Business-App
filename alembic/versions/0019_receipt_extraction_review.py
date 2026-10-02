"""Retain incomplete structured OCR results for review.

Revision ID: 0019_receipt_extraction_review
Revises: 0018_receipt_source_associations
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0019_receipt_extraction_review"
down_revision = "0018_receipt_source_associations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tbl_receipt_uploads",
        sa.Column(
            "ocr_extraction_result",
            sa.JSON().with_variant(JSONB, "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    connection = op.get_bind()
    held_results = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM tbl_receipt_uploads "
            "WHERE ocr_extraction_result IS NOT NULL"
        )
    )
    if held_results:
        raise RuntimeError(
            "Cannot downgrade while incomplete OCR results are retained for review."
        )
    op.drop_column("tbl_receipt_uploads", "ocr_extraction_result")