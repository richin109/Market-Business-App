"""Add idempotent receipt image candidate keys.

Revision ID: 0025_media_asset_candidate_keys
Revises: 0024_media_assets
"""

import sqlalchemy as sa
from alembic import op

revision = "0025_media_asset_candidate_keys"
down_revision = "0024_media_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_tbl_media_asset_links_candidate_key",
        "tbl_media_asset_links",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("owner_kind = 'RECEIPT_LINE_CANDIDATE'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_tbl_media_asset_links_candidate_key",
        table_name="tbl_media_asset_links",
    )
