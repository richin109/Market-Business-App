"""Add effective-dated item mappings and administration events.

Revision ID: 0015_item_mapping_admin
Revises: 0014_item_identity
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_item_mapping_admin"
down_revision = "0014_item_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()

    op.drop_constraint(
        "fk_tbl_receipt_items_store_item_identity",
        "tbl_receipt_items",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_tbl_receipt_items_store_item_id",
        "tbl_receipt_items",
        "tbl_store_items",
        ["store_item_id"],
        ["store_item_id"],
    )
    op.add_column("tbl_items", sa.Column("superseded_by_item_id", sa.String(length=36)))
    op.create_foreign_key(
        "fk_tbl_items_superseded_by_item_id",
        "tbl_items",
        "tbl_items",
        ["superseded_by_item_id"],
        ["item_id"],
    )

    op.create_table(
        "tbl_store_item_mappings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("store_item_id", sa.String(length=36), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("source_event_id", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_tbl_store_item_mappings_effective_range",
        ),
        sa.ForeignKeyConstraint(["item_id"], ["tbl_items.item_id"]),
        sa.ForeignKeyConstraint(["store_item_id"], ["tbl_store_items.store_item_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "store_item_id", "effective_from", name="uq_tbl_store_item_mappings_effective_from"
        ),
        sa.UniqueConstraint("source_event_id"),
    )
    op.create_table(
        "tbl_store_admin_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_event_id", sa.String(length=255), nullable=False),
        sa.Column("request_signature", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("source_store_id", sa.String(length=36), nullable=False),
        sa.Column("target_store_id", sa.String(length=36), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_event_id"),
    )
    op.create_table(
        "tbl_item_mapping_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_event_id", sa.String(length=255), nullable=False),
        sa.Column("request_signature", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("store_item_id", sa.String(length=36), nullable=False),
        sa.Column("previous_item_id", sa.String(length=36), nullable=True),
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_event_id"),
    )
    connection.execute(
        sa.text(
            """INSERT INTO tbl_store_item_mappings
            (store_item_id, item_id, effective_from, actor)
            SELECT store_item.store_item_id, store_item.item_id,
                   COALESCE(
                       (SELECT MIN(receipt.receipt_date)
                        FROM tbl_receipt_items AS line
                        JOIN tbl_receipts AS receipt ON receipt.receipt_pk = line.receipt_pk
                        WHERE line.store_item_id = store_item.store_item_id),
                       DATE(store_item.created_at)
                   ),
                   'SYSTEM'
            FROM tbl_store_items AS store_item"""
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    inconsistent_lines = connection.scalar(
        sa.text(
            """SELECT COUNT(*) FROM tbl_receipt_items AS line
            JOIN tbl_store_items AS store_item
              ON store_item.store_item_id = line.store_item_id
            WHERE line.item_id != store_item.item_id"""
        )
    )
    if inconsistent_lines:
        raise RuntimeError(
            "Cannot downgrade item mapping history: receipt lines retain historical item IDs."
        )

    op.drop_table("tbl_item_mapping_events")
    op.drop_table("tbl_store_admin_events")
    op.drop_table("tbl_store_item_mappings")
    op.drop_constraint(
        "fk_tbl_receipt_items_store_item_id", "tbl_receipt_items", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_tbl_receipt_items_store_item_identity",
        "tbl_receipt_items",
        "tbl_store_items",
        ["store_item_id", "item_id"],
        ["store_item_id", "item_id"],
    )
    op.drop_constraint("fk_tbl_items_superseded_by_item_id", "tbl_items", type_="foreignkey")
    op.drop_column("tbl_items", "superseded_by_item_id")
