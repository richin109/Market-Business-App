from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mbs.models.base import Base


class MediaAsset(Base):
    __tablename__ = "tbl_media_assets"
    __table_args__ = (
        CheckConstraint(
            "original_media_type IN ('image/jpeg', 'image/png')",
            name="ck_tbl_media_assets_original_type",
        ),
        CheckConstraint(
            "scan_status = 'NOT_SCANNED'",
            name="ck_tbl_media_assets_no_scan_boundary",
        ),
        CheckConstraint(
            "ingest_status IN ('STAGED', 'READY')",
            name="ck_tbl_media_assets_ingest_status",
        ),
        CheckConstraint(
            "width_px > 0 AND height_px > 0 AND byte_size > 0",
            name="ck_tbl_media_assets_dimensions_size",
        ),
        Index(
            "uq_tbl_media_assets_perceptual_hash",
            "perceptual_hash",
            unique=True,
        ),
    )

    asset_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    original_media_type: Mapped[str] = mapped_column(String(50), nullable=False)
    original_file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    display_file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    display_media_type: Mapped[str] = mapped_column(String(50), nullable=False)
    thumbnail_file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    thumbnail_media_type: Mapped[str] = mapped_column(String(50), nullable=False)
    staging_files: Mapped[list[dict[str, str]] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    width_px: Mapped[int] = mapped_column(Integer, nullable=False)
    height_px: Mapped[int] = mapped_column(Integer, nullable=False)
    display_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    thumbnail_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    perceptual_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    scan_status: Mapped[str] = mapped_column(String(20), nullable=False)
    ingest_status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("tbl_users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MediaAssetLink(Base):
    __tablename__ = "tbl_media_asset_links"
    __table_args__ = (
        CheckConstraint(
            "owner_kind IN ('RECEIPT_LINE_CANDIDATE', 'ITEM', 'STORE_ITEM', 'RECIPE')",
            name="ck_tbl_media_asset_links_owner_kind",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED', 'REJECTED')",
            name="ck_tbl_media_asset_links_status",
        ),
        CheckConstraint("sort_order >= 0", name="ck_tbl_media_asset_links_sort_order"),
        Index(
            "uq_tbl_media_asset_links_active_primary",
            "owner_kind",
            "owner_id",
            unique=True,
            postgresql_where=text("is_primary = TRUE AND detached_at IS NULL"),
        ),
        Index(
            "uq_tbl_media_asset_links_candidate_key",
            "owner_id",
            unique=True,
            postgresql_where=text("owner_kind = 'RECEIPT_LINE_CANDIDATE'"),
        ),
        Index(
            "ix_tbl_media_asset_links_owner_active",
            "owner_kind",
            "owner_id",
            "status",
            "detached_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_sha256: Mapped[str] = mapped_column(
        ForeignKey("tbl_media_assets.asset_sha256"), nullable=False
    )
    owner_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    source_id: Mapped[int | None] = mapped_column(ForeignKey("tbl_receipt_sources.id"))
    receipt_item_id: Mapped[int | None] = mapped_column(ForeignKey("tbl_receipt_items.id"))
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_region: Mapped[dict[str, object] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("tbl_users.id"))
    detached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
