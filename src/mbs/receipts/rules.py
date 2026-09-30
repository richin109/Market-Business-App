from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from mbs.receipts.ocr import BusinessDisposition


class RuleMatchKind(StrEnum):
    EXACT = "EXACT"
    SUGGESTION = "SUGGESTION"


@dataclass(frozen=True)
class RememberedItemRule:
    vendor: str
    description: str
    disposition: BusinessDisposition
    upc: str | None = None


@dataclass(frozen=True)
class RuleMatch:
    rule: RememberedItemRule
    kind: RuleMatchKind


def find_item_rule(
    rules: tuple[RememberedItemRule, ...],
    vendor: str,
    description: str,
    upc: str | None = None,
) -> RuleMatch | None:
    normalized_vendor = _normalize(vendor)
    if upc is not None:
        for rule in rules:
            if rule.upc == upc and _normalize(rule.vendor) == normalized_vendor:
                return RuleMatch(rule=rule, kind=RuleMatchKind.EXACT)

    description_matches = tuple(
        rule
        for rule in rules
        if rule.upc is None
        and _normalize(rule.vendor) == normalized_vendor
        and _normalize(rule.description) == _normalize(description)
    )
    if len(description_matches) == 1:
        return RuleMatch(rule=description_matches[0], kind=RuleMatchKind.EXACT)
    if description_matches:
        return RuleMatch(rule=description_matches[0], kind=RuleMatchKind.SUGGESTION)
    return None


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
