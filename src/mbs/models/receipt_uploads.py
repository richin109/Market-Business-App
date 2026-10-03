from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mbs.models.base import Base


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
