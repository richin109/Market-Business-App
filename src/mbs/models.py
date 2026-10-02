from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Setting(Base):
    __tablename__ = "tbl_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuditLog(Base):
    __tablename__ = "tbl_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(100))
    entity_type: Mapped[str | None] = mapped_column(String(100))
    entity_id: Mapped[str | None] = mapped_column(String(255))
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ErrorLog(Base):
    __tablename__ = "tbl_error_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    error_type: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Store(Base):
    __tablename__ = "tbl_stores"

    store_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")
    superseded_by_store_id: Mapped[str | None] = mapped_column(ForeignKey("tbl_stores.store_id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StoreAliasKey(Base):
    __tablename__ = "tbl_store_aliases"

    normalized_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("tbl_stores.store_id"), nullable=False)
    location_signature: Mapped[str | None] = mapped_column(String(500))


class StoreAliasSpelling(Base):
    __tablename__ = "tbl_store_alias_spellings"
    __table_args__ = (UniqueConstraint("normalized_key", "raw_alias"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    normalized_key: Mapped[str] = mapped_column(
        ForeignKey("tbl_store_aliases.normalized_key"), nullable=False
    )
    raw_alias: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Item(Base):
    __tablename__ = "tbl_items"

    item_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    common_name: Mapped[str | None] = mapped_column(String(255))
    is_store_observed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")
    superseded_by_item_id: Mapped[str | None] = mapped_column(ForeignKey("tbl_items.item_id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StoreItem(Base):
    __tablename__ = "tbl_store_items"
    __table_args__ = (
        CheckConstraint(
            "(identifier_source = 'MANUAL' AND store_product_id LIKE 'MANUAL:%') OR "
            "(identifier_source IN ('MERCHANT', 'USER_ENTERED') "
            "AND store_product_id NOT LIKE 'MANUAL:%')",
            name="ck_tbl_store_items_identifier_provenance",
        ),
        UniqueConstraint("store_id", "store_product_id", name="uq_tbl_store_items_store_product"),
        UniqueConstraint("store_item_id", "item_id", name="uq_tbl_store_items_identity"),
        Index("ix_tbl_store_items_item_id", "item_id"),
        CheckConstraint(
            "(remembered_pack_size IS NULL AND remembered_pack_unit IS NULL) OR "
            "(remembered_pack_size IS NOT NULL AND remembered_pack_size > 0 "
            "AND remembered_pack_unit IS NOT NULL AND length(trim(remembered_pack_unit)) > 0)",
            name="ck_tbl_store_items_remembered_package",
        ),
    )

    store_item_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    store_id: Mapped[str] = mapped_column(ForeignKey("tbl_stores.store_id"), nullable=False)
    store_product_id: Mapped[str] = mapped_column(String(255), nullable=False)
    item_id: Mapped[str] = mapped_column(ForeignKey("tbl_items.item_id"), nullable=False)
    latest_description: Mapped[str] = mapped_column(String(255), nullable=False)
    upc: Mapped[str | None] = mapped_column(String(50))
    common_name: Mapped[str | None] = mapped_column(String(255))
    last_disposition: Mapped[str | None] = mapped_column(String(50))
    last_disposition_subtype: Mapped[str | None] = mapped_column(String(30))
    remembered_pack_size: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    remembered_pack_unit: Mapped[str | None] = mapped_column(String(30))
    identifier_source: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="MERCHANT"
    )
    mapping_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StoreItemMapping(Base):
    __tablename__ = "tbl_store_item_mappings"
    __table_args__ = (
        UniqueConstraint(
            "store_item_id", "effective_from", name="uq_tbl_store_item_mappings_effective_from"
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_tbl_store_item_mappings_effective_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_item_id: Mapped[str] = mapped_column(
        ForeignKey("tbl_store_items.store_item_id"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(ForeignKey("tbl_items.item_id"), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    source_event_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StoreAdminEvent(Base):
    __tablename__ = "tbl_store_admin_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_event_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    request_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    source_store_id: Mapped[str] = mapped_column(String(36), nullable=False)
    target_store_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ItemMappingEvent(Base):
    __tablename__ = "tbl_item_mapping_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_event_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    request_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    store_item_id: Mapped[str] = mapped_column(String(36), nullable=False)
    previous_item_id: Mapped[str | None] = mapped_column(String(36))
    item_id: Mapped[str] = mapped_column(String(36), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StoreResolutionHold(Base):
    __tablename__ = "tbl_store_resolution_holds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upload_pk: Mapped[str] = mapped_column(
        ForeignKey("tbl_receipt_uploads.upload_pk"), unique=True, nullable=False
    )
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_ocr_document: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class User(Base):
    __tablename__ = "tbl_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuthSession(Base):
    __tablename__ = "tbl_auth_sessions"
    __table_args__ = (Index("ix_tbl_auth_sessions_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id"), nullable=False)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PasswordResetToken(Base):
    __tablename__ = "tbl_password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReceiptUpload(Base):
    __tablename__ = "tbl_receipt_uploads"

    upload_pk: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    source_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    staging_file_key: Mapped[str | None] = mapped_column(String(500))
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("tbl_users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processing_status: Mapped[str] = mapped_column(String(30), nullable=False)
    processing_lease_token: Mapped[str | None] = mapped_column(String(36))
    processing_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scan_status: Mapped[str | None] = mapped_column(String(30))
    duplicate_status: Mapped[str | None] = mapped_column(String(30))
    perceptual_hash: Mapped[str | None] = mapped_column(String(32))
    ocr_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    ocr_provider: Mapped[str | None] = mapped_column(String(100))
    ocr_schema_version: Mapped[str | None] = mapped_column(String(100))
    page_count: Mapped[int | None] = mapped_column(Integer)
    ocr_extraction_result: Mapped[dict[str, object] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )


class ReceiptOutboxEvent(Base):
    __tablename__ = "tbl_receipt_outbox_events"
    __table_args__ = (
        UniqueConstraint("upload_pk", name="uq_tbl_receipt_outbox_events_upload"),
        Index("ix_tbl_receipt_outbox_events_pending", "dispatched_at", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upload_pk: Mapped[str] = mapped_column(
        ForeignKey("tbl_receipt_uploads.upload_pk"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatch_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)


class Receipt(Base):
    __tablename__ = "tbl_receipts"
    __table_args__ = (
        UniqueConstraint("receipt_id", name="uq_tbl_receipts_receipt_id"),
        Index("ix_tbl_receipts_store_date", "store_id", "receipt_date"),
    )

    receipt_pk: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    receipt_id: Mapped[str] = mapped_column(String(255), nullable=False)
    store_id: Mapped[str] = mapped_column(ForeignKey("tbl_stores.store_id"), nullable=False)
    store_alias_key: Mapped[str] = mapped_column(
        ForeignKey("tbl_store_aliases.normalized_key"), nullable=False
    )
    store: Mapped[str] = mapped_column(String(255), nullable=False)
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False)
    receipt_time: Mapped[time] = mapped_column(Time, nullable=False)
    transaction_number: Mapped[str] = mapped_column(String(100), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="OCR")
    source_event_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    source_request_signature: Mapped[str | None] = mapped_column(String(64))
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    tax: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(50))
    upload_pk: Mapped[str | None] = mapped_column(ForeignKey("tbl_receipt_uploads.upload_pk"))
    page_number: Mapped[int | None] = mapped_column(Integer)
    import_state: Mapped[str] = mapped_column(String(30), nullable=False, server_default="DRAFT")
    ocr_provider: Mapped[str | None] = mapped_column(String(100))
    ocr_schema_version: Mapped[str | None] = mapped_column(String(100))
    raw_ocr_document: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    receipt_document: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    receipt_document_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("tbl_users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReceiptSource(Base):
    __tablename__ = "tbl_receipt_sources"
    __table_args__ = (
        UniqueConstraint("upload_pk", "receipt_pk", name="uq_tbl_receipt_sources_upload_receipt"),
        UniqueConstraint("decision_event_id", name="uq_tbl_receipt_sources_decision_event"),
        UniqueConstraint("hold_event_id", name="uq_tbl_receipt_sources_hold_event"),
        CheckConstraint(
            "association_kind IN ('PRIMARY', 'PENDING', 'SUPPLEMENT', 'COPY', 'REJECTED')",
            name="ck_tbl_receipt_sources_association_kind",
        ),
        Index("ix_tbl_receipt_sources_receipt_kind", "receipt_pk", "association_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_pk: Mapped[str] = mapped_column(ForeignKey("tbl_receipts.receipt_pk"), nullable=False)
    upload_pk: Mapped[str] = mapped_column(
        ForeignKey("tbl_receipt_uploads.upload_pk"), nullable=False
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    association_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_ocr_document: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    extracted_document: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    decision_event_id: Mapped[str | None] = mapped_column(String(255))
    hold_event_id: Mapped[str | None] = mapped_column(String(255))
    decision_actor_id: Mapped[int | None] = mapped_column(ForeignKey("tbl_users.id"))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    hold_reason: Mapped[str | None] = mapped_column(Text)
    confirmed_repeated_line_indexes: Mapped[list[int] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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


class ReceiptItem(Base):
    __tablename__ = "tbl_receipt_items"
    __table_args__ = (
        Index("ix_tbl_receipt_items_receipt_pk", "receipt_pk"),
        Index("ix_tbl_receipt_items_item_id", "item_id"),
        CheckConstraint(
            "(store_item_id IS NULL) = (item_id IS NULL)",
            name="ck_tbl_receipt_items_identity_pair",
        ),
        CheckConstraint(
            "(business_disposition = 'ORDINARY_BUSINESS_PURCHASE' AND "
            "disposition_subtype IN ('DIRECT_EXPENSE', 'STOCKED_SUPPLY', 'DIRECT_SELL_RESTOCK')) "
            "OR (business_disposition IN ('UNCLASSIFIED', 'PERSONAL_NON_BUSINESS', "
            "'RECIPE_INGREDIENT', 'CAPITAL_ASSET_EQUIPMENT') AND disposition_subtype = 'NONE')",
            name="ck_tbl_receipt_items_disposition_subtype",
        ),
        CheckConstraint(
            "package_count IS NULL OR package_count > 0",
            name="ck_tbl_receipt_items_package_count_positive",
        ),
        CheckConstraint(
            "pack_size IS NULL OR pack_size > 0",
            name="ck_tbl_receipt_items_pack_size_positive",
        ),
        CheckConstraint(
            "(is_excluded = FALSE AND exclusion_reason IS NULL) OR "
            "(is_excluded = TRUE AND exclusion_reason IS NOT NULL "
            "AND length(trim(exclusion_reason)) > 0)",
            name="ck_tbl_receipt_items_exclusion_reason",
        ),
        ForeignKeyConstraint(
            ["store_item_id"],
            ["tbl_store_items.store_item_id"],
            name="fk_tbl_receipt_items_store_item_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_pk: Mapped[str] = mapped_column(ForeignKey("tbl_receipts.receipt_pk"), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    upc: Mapped[str | None] = mapped_column(String(50))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    weight_lb: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    package_count: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    pack_size: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    pack_unit: Mapped[str | None] = mapped_column(String(30))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    business_disposition: Mapped[str] = mapped_column(String(50), nullable=False)
    disposition_subtype: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="NONE"
    )
    ocr_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    raw_ocr_item: Mapped[dict[str, object] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    source_id: Mapped[int | None] = mapped_column(ForeignKey("tbl_receipt_sources.id"))
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_line_number: Mapped[int | None] = mapped_column(Integer)
    store_item_id: Mapped[str | None] = mapped_column(String(36))
    item_id: Mapped[str | None] = mapped_column(ForeignKey("tbl_items.item_id"))
    is_excluded: Mapped[bool] = mapped_column(nullable=False, server_default="0")
    exclusion_reason: Mapped[str | None] = mapped_column(Text)


class CategoryRule(Base):
    __tablename__ = "tbl_category_rules"
    __table_args__ = (
        Index(
            "uq_tbl_category_rules_term_ci",
            text("lower(category)"),
            text("lower(keyword)"),
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    keyword: Mapped[str] = mapped_column(String(100), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReceiptCorrectionHold(Base):
    __tablename__ = "tbl_receipt_correction_holds"
    __table_args__ = (
        UniqueConstraint("source_event_id", name="uq_tbl_receipt_correction_holds_source_event"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_pk: Mapped[str] = mapped_column(ForeignKey("tbl_receipts.receipt_pk"), nullable=False)
    proposed_receipt_id: Mapped[str] = mapped_column(String(255), nullable=False)
    proposed_document: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    source_event_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING")
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("tbl_users.id"))
    resolution_action: Mapped[str | None] = mapped_column(String(20))
    resolution_reason: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReceiptCorrection(Base):
    __tablename__ = "tbl_receipt_corrections"
    __table_args__ = (
        UniqueConstraint("source_event_id", name="uq_tbl_receipt_corrections_source_event"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_pk: Mapped[str] = mapped_column(ForeignKey("tbl_receipts.receipt_pk"), nullable=False)
    actor_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    request_document: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    before_document: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    after_document: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReceiptLineApproval(Base):
    __tablename__ = "tbl_receipt_line_approvals"
    __table_args__ = (
        CheckConstraint(
            "(disposition = 'ORDINARY_BUSINESS_PURCHASE' AND "
            "disposition_subtype IN ('DIRECT_EXPENSE', 'STOCKED_SUPPLY', 'DIRECT_SELL_RESTOCK')) "
            "OR (disposition IN ('PERSONAL_NON_BUSINESS', 'RECIPE_INGREDIENT', "
            "'CAPITAL_ASSET_EQUIPMENT') AND disposition_subtype = 'NONE')",
            name="ck_tbl_receipt_line_approvals_disposition_subtype",
        ),
        UniqueConstraint(
            "receipt_item_id",
            "approval_version",
            name="uq_tbl_receipt_line_approvals_item_version",
        ),
        UniqueConstraint("source_event_id", name="uq_tbl_receipt_line_approvals_event"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_item_id: Mapped[int] = mapped_column(ForeignKey("tbl_receipt_items.id"), nullable=False)
    approval_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id"), nullable=False)
    disposition: Mapped[str] = mapped_column(String(50), nullable=False)
    disposition_subtype: Mapped[str] = mapped_column(String(30), nullable=False)
    posting_kind: Mapped[str] = mapped_column(String(50), nullable=False)
    posting_status: Mapped[str] = mapped_column(String(20), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReceiptRoutingRecord(Base):
    __tablename__ = "tbl_receipt_routing_records"
    __table_args__ = (
        UniqueConstraint(
            "receipt_item_id",
            "destination_kind",
            "approved_version",
            name="uq_tbl_receipt_routing_occurrence_destination_version",
        ),
        UniqueConstraint("source_event_key", name="uq_tbl_receipt_routing_source_event"),
        CheckConstraint(
            "destination_kind IN ('DIRECT_EXPENSE', 'STOCKED_SUPPLY', "
            "'DIRECT_SELL_RESTOCK', 'INGREDIENT_PURCHASE', 'CAPITAL_ASSET')",
            name="ck_tbl_receipt_routing_destination_kind",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'HELD', 'POSTED', 'REVERSED')",
            name="ck_tbl_receipt_routing_status",
        ),
        Index("ix_tbl_receipt_routing_status", "status", "destination_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_item_id: Mapped[int] = mapped_column(ForeignKey("tbl_receipt_items.id"), nullable=False)
    approved_version: Mapped[int] = mapped_column(Integer, nullable=False)
    destination_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    destination_identity: Mapped[str] = mapped_column(String(255), nullable=False)
    source_event_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING")
    supersedes_routing_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("tbl_receipt_routing_records.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReceiptExpenseDraft(Base):
    __tablename__ = "tbl_receipt_expense_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_item_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_receipt_items.id"), unique=True, nullable=False
    )
    routing_record_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_receipt_routing_records.id"), unique=True, nullable=False
    )
    store_id: Mapped[str] = mapped_column(ForeignKey("tbl_stores.store_id"), nullable=False)
    item_id: Mapped[str] = mapped_column(ForeignKey("tbl_items.item_id"), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
