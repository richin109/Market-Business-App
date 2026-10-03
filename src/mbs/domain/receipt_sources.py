from __future__ import annotations

import re
from decimal import Decimal
from enum import StrEnum


class SourceDecision(StrEnum):
    COPY = "COPY"
    SUPPLEMENT = "SUPPLEMENT"
    REJECT = "REJECT"


def _normalized_product_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return re.sub(r"\s+", " ", value).strip().casefold()


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))
