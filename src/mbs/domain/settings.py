from __future__ import annotations

RETENTION_KEYS = ("receipt_source_retention_days", "receipt_raw_retention_days")
MAX_RETENTION_DAYS = 36500


def validate_retention_update(updates: dict[str, int | None], reason: str) -> str:
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("A reason is required to change retention settings")
    unknown = set(updates) - set(RETENTION_KEYS)
    if unknown:
        raise ValueError(f"Unsupported retention setting: {sorted(unknown)[0]}")
    for key, days in updates.items():
        if days is not None and not 1 <= days <= MAX_RETENTION_DAYS:
            raise ValueError(f"{key} must be between 1 and {MAX_RETENTION_DAYS} days or unset")
    return normalized_reason
