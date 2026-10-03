from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    JSON,
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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mbs.models.base import Base


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
