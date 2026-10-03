from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mbs.models.base import Base


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
