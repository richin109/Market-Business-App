"""Align store-resolution evidence with the ORM JSON variant.

Revision ID: 0026_store_hold_jsonb
Revises: 0025_media_asset_candidate_keys
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0026_store_hold_jsonb"
down_revision = "0025_media_asset_candidate_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column(
            "tbl_store_resolution_holds",
            "raw_ocr_document",
            existing_type=sa.JSON(),
            type_=sa.JSON().with_variant(JSONB, "postgresql"),
            existing_nullable=False,
            postgresql_using="raw_ocr_document::jsonb",
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column(
            "tbl_store_resolution_holds",
            "raw_ocr_document",
            existing_type=sa.JSON().with_variant(JSONB, "postgresql"),
            type_=sa.JSON(),
            existing_nullable=False,
            postgresql_using="raw_ocr_document::json",
        )
