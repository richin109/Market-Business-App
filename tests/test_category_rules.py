from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbs.models import CategoryRule, ReceiptItem
from mbs.receipts.category_rules import load_category_rules
from mbs.receipts.ocr import normalize_receipt
from mbs.receipts.persistence import persist_extracted_receipt
from tests.database import postgres_test_url


def _receipt_document(description: str) -> dict[str, object]:
    return {
        "receipt": {
            "store": "Synthetic Market",
            "date": "2026-09-30",
            "time": "14:05:06",
            "transaction_number": "CAT-101",
            "total": "1.00",
        },
        "items": [{"description": description, "line_total": "1.00"}],
    }


def test_category_rules_are_seeded_and_editable(tmp_path: Path) -> None:
    database_path = tmp_path / "category-rules.db"
    engine = create_engine(postgres_test_url(database_path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(database_path).replace("%", "%%"))
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


def test_category_keywords_match_words_without_substring_false_positives(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "category-word-boundaries.db"
    engine = create_engine(postgres_test_url(database_path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(database_path).replace("%", "%%"))
    command.upgrade(config, "head")

    with Session(engine) as session:
        rules = load_category_rules(session)
        assert normalize_receipt(_receipt_document("BEEF STEAK"), rules).items[0].category == "Meat"
        assert (
            normalize_receipt(_receipt_document("CHIPOTLE SEASONING"), rules).items[0].category
            == "Other"
        )
        assert (
            normalize_receipt(_receipt_document("CELERY BUNCH"), rules).items[0].category
            == "Produce"
        )


def test_rule_edit_is_case_insensitive_and_does_not_reclassify_saved_lines(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "category-rule-edits.db"
    engine = create_engine(postgres_test_url(database_path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(database_path).replace("%", "%%"))
    command.upgrade(config, "head")

    with Session(engine) as session:
        saved_receipt = persist_extracted_receipt(
            session, normalize_receipt(_receipt_document("Coffee Beans"))
        )
        coffee_rule = session.scalar(
            select(CategoryRule).where(
                CategoryRule.category == "Beverages", CategoryRule.keyword == "coffee"
            )
        )
        assert coffee_rule is not None
        coffee_rule.enabled = False
        session.flush()

        assert (
            normalize_receipt(_receipt_document("Coffee Beans"), load_category_rules(session))
            .items[0]
            .category
            == "Other"
        )
        saved_line = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_pk == saved_receipt.receipt_pk)
        )
        assert saved_line is not None and saved_line.category == "Beverages"

        coffee_rule.enabled = True
        coffee_rule.keyword = "roast"
        session.commit()

        rules = load_category_rules(session)
        assert (
            normalize_receipt(_receipt_document("ROAST BEANS"), rules).items[0].category
            == "Beverages"
        )
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(CategoryRule(category="Beverages", keyword="ROAST", priority=0))
                session.flush()
