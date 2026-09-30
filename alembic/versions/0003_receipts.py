"""Add receipt upload, header, and line-item persistence tables.

Revision ID: 0003_receipts
Revises: 0002_authentication
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_receipts"
down_revision = "0002_authentication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tbl_receipt_uploads",
        sa.Column("upload_pk", sa.String(length=36), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("file_key", sa.String(length=500), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processing_status", sa.String(length=30), nullable=False),
        sa.Column("duplicate_status", sa.String(length=30), nullable=True),
        sa.Column("ocr_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ocr_provider", sa.String(length=100), nullable=True),
        sa.Column("ocr_schema_version", sa.String(length=100), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["uploaded_by"], ["tbl_users.id"]),
        sa.PrimaryKeyConstraint("upload_pk"),
        sa.UniqueConstraint("source_sha256"),
    )
    op.create_table(
        "tbl_receipts",
        sa.Column("receipt_pk", sa.String(length=36), nullable=False),
        sa.Column("receipt_id", sa.String(length=255), nullable=False),
        sa.Column("store", sa.String(length=255), nullable=False),
        sa.Column("receipt_date", sa.Date(), nullable=False),
        sa.Column("receipt_time", sa.Time(), nullable=False),
        sa.Column("transaction_number", sa.String(length=100), nullable=False),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=True),
        sa.Column("tax", sa.Numeric(14, 2), nullable=True),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
        sa.Column("payment_method", sa.String(length=50), nullable=True),
        sa.Column("upload_pk", sa.String(length=36), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("import_state", sa.String(length=30), server_default="DRAFT", nullable=False),
        sa.Column("ocr_provider", sa.String(length=100), nullable=True),
        sa.Column("ocr_schema_version", sa.String(length=100), nullable=True),
        sa.Column("raw_ocr_document", sa.JSON(), nullable=False),
        sa.Column("receipt_document", sa.JSON(), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["upload_pk"], ["tbl_receipt_uploads.upload_pk"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["tbl_users.id"]),
        sa.PrimaryKeyConstraint("receipt_pk"),
        sa.UniqueConstraint("receipt_id", name="uq_tbl_receipts_receipt_id"),
    )
    op.create_index("ix_tbl_receipts_store_date", "tbl_receipts", ["store", "receipt_date"])
    op.create_table(
        "tbl_receipt_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("receipt_pk", sa.String(length=36), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("upc", sa.String(length=50), nullable=True),
        sa.Column("quantity", sa.Numeric(14, 4), nullable=True),
        sa.Column("weight_lb", sa.Numeric(14, 4), nullable=True),
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("line_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("business_disposition", sa.String(length=50), nullable=False),
        sa.Column("ocr_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("raw_ocr_item", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["receipt_pk"], ["tbl_receipts.receipt_pk"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tbl_receipt_items_receipt_pk", "tbl_receipt_items", ["receipt_pk"])


def downgrade() -> None:
    op.drop_index("ix_tbl_receipt_items_receipt_pk", table_name="tbl_receipt_items")
    op.drop_table("tbl_receipt_items")
    op.drop_index("ix_tbl_receipts_store_date", table_name="tbl_receipts")
    op.drop_table("tbl_receipts")
    op.drop_table("tbl_receipt_uploads")