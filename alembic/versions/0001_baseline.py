"""Create baseline settings and operational logs.

Revision ID: 0001_baseline
Revises:
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tbl_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.bulk_insert(
        sa.table(
            "tbl_settings",
            sa.column("key", sa.String()),
            sa.column("value", sa.Text()),
            sa.column("description", sa.Text()),
        ),
        [
            {
                "key": "business_timezone",
                "value": "America/New_York",
                "description": "IANA timezone used for business-date interpretation.",
            },
            {"key": "currency", "value": "USD", "description": "Operating currency."},
            {"key": "week_start", "value": "monday", "description": "First day of business weeks."},
            {"key": "tax_year", "value": "2026", "description": "Current tax year."},
            {"key": "receipt_source_retention_days", "value": "", "description": "Unset until owner approval."},
            {"key": "receipt_raw_retention_days", "value": "", "description": "Unset until owner approval."},
        ],
    )
    op.create_table(
        "tbl_audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=True),
        sa.Column("entity_type", sa.String(length=100), nullable=True),
        sa.Column("entity_id", sa.String(length=255), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "tbl_error_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("error_type", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("tbl_error_log")
    op.drop_table("tbl_audit_log")
    op.drop_table("tbl_settings")