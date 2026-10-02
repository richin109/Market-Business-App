"""Use JSONB for receipt OCR documents on PostgreSQL.

Revision ID: 0009_receipt_jsonb
Revises: 0008_receipt_upload_outbox
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009_receipt_jsonb"
down_revision = "0008_receipt_upload_outbox"
branch_labels = None
depends_on = None

_RECEIPT_JSON_COLUMNS = (
    ("tbl_receipts", "raw_ocr_document"),
    ("tbl_receipts", "receipt_document"),
    ("tbl_receipt_items", "raw_ocr_item"),
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table_name, column_name in _RECEIPT_JSON_COLUMNS:
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.JSON(),
            type_=postgresql.JSONB(),
            postgresql_using=f"{column_name}::jsonb",
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table_name, column_name in _RECEIPT_JSON_COLUMNS:
        op.alter_column(
            table_name,
            column_name,
            existing_type=postgresql.JSONB(),
            type_=sa.JSON(),
            postgresql_using=f"{column_name}::json",
        )
