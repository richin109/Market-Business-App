"""Enforce case-insensitive category keywords and classify celery.

Revision ID: 0011_category_rule_casefold
Revises: 0010_auth_session_user_index
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_category_rule_casefold"
down_revision = "0010_auth_session_user_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tbl_category_rules") as batch_op:
        batch_op.drop_constraint("uq_tbl_category_rules_term", type_="unique")
    op.create_index(
        "uq_tbl_category_rules_term_ci",
        "tbl_category_rules",
        [sa.text("lower(category)"), sa.text("lower(keyword)")],
        unique=True,
    )
    connection = op.get_bind()
    rules = sa.table(
        "tbl_category_rules",
        sa.column("id", sa.Integer()),
        sa.column("category", sa.String(length=50)),
        sa.column("keyword", sa.String(length=100)),
        sa.column("priority", sa.Integer()),
    )
    next_id = connection.execute(
        sa.select(sa.func.coalesce(sa.func.max(rules.c.id), 0) + 1)
    ).scalar_one()
    connection.execute(
        rules.insert().values(
            id=next_id,
            category="Produce",
            keyword="celery",
            priority=1,
        )
    )
    if connection.dialect.name == "postgresql":
        connection.execute(
            sa.text("SELECT setval(pg_get_serial_sequence('tbl_category_rules', 'id'), :id, true)"),
            {"id": next_id},
        )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM tbl_category_rules WHERE category = 'Produce' AND keyword = 'celery'")
    )
    op.drop_index("uq_tbl_category_rules_term_ci", table_name="tbl_category_rules")
    with op.batch_alter_table("tbl_category_rules") as batch_op:
        batch_op.create_unique_constraint("uq_tbl_category_rules_term", ["category", "keyword"])
