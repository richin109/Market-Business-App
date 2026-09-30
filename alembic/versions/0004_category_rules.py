"""Add editable merchandise category rules.

Revision ID: 0004_category_rules
Revises: 0003_receipts
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_category_rules"
down_revision = "0003_receipts"
branch_labels = None
depends_on = None


RULES = {
    "Beverages": ("coffee", "juice", "soda", "water", "tea"),
    "Produce": ("apple", "banana", "lettuce", "tomato", "onion", "produce"),
    "Household": ("cleaner", "paper towel", "trash bag", "detergent"),
    "Frozen Meals": ("frozen", "ice cream"),
    "Lawn & Garden": ("soil", "seed", "fertilizer", "garden"),
    "Dairy": ("milk", "cheese", "yogurt", "butter"),
    "Meat": ("beef", "chicken", "pork", "turkey", "meat"),
    "Bakery": ("bread", "bun", "cake", "muffin", "bakery"),
    "Snacks": ("chip", "cracker", "cookie", "snack"),
    "Personal Care": ("shampoo", "soap", "toothpaste", "deodorant"),
}


def upgrade() -> None:
    op.create_table(
        "tbl_category_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("keyword", sa.String(length=100), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("category", "keyword", name="uq_tbl_category_rules_term"),
    )
    table = sa.table(
        "tbl_category_rules",
        sa.column("category", sa.String()),
        sa.column("keyword", sa.String()),
        sa.column("priority", sa.Integer()),
    )
    op.bulk_insert(
        table,
        [
            {"category": category, "keyword": keyword, "priority": priority}
            for priority, (category, keywords) in enumerate(RULES.items())
            for keyword in keywords
        ],
    )


def downgrade() -> None:
    op.drop_table("tbl_category_rules")