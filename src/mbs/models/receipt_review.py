from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
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
