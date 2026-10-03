from __future__ import annotations

from sqlalchemy.orm import Session

from mbs.domain.category_rules import CategoryRuleSpec
from mbs.repositories.receipt_rules import ReceiptRuleRepository


def load_category_rules(session: Session) -> tuple[CategoryRuleSpec, ...]:
    rows = ReceiptRuleRepository().enabled_categories(session)
    return tuple(
        CategoryRuleSpec(row.category, row.keyword, row.priority, row.enabled) for row in rows
    )
