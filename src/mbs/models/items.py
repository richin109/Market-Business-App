from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from mbs.models.base import Base


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
