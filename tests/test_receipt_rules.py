from mbs.receipts.ocr import BusinessDisposition
from mbs.receipts.rules import (
    RememberedItemRule,
    RuleMatchKind,
    find_item_rule,
)


def test_rule_matching_prefers_vendor_and_upc() -> None:
    rules = (
        RememberedItemRule(
            vendor="Synthetic Market",
            description="Milk",
            disposition=BusinessDisposition.RECIPE_INGREDIENT,
            upc="123",
        ),
        RememberedItemRule(
            vendor="Synthetic Market",
            description="Milk",
            disposition=BusinessDisposition.PERSONAL_NON_BUSINESS,
        ),
    )

    match = find_item_rule(rules, "synthetic market", "Different label", "123")

    assert match is not None
    assert match.kind == RuleMatchKind.EXACT
    assert match.rule.disposition is BusinessDisposition.RECIPE_INGREDIENT


def test_rule_matching_normalizes_vendor_and_description_without_upc() -> None:
    rule = RememberedItemRule(
        vendor="Synthetic Market",
        description="Paper towels",
        disposition=BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
    )

    match = find_item_rule((rule,), "SYNTHETIC-MARKET", "paper towels")

    assert match is not None
    assert match.kind == RuleMatchKind.EXACT


def test_ambiguous_description_match_is_only_a_suggestion() -> None:
    rules = (
        RememberedItemRule(
            vendor="Synthetic Market",
            description="Mystery item",
            disposition=BusinessDisposition.PERSONAL_NON_BUSINESS,
        ),
        RememberedItemRule(
            vendor="Synthetic Market",
            description="Mystery item",
            disposition=BusinessDisposition.RECIPE_INGREDIENT,
        ),
    )

    match = find_item_rule(rules, "Synthetic Market", "Mystery item")

    assert match is not None
    assert match.kind == RuleMatchKind.SUGGESTION
