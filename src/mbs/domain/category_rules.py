from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class CategoryRuleSpec:
    category: str
    keyword: str
    priority: int
    enabled: bool = True


_CATEGORY_KEYWORDS = {
    "Beverages": ("coffee", "juice", "soda", "water", "tea"),
    "Produce": ("apple", "banana", "celery", "lettuce", "tomato", "onion", "produce"),
    "Household": ("cleaner", "paper towel", "trash bag", "detergent"),
    "Frozen Meals": ("frozen", "ice cream"),
    "Lawn & Garden": ("soil", "seed", "fertilizer", "garden"),
    "Dairy": ("milk", "cheese", "yogurt", "butter"),
    "Meat": ("beef", "chicken", "pork", "turkey", "meat"),
    "Bakery": ("bread", "bun", "cake", "muffin", "bakery"),
    "Snacks": ("chip", "cracker", "cookie", "snack"),
    "Personal Care": ("shampoo", "soap", "toothpaste", "deodorant"),
}

DEFAULT_CATEGORY_RULES = tuple(
    CategoryRuleSpec(category, keyword, priority)
    for priority, (category, keywords) in enumerate(_CATEGORY_KEYWORDS.items())
    for keyword in keywords
)


def classify_description(
    description: str, rules: tuple[CategoryRuleSpec, ...] = DEFAULT_CATEGORY_RULES
) -> str:
    normalized = description.casefold()
    for rule in sorted((rule for rule in rules if rule.enabled), key=lambda rule: rule.priority):
        if _keyword_pattern(rule.keyword.casefold()).search(normalized):
            return rule.category
    return "Other"


@lru_cache(maxsize=512)
def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(keyword)}(?!\w)")
