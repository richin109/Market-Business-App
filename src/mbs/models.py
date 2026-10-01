from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Setting(Base):
    __tablename__ = "tbl_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
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
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("tbl_users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processing_status: Mapped[str] = mapped_column(String(30), nullable=False)
    duplicate_status: Mapped[str | None] = mapped_column(String(30))
    ocr_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    ocr_provider: Mapped[str | None] = mapped_column(String(100))
    ocr_schema_version: Mapped[str | None] = mapped_column(String(100))
    page_count: Mapped[int | None] = mapped_column(Integer)


class Receipt(Base):
    __tablename__ = "tbl_receipts"
    __table_args__ = (
        UniqueConstraint("receipt_id", name="uq_tbl_receipts_receipt_id"),
        Index("ix_tbl_receipts_store_date", "store", "receipt_date"),
    )

    receipt_pk: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    receipt_id: Mapped[str] = mapped_column(String(255), nullable=False)
    store: Mapped[str] = mapped_column(String(255), nullable=False)
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False)
    receipt_time: Mapped[time] = mapped_column(Time, nullable=False)
    transaction_number: Mapped[str] = mapped_column(String(100), nullable=False)
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    tax: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(50))
    upload_pk: Mapped[str | None] = mapped_column(ForeignKey("tbl_receipt_uploads.upload_pk"))
    page_number: Mapped[int | None] = mapped_column(Integer)
    import_state: Mapped[str] = mapped_column(String(30), nullable=False, server_default="DRAFT")
    ocr_provider: Mapped[str | None] = mapped_column(String(100))
    ocr_schema_version: Mapped[str | None] = mapped_column(String(100))
    raw_ocr_document: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    receipt_document: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    receipt_document_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("tbl_users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReceiptItem(Base):
    __tablename__ = "tbl_receipt_items"
    __table_args__ = (Index("ix_tbl_receipt_items_receipt_pk", "receipt_pk"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_pk: Mapped[str] = mapped_column(ForeignKey("tbl_receipts.receipt_pk"), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    upc: Mapped[str | None] = mapped_column(String(50))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    weight_lb: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    business_disposition: Mapped[str] = mapped_column(String(50), nullable=False)
    ocr_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    raw_ocr_item: Mapped[dict[str, object] | None] = mapped_column(JSON)


class CategoryRule(Base):
    __tablename__ = "tbl_category_rules"
    __table_args__ = (UniqueConstraint("category", "keyword", name="uq_tbl_category_rules_term"),)

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

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_pk: Mapped[str] = mapped_column(ForeignKey("tbl_receipts.receipt_pk"), nullable=False)
    proposed_receipt_id: Mapped[str] = mapped_column(String(255), nullable=False)
    proposed_document: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING")
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
    before_document: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    after_document: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReceiptLineApproval(Base):
    __tablename__ = "tbl_receipt_line_approvals"
    __table_args__ = (
        UniqueConstraint("receipt_item_id", name="uq_tbl_receipt_line_approvals_item"),
        UniqueConstraint("source_event_id", name="uq_tbl_receipt_line_approvals_event"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_item_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_receipt_items.id"), nullable=False
    )
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id"), nullable=False)
    disposition: Mapped[str] = mapped_column(String(50), nullable=False)
    posting_kind: Mapped[str] = mapped_column(String(50), nullable=False)
    posting_status: Mapped[str] = mapped_column(String(20), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
