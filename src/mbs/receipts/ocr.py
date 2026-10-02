from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Protocol

from mbs.receipts.category_rules import CategoryRuleSpec, classify_description


class OCREngine(Protocol):
    def extract(self, source: bytes, media_type: str) -> dict[str, Any]: ...


class BusinessDisposition(StrEnum):
    UNCLASSIFIED = "UNCLASSIFIED"
    PERSONAL_NON_BUSINESS = "PERSONAL_NON_BUSINESS"
    ORDINARY_BUSINESS_PURCHASE = "ORDINARY_BUSINESS_PURCHASE"
    RECIPE_INGREDIENT = "RECIPE_INGREDIENT"
    CAPITAL_ASSET_EQUIPMENT = "CAPITAL_ASSET_EQUIPMENT"


@dataclass(frozen=True)
class OCRMetadata:
    provider: str
    schema_version: str
    confidence: Decimal | None
    page_count: int | None


@dataclass(frozen=True)
class ReceiptItem:
    description: str
    line_total: Decimal
    category: str
    business_disposition: BusinessDisposition = BusinessDisposition.UNCLASSIFIED
    upc: str | None = None
    quantity: Decimal | None = None
    weight_lb: Decimal | None = None
    unit_price: Decimal | None = None
    store_product_id: str | None = None
    raw_ocr_item: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExtractedReceipt:
    receipt_id: str
    store: str | None
    receipt_date: date
    receipt_time: time
    transaction_number: str
    total: Decimal
    subtotal: Decimal | None
    tax: Decimal | None
    payment_method: str | None
    items: tuple[ReceiptItem, ...]
    total_mismatch: bool
    raw_ocr_document: dict[str, Any]
    raw_date: str
    raw_time: str
    ocr_metadata: OCRMetadata


def classify_merchandise(
    description: str, rules: tuple[CategoryRuleSpec, ...] | None = None
) -> str:
    if rules is None:
        return classify_description(description)
    return classify_description(description, rules)


def normalize_receipt(
    document: dict[str, Any], rules: tuple[CategoryRuleSpec, ...] | None = None
) -> ExtractedReceipt:
    header = document["receipt"]
    raw_date = str(header["date"])
    raw_time = str(header["time"])
    receipt_date = date.fromisoformat(raw_date)
    receipt_time = time.fromisoformat(raw_time)
    transaction_number = str(header["transaction_number"])
    store_value = header.get("store")
    store = store_value.strip() if isinstance(store_value, str) else None
    receipt_id = (
        f"{store or ''}|{receipt_date.isoformat()}|{receipt_time.isoformat()}|{transaction_number}"
    )

    items = tuple(_normalize_item(item, rules) for item in document.get("items", []))
    total = _decimal(header["total"])
    item_total = sum((item.line_total for item in items), Decimal("0"))
    subtotal = _optional_decimal(header.get("subtotal"))
    tax = _optional_decimal(header.get("tax"))
    expected_subtotal = subtotal if subtotal is not None else total - (tax or Decimal("0"))
    ocr_metadata = _normalize_metadata(document.get("metadata", {}))

    return ExtractedReceipt(
        receipt_id=receipt_id,
        store=store,
        receipt_date=receipt_date,
        receipt_time=receipt_time,
        transaction_number=transaction_number,
        total=total,
        subtotal=subtotal,
        tax=tax,
        payment_method=header.get("payment_method"),
        items=items,
        total_mismatch=(
            item_total.quantize(Decimal("0.01")) != expected_subtotal.quantize(Decimal("0.01"))
        ),
        raw_ocr_document=deepcopy(document),
        raw_date=raw_date,
        raw_time=raw_time,
        ocr_metadata=ocr_metadata,
    )


def _normalize_item(
    item: dict[str, Any], rules: tuple[CategoryRuleSpec, ...] | None = None
) -> ReceiptItem:
    description = str(item["description"]).strip()
    return ReceiptItem(
        description=description,
        line_total=_decimal(item["line_total"]),
        category=classify_merchandise(description, rules),
        upc=_optional_string(item.get("upc")),
        quantity=_optional_decimal(item.get("quantity")),
        weight_lb=_optional_decimal(item.get("weight_lb")),
        unit_price=_optional_decimal(item.get("unit_price")),
        store_product_id=_optional_nonblank_string(item.get("store_product_id")),
        raw_ocr_item=deepcopy(item),
    )


def _normalize_metadata(metadata: dict[str, Any]) -> OCRMetadata:
    page_count = metadata.get("page_count")
    return OCRMetadata(
        provider=str(metadata.get("provider", "unknown")),
        schema_version=str(metadata.get("schema_version", "unknown")),
        confidence=_optional_decimal(metadata.get("confidence")),
        page_count=None if page_count is None else int(page_count),
    )


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"Invalid monetary value: {value!r}") from error


def _optional_decimal(value: Any) -> Decimal | None:
    return None if value is None else _decimal(value)


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_nonblank_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
