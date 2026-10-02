"""Index auth sessions by user for revocation and management queries.

Revision ID: 0010_auth_session_user_index
Revises: 0009_receipt_jsonb
"""

from alembic import op


revision = "0010_auth_session_user_index"
down_revision = "0009_receipt_jsonb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_tbl_auth_sessions_user_id", "tbl_auth_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_tbl_auth_sessions_user_id", table_name="tbl_auth_sessions")