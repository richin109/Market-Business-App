from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from mbs.models import CategoryRule
from mbs.receipts.category_rules import load_category_rules
from mbs.receipts.ocr import normalize_receipt


def test_category_rules_are_seeded_and_editable(tmp_path: Path) -> None:
    database_path = tmp_path / "category-rules.db"
    engine = create_engine(f"sqlite:///{database_path}")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")

    with Session(engine) as session:
        rule = session.scalar(
            select(CategoryRule).where(
                CategoryRule.category == "Other", CategoryRule.keyword == "kombucha"
            )
        )
        assert rule is None
        session.add(CategoryRule(category="Beverages", keyword="kombucha", priority=0))
        session.commit()
        rules = load_category_rules(session)

    receipt = normalize_receipt(
        {
            "receipt": {
                "store": "Synthetic Market",
                "date": "2026-09-30",
                "time": "14:05:06",
                "transaction_number": "TC-990",
                "total": "1.00",
            },
            "items": [{"description": "Kombucha", "line_total": "1.00"}],
        },
        rules,
    )

    assert receipt.items[0].category == "Beverages"
