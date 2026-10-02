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
    store_item_id: str
    vendor: str
    description: str
    disposition: BusinessDisposition
    upc: str | None = None


@dataclass(frozen=True)
class RuleMatch:
    rule: RememberedItemRule | None
    kind: RuleMatchKind
    candidates: tuple[RememberedItemRule, ...]


def find_item_rule(
    rules: tuple[RememberedItemRule, ...],
    vendor: str,
    description: str,
    upc: str | None = None,
    store_item_id: str | None = None,
) -> RuleMatch | None:
    if store_item_id is not None:
        identity_matches = tuple(rule for rule in rules if rule.store_item_id == store_item_id)
        if len(identity_matches) == 1:
            return RuleMatch(identity_matches[0], RuleMatchKind.EXACT, identity_matches)
        if identity_matches:
            return RuleMatch(None, RuleMatchKind.SUGGESTION, identity_matches)

    normalized_vendor = _normalize(vendor)
    if upc is not None:
        upc_matches = tuple(
            rule
            for rule in rules
            if rule.upc == upc and _normalize(rule.vendor) == normalized_vendor
        )
        if len(upc_matches) == 1:
            return RuleMatch(upc_matches[0], RuleMatchKind.EXACT, upc_matches)
        if upc_matches:
            return RuleMatch(None, RuleMatchKind.SUGGESTION, upc_matches)

    description_matches = tuple(
        rule
        for rule in rules
        if rule.upc is None
        and _normalize(rule.vendor) == normalized_vendor
        and _normalize(rule.description) == _normalize(description)
    )
    if len(description_matches) == 1:
        return RuleMatch(description_matches[0], RuleMatchKind.EXACT, description_matches)
    if description_matches:
        return RuleMatch(None, RuleMatchKind.SUGGESTION, description_matches)
    return None


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
