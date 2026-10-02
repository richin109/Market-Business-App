from mbs.receipts.ocr import BusinessDisposition
from mbs.receipts.rules import (
    RememberedItemRule,
    RuleMatchKind,
    find_item_rule,
)


def test_rule_matching_prefers_vendor_and_upc() -> None:
    rules = (
        RememberedItemRule(
            store_item_id="store-item-1",
            vendor="Synthetic Market",
            description="Milk",
            disposition=BusinessDisposition.RECIPE_INGREDIENT,
            upc="123",
        ),
        RememberedItemRule(
            store_item_id="store-item-2",
            vendor="Synthetic Market",
            description="Milk",
            disposition=BusinessDisposition.PERSONAL_NON_BUSINESS,
        ),
    )

    match = find_item_rule(rules, "synthetic market", "Different label", "123")

    assert match is not None
    assert match.rule is not None
    assert match.kind == RuleMatchKind.EXACT
    assert match.rule.disposition is BusinessDisposition.RECIPE_INGREDIENT


def test_rule_matching_normalizes_vendor_and_description_without_upc() -> None:
    rule = RememberedItemRule(
        store_item_id="store-item-1",
        vendor="Synthetic Market",
        description="Paper towels",
        disposition=BusinessDisposition.ORDINARY_BUSINESS_PURCHASE,
    )

    match = find_item_rule((rule,), "SYNTHETIC-MARKET", "paper towels")

    assert match is not None
    assert match.kind == RuleMatchKind.EXACT


def test_rule_matching_uses_store_item_identity_before_changing_descriptions() -> None:
    rules = (
        RememberedItemRule(
            store_item_id="market-a-sku-1",
            vendor="Market A",
            description="Old printed name",
            disposition=BusinessDisposition.RECIPE_INGREDIENT,
        ),
        RememberedItemRule(
            store_item_id="market-b-sku-2",
            vendor="Market B",
            description="Different item",
            disposition=BusinessDisposition.PERSONAL_NON_BUSINESS,
        ),
    )

    match = find_item_rule(
        rules,
        "Market A",
        "New printed name",
        store_item_id="market-a-sku-1",
    )

    assert match is not None
    assert match.kind == RuleMatchKind.EXACT
    assert match.rule is rules[0]


def test_ambiguous_description_match_is_only_a_suggestion() -> None:
    rules = (
        RememberedItemRule(
            store_item_id="store-item-1",
            vendor="Synthetic Market",
            description="Mystery item",
            disposition=BusinessDisposition.PERSONAL_NON_BUSINESS,
        ),
        RememberedItemRule(
            store_item_id="store-item-2",
            vendor="Synthetic Market",
            description="Mystery item",
            disposition=BusinessDisposition.RECIPE_INGREDIENT,
        ),
    )

    match = find_item_rule(rules, "Synthetic Market", "Mystery item")

    assert match is not None
    assert match.kind == RuleMatchKind.SUGGESTION
    assert match.rule is None
    assert len(match.candidates) == 2
