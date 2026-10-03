from __future__ import annotations

import hashlib
import json
import re
import unicodedata

STORE_ALIAS_NORMALIZATION_VERSION = "casefold-trim-whitespace-punctuation-store-number-v1"


class StoreResolutionRequired(ValueError):
    pass


class StoreAdministrationConflict(ValueError):
    pass


def normalize_store_alias(value: str, version: str) -> str:
    if version != STORE_ALIAS_NORMALIZATION_VERSION:
        raise ValueError(f"Unsupported store alias normalization version: {version}")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w\s]|_", "", normalized)
    normalized = " ".join(normalized.split())
    normalized = re.sub(r"\s+(?:(?:store|unit)\s+)?\d+$", "", normalized)
    return " ".join(normalized.split())


def _location_signature(raw_document: dict[str, object]) -> str | None:
    receipt = raw_document.get("receipt")
    if not isinstance(receipt, dict):
        return None
    values: list[str] = []
    for key in ("location_id", "branch_number", "address", "store_address"):
        value = receipt.get(key)
        if isinstance(value, str) and value.strip():
            normalized = unicodedata.normalize("NFKC", value).casefold()
            normalized = re.sub(r"[^\w\s]|_", "", normalized)
            values.append(f"{key}:{' '.join(normalized.split())}")
    return "|".join(values) if values else None


def _signature(payload: dict[str, str]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
