from __future__ import annotations

from enum import StrEnum

from mbs.domain.receipt_normalization import BusinessDisposition


class PostingKind(StrEnum):
    NO_POST = "NO_POST"
    DIRECT_EXPENSE = "DIRECT_EXPENSE"
    ORDINARY_EXPENSE = "DIRECT_EXPENSE"
    STOCKED_SUPPLY = "STOCKED_SUPPLY"
    DIRECT_SELL_RESTOCK = "DIRECT_SELL_RESTOCK"
    INGREDIENT_PURCHASE = "INGREDIENT_PURCHASE"
    CAPITAL_ASSET = "CAPITAL_ASSET"


class DispositionSubtype(StrEnum):
    NONE = "NONE"
    DIRECT_EXPENSE = "DIRECT_EXPENSE"
    STOCKED_SUPPLY = "STOCKED_SUPPLY"
    DIRECT_SELL_RESTOCK = "DIRECT_SELL_RESTOCK"


class PostingStatus(StrEnum):
    NO_POST = "NO_POST"
    ROUTED = "ROUTED"
    HELD = "HELD"


def validate_disposition_pair(
    disposition: BusinessDisposition, subtype: DispositionSubtype
) -> None:
    if disposition is BusinessDisposition.ORDINARY_BUSINESS_PURCHASE:
        if subtype is DispositionSubtype.NONE:
            raise ValueError("Ordinary Business Purchase requires a disposition subtype")
    elif subtype is not DispositionSubtype.NONE:
        raise ValueError("Only Ordinary Business Purchase accepts a disposition subtype")
