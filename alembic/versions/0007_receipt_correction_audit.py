"""Add immutable receipt correction events and snapshot versions.

Revision ID: 0007_receipt_correction_audit
Revises: 0006_line_approvals
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_receipt_correction_audit"
down_revision = "0006_line_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tbl_receipts",
        sa.Column("receipt_document_version", sa.Integer(), server_default="1", nullable=False),
    )
    with op.batch_alter_table("tbl_receipt_correction_holds") as batch_op:
        batch_op.add_column(sa.Column("resolved_by", sa.Integer()))
        batch_op.add_column(sa.Column("reason", sa.Text()))
        batch_op.add_column(sa.Column("source_event_id", sa.String(length=255)))
        batch_op.create_foreign_key(
            "fk_tbl_receipt_correction_holds_resolved_by",
            "tbl_users",
            ["resolved_by"],
            ["id"],
        )
        batch_op.create_unique_constraint(
            "uq_tbl_receipt_correction_holds_source_event", ["source_event_id"]
        )
    op.add_column(
        "tbl_receipt_correction_holds", sa.Column("resolution_action", sa.String(length=20))
    )
    op.add_column(
        "tbl_receipt_correction_holds", sa.Column("resolution_reason", sa.Text())
    )
    op.add_column(
        "tbl_receipt_correction_holds",
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "tbl_receipt_corrections",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("receipt_pk", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source_event_id", sa.String(length=255), nullable=False),
        sa.Column("request_document", sa.JSON(), nullable=False),
        sa.Column("before_document", sa.JSON(), nullable=False),
        sa.Column("after_document", sa.JSON(), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["receipt_pk"], ["tbl_receipts.receipt_pk"]),
        sa.ForeignKeyConstraint(["actor_id"], ["tbl_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_event_id", name="uq_tbl_receipt_corrections_source_event"),
    )


def downgrade() -> None:
    op.drop_table("tbl_receipt_corrections")
    with op.batch_alter_table("tbl_receipt_correction_holds") as batch_op:
        batch_op.drop_constraint(
            "uq_tbl_receipt_correction_holds_source_event", type_="unique"
        )
        batch_op.drop_constraint(
            "fk_tbl_receipt_correction_holds_resolved_by", type_="foreignkey"
        )
        batch_op.drop_column("source_event_id")
        batch_op.drop_column("reason")
        batch_op.drop_column("resolved_by")
    op.drop_column("tbl_receipt_correction_holds", "resolved_at")
    op.drop_column("tbl_receipt_correction_holds", "resolution_reason")
    op.drop_column("tbl_receipt_correction_holds", "resolution_action")
    op.drop_column("tbl_receipts", "receipt_document_version")