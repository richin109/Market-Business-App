"""Add shared media assets and owner links.

Revision ID: 0024_media_assets
Revises: 0023_store_item_package_defaults
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0024_media_assets"
down_revision = "0023_store_item_package_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(JSONB, "postgresql")
    op.create_table(
        "tbl_media_assets",
        sa.Column("asset_sha256", sa.String(length=64), nullable=False),
        sa.Column("original_media_type", sa.String(length=50), nullable=False),
        sa.Column("original_file_key", sa.String(length=500), nullable=False),
        sa.Column("display_file_key", sa.String(length=500), nullable=False),
        sa.Column("display_media_type", sa.String(length=50), nullable=False),
        sa.Column("thumbnail_file_key", sa.String(length=500), nullable=False),
        sa.Column("thumbnail_media_type", sa.String(length=50), nullable=False),
        sa.Column("staging_files", json_type),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("width_px", sa.Integer(), nullable=False),
        sa.Column("height_px", sa.Integer(), nullable=False),
        sa.Column("display_size_bytes", sa.Integer(), nullable=False),
        sa.Column("thumbnail_size_bytes", sa.Integer(), nullable=False),
        sa.Column("perceptual_hash", sa.String(length=32), nullable=False),
        sa.Column("scan_status", sa.String(length=20), nullable=False),
        sa.Column("ingest_status", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "original_media_type IN ('image/jpeg', 'image/png')",
            name="ck_tbl_media_assets_original_type",
        ),
        sa.CheckConstraint(
            "scan_status = 'NOT_SCANNED'", name="ck_tbl_media_assets_no_scan_boundary"
        ),
        sa.CheckConstraint(
            "ingest_status IN ('STAGED', 'READY')", name="ck_tbl_media_assets_ingest_status"
        ),
        sa.CheckConstraint(
            "width_px > 0 AND height_px > 0 AND byte_size > 0",
            name="ck_tbl_media_assets_dimensions_size",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["tbl_users.id"]),
        sa.PrimaryKeyConstraint("asset_sha256"),
    )
    op.create_index(
        "uq_tbl_media_assets_perceptual_hash",
        "tbl_media_assets",
        ["perceptual_hash"],
        unique=True,
    )
    op.create_table(
        "tbl_media_asset_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("asset_sha256", sa.String(length=64), nullable=False),
        sa.Column("owner_kind", sa.String(length=30), nullable=False),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("source_id", sa.Integer()),
        sa.Column("receipt_item_id", sa.Integer()),
        sa.Column("source_page", sa.Integer()),
        sa.Column("source_region", json_type),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("created_by", sa.Integer()),
        sa.Column("detached_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "owner_kind IN ('RECEIPT_LINE_CANDIDATE', 'ITEM', 'STORE_ITEM', 'RECIPE')",
            name="ck_tbl_media_asset_links_owner_kind",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED', 'REJECTED')",
            name="ck_tbl_media_asset_links_status",
        ),
        sa.CheckConstraint("sort_order >= 0", name="ck_tbl_media_asset_links_sort_order"),
        sa.ForeignKeyConstraint(["asset_sha256"], ["tbl_media_assets.asset_sha256"]),
        sa.ForeignKeyConstraint(["source_id"], ["tbl_receipt_sources.id"]),
        sa.ForeignKeyConstraint(["receipt_item_id"], ["tbl_receipt_items.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["tbl_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tbl_media_asset_links_owner_active",
        "tbl_media_asset_links",
        ["owner_kind", "owner_id", "status", "detached_at"],
    )
    op.create_index(
        "uq_tbl_media_asset_links_active_primary",
        "tbl_media_asset_links",
        ["owner_kind", "owner_id"],
        unique=True,
        postgresql_where=sa.text("is_primary = TRUE AND detached_at IS NULL"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    linked_assets = connection.scalar(sa.text("SELECT COUNT(*) FROM tbl_media_asset_links"))
    asset_count = connection.scalar(sa.text("SELECT COUNT(*) FROM tbl_media_assets"))
    if linked_assets or asset_count:
        raise RuntimeError("Cannot downgrade while media assets or links exist.")
    op.drop_index("uq_tbl_media_asset_links_active_primary", table_name="tbl_media_asset_links")
    op.drop_index("ix_tbl_media_asset_links_owner_active", table_name="tbl_media_asset_links")
    op.drop_index("uq_tbl_media_assets_perceptual_hash", table_name="tbl_media_assets")
    op.drop_table("tbl_media_asset_links")
    op.drop_table("tbl_media_assets")
