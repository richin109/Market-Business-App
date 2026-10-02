"""Add durable receipt upload dispatch outbox.

Revision ID: 0008_receipt_upload_outbox
Revises: 0007_receipt_correction_audit
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_receipt_upload_outbox"
down_revision = "0007_receipt_correction_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tbl_receipt_uploads",
        sa.Column("processing_lease_token", sa.String(length=36)),
    )
    op.add_column(
        "tbl_receipt_uploads",
        sa.Column("processing_lease_until", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "tbl_receipt_outbox_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("upload_pk", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatch_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["upload_pk"], ["tbl_receipt_uploads.upload_pk"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("upload_pk", name="uq_tbl_receipt_outbox_events_upload"),
    )
    op.add_column("tbl_receipt_uploads", sa.Column("staging_file_key", sa.String(length=500)))
    op.add_column("tbl_receipt_uploads", sa.Column("scan_status", sa.String(length=30)))
    op.add_column("tbl_receipt_uploads", sa.Column("perceptual_hash", sa.String(length=32)))
    op.create_index(
        "ix_tbl_receipt_outbox_events_pending",
        "tbl_receipt_outbox_events",
        ["dispatched_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_tbl_receipt_outbox_events_pending", table_name="tbl_receipt_outbox_events")
    op.drop_table("tbl_receipt_outbox_events")
    op.drop_column("tbl_receipt_uploads", "perceptual_hash")
    op.drop_column("tbl_receipt_uploads", "scan_status")
    op.drop_column("tbl_receipt_uploads", "staging_file_key")
    op.drop_column("tbl_receipt_uploads", "processing_lease_until")
    op.drop_column("tbl_receipt_uploads", "processing_lease_token")