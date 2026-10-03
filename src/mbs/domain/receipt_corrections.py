from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Any

from mbs.domain.receipt_documents import _decimal_string
from mbs.domain.units import normalize_unit_alias


class CorrectionStatus(StrEnum):
    UPDATED = "UPDATED"
    HELD_FOR_ADMIN = "HELD_FOR_ADMIN"


class HoldResolutionAction(StrEnum):
    KEEP = "KEEP"
    REKEY = "REKEY"
    REJECT = "REJECT"


def _request_document(
    header_updates: dict[str, Any],
    item_updates: dict[int, dict[str, Any]],
    item_additions: Sequence[dict[str, Any]],
    item_exclusions: Sequence[int],
    remember_package_default_indexes: Sequence[int],
) -> dict[str, object]:
    return {
        "header_updates": {
            field: _request_value(value) for field, value in sorted(header_updates.items())
        },
        "item_updates": {
            str(index): {field: _request_value(value) for field, value in sorted(updates.items())}
            for index, updates in sorted(item_updates.items())
        },
        "item_additions": [
            {field: _request_value(value) for field, value in sorted(addition.items())}
            for addition in item_additions
        ],
        "item_exclusions": list(item_exclusions),
        "remember_package_default_indexes": list(remember_package_default_indexes),
    }


def _request_value(value: Any) -> object:
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return _decimal_string(value)
    return value


def _normalize_item_updates(
    item_updates: dict[int, dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    return {
        index: {field: _item_value(field, value) for field, value in updates.items()}
        for index, updates in item_updates.items()
    }


def _normalize_item_additions(
    additions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for addition in additions:
        description = str(addition.get("description", "")).strip()
        if not description or len(description) > 255:
            raise ValueError("Added receipt line requires a description of at most 255 characters")
        package_count = _item_value("package_count", addition.get("package_count"))
        unit_price = _item_value("unit_price", addition.get("unit_price"))
        if package_count is None or package_count <= 0 or unit_price is None or unit_price < 0:
            raise ValueError("Added receipt lines require a positive package count and unit price")
        pack_size = _item_value("pack_size", addition.get("pack_size"))
        if pack_size is not None and pack_size <= 0:
            raise ValueError("Pack size must be positive")
        pack_unit = _item_value("pack_unit", addition.get("pack_unit"))
        store_product_id_value = addition.get("store_product_id")
        store_product_id = (
            str(store_product_id_value).strip() if store_product_id_value is not None else None
        )
        if store_product_id == "" or (store_product_id is not None and len(store_product_id) > 255):
            raise ValueError("Store product identifier must contain at most 255 characters")
        source_id = addition.get("source_id")
        source_page = addition.get("source_page")
        source_line_number = addition.get("source_line_number")
        confirmation = addition.get("confirm_repeated_occurrence", False)
        if not isinstance(confirmation, bool):
            raise ValueError("Repeated occurrence confirmation must be boolean")
        remember_as_default = addition.get("remember_package_as_default", False)
        if not isinstance(remember_as_default, bool):
            raise ValueError("Remember package as default must be boolean")
        if source_id is None and (source_page is not None or source_line_number is not None):
            raise ValueError("Source page and line require a source association")
        if source_id is not None and (
            not isinstance(source_page, int)
            or source_page < 1
            or not isinstance(source_line_number, int)
            or source_line_number < 1
        ):
            raise ValueError("Source page and line positions must be positive integers")
        normalized.append(
            {
                "description": description,
                "upc": addition.get("upc"),
                "store_product_id": store_product_id,
                "package_count": package_count,
                "pack_size": pack_size,
                "pack_unit": pack_unit,
                "unit_price": unit_price,
                "line_total": (package_count * unit_price).quantize(Decimal("0.01")),
                "category": str(addition.get("category") or "Other"),
                "source_id": source_id,
                "source_page": source_page,
                "source_line_number": source_line_number,
                "confirm_repeated_occurrence": confirmation,
                "remember_package_as_default": remember_as_default,
            }
        )
    return normalized


def _normalized_description(value: str) -> str:
    return " ".join(value.casefold().split())


def _item_value(field: str, value: Any) -> Any:
    decimal_fields = {
        "quantity",
        "weight_lb",
        "package_count",
        "pack_size",
        "unit_price",
        "line_total",
    }
    if field in decimal_fields and value is not None:
        return Decimal(str(value))
    if field == "pack_unit" and value is not None:
        normalized = normalize_unit_alias(str(value))
        if normalized is None:
            raise ValueError("Pack unit must match a supported unit alias")
        return normalized
    return value


def _receipt_id(store: str, receipt_date: date, receipt_time: time, transaction_number: str) -> str:
    return f"{store}|{receipt_date.isoformat()}|{receipt_time.isoformat()}|{transaction_number}"


def _validate_disposition_pair(disposition: object, subtype: object) -> None:
    ordinary_subtypes = {"DIRECT_EXPENSE", "STOCKED_SUPPLY", "DIRECT_SELL_RESTOCK"}
    if disposition == "ORDINARY_BUSINESS_PURCHASE":
        if subtype not in ordinary_subtypes:
            raise ValueError("Ordinary Business Purchase requires a legal disposition subtype")
    elif disposition in {
        "UNCLASSIFIED",
        "PERSONAL_NON_BUSINESS",
        "RECIPE_INGREDIENT",
        "CAPITAL_ASSET_EQUIPMENT",
    }:
        if subtype != "NONE":
            raise ValueError("This business disposition requires subtype NONE")
    else:
        raise ValueError("Unsupported receipt business disposition")
