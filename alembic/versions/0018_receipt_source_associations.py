"""Associate immutable source extractions with receipt orders and lines.

Revision ID: 0018_receipt_source_associations
Revises: 0017_receipt_approval_versions
"""

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0018_receipt_source_associations"
down_revision = "0017_receipt_approval_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    op.create_table(
        "tbl_receipt_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("receipt_pk", sa.String(length=36), nullable=False),
        sa.Column("upload_pk", sa.String(length=36), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("association_kind", sa.String(length=20), nullable=False),
        sa.Column("raw_ocr_document", sa.JSON().with_variant(JSONB, "postgresql"), nullable=False),
        sa.Column(
            "extracted_document",
            sa.JSON().with_variant(JSONB, "postgresql"),
            nullable=False,
        ),
        sa.Column("decision_event_id", sa.String(length=255), nullable=True),
        sa.Column("hold_event_id", sa.String(length=255), nullable=True),
        sa.Column("decision_actor_id", sa.Integer(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("hold_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "association_kind IN ('PRIMARY', 'PENDING', 'SUPPLEMENT', 'COPY', 'REJECTED')",
            name="ck_tbl_receipt_sources_association_kind",
        ),
        sa.ForeignKeyConstraint(["receipt_pk"], ["tbl_receipts.receipt_pk"]),
        sa.ForeignKeyConstraint(["upload_pk"], ["tbl_receipt_uploads.upload_pk"]),
        sa.ForeignKeyConstraint(["decision_actor_id"], ["tbl_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "upload_pk", "receipt_pk", name="uq_tbl_receipt_sources_upload_receipt"
        ),
        sa.UniqueConstraint("decision_event_id", name="uq_tbl_receipt_sources_decision_event"),
        sa.UniqueConstraint("hold_event_id", name="uq_tbl_receipt_sources_hold_event"),
    )
    op.create_index(
        "ix_tbl_receipt_sources_receipt_kind",
        "tbl_receipt_sources",
        ["receipt_pk", "association_kind"],
    )

    op.add_column("tbl_receipt_items", sa.Column("source_id", sa.Integer(), nullable=True))
    op.add_column("tbl_receipt_items", sa.Column("source_page", sa.Integer(), nullable=True))
    op.add_column("tbl_receipt_items", sa.Column("source_line_number", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_tbl_receipt_items_source_id",
        "tbl_receipt_items",
        "tbl_receipt_sources",
        ["source_id"],
        ["id"],
    )
    op.create_index("ix_tbl_receipt_items_source_id", "tbl_receipt_items", ["source_id"])

    source_table = sa.table(
        "tbl_receipt_sources",
        sa.column("id", sa.Integer()),
        sa.column("receipt_pk", sa.String()),
        sa.column("upload_pk", sa.String()),
        sa.column("source_sha256", sa.String()),
        sa.column("association_kind", sa.String()),
        sa.column("raw_ocr_document", sa.JSON().with_variant(JSONB, "postgresql")),
        sa.column("extracted_document", sa.JSON().with_variant(JSONB, "postgresql")),
    )
    receipts = sa.table(
        "tbl_receipts",
        sa.column("receipt_pk", sa.String()),
        sa.column("upload_pk", sa.String()),
        sa.column("page_number", sa.Integer()),
        sa.column("raw_ocr_document", sa.JSON().with_variant(JSONB, "postgresql")),
        sa.column("receipt_document", sa.JSON().with_variant(JSONB, "postgresql")),
    )
    uploads = sa.table(
        "tbl_receipt_uploads",
        sa.column("upload_pk", sa.String()),
        sa.column("source_sha256", sa.String()),
    )
    existing_sources = connection.execute(
        sa.select(
            receipts.c.receipt_pk,
            receipts.c.upload_pk,
            uploads.c.source_sha256,
            receipts.c.page_number,
            receipts.c.raw_ocr_document,
            receipts.c.receipt_document,
        )
        .select_from(receipts.join(uploads, uploads.c.upload_pk == receipts.c.upload_pk))
        .where(receipts.c.upload_pk.is_not(None))
    ).mappings()
    for row in existing_sources:
        connection.execute(
            sa.insert(source_table).values(
                receipt_pk=row["receipt_pk"],
                upload_pk=row["upload_pk"],
                source_sha256=row["source_sha256"],
                association_kind="PRIMARY",
                raw_ocr_document=row["raw_ocr_document"],
                extracted_document=row["receipt_document"],
            )
        )
        source_id = connection.scalar(
            sa.select(source_table.c.id).where(
                source_table.c.upload_pk == row["upload_pk"],
                source_table.c.receipt_pk == row["receipt_pk"],
            )
        )
        source_page = row["page_number"] or 1
        extracted_document = row["receipt_document"]
        if isinstance(extracted_document, str):
            extracted_document = json.loads(extracted_document)
        if isinstance(extracted_document, dict):
            source_items = extracted_document.get("items")
            if isinstance(source_items, list):
                for line_number, source_item in enumerate(source_items, start=1):
                    if isinstance(source_item, dict):
                        source_item.update(
                            {
                                "source_id": source_id,
                                "source_page": source_page,
                                "source_line_number": line_number,
                            }
                        )
            connection.execute(
                sa.update(source_table)
                .where(source_table.c.id == source_id)
                .values(extracted_document=extracted_document)
            )
            connection.execute(
                sa.update(receipts)
                .where(receipts.c.receipt_pk == row["receipt_pk"])
                .values(receipt_document=extracted_document)
            )
        line_ids = (
            connection.execute(
                sa.text(
                    "SELECT id FROM tbl_receipt_items WHERE receipt_pk = :receipt_pk ORDER BY id"
                ),
                {"receipt_pk": row["receipt_pk"]},
            )
            .scalars()
            .all()
        )
        for line_number, line_id in enumerate(line_ids, start=1):
            connection.execute(
                sa.text(
                    """UPDATE tbl_receipt_items
                    SET source_id = :source_id, source_page = :source_page,
                        source_line_number = :line_number
                    WHERE id = :line_id"""
                ),
                {
                    "source_id": source_id,
                    "source_page": source_page,
                    "line_number": line_number,
                    "line_id": line_id,
                },
            )


def downgrade() -> None:
    connection = op.get_bind()
    undecided_count = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM tbl_receipt_sources WHERE association_kind NOT IN ('PRIMARY')"
        )
    )
    if undecided_count:
        raise RuntimeError(
            "Cannot downgrade receipt source associations while non-primary source decisions exist."
        )
    op.drop_index("ix_tbl_receipt_items_source_id", table_name="tbl_receipt_items")
    op.drop_constraint("fk_tbl_receipt_items_source_id", "tbl_receipt_items", type_="foreignkey")
    op.drop_column("tbl_receipt_items", "source_line_number")
    op.drop_column("tbl_receipt_items", "source_page")
    op.drop_column("tbl_receipt_items", "source_id")
    op.drop_index("ix_tbl_receipt_sources_receipt_kind", table_name="tbl_receipt_sources")
    op.drop_table("tbl_receipt_sources")
