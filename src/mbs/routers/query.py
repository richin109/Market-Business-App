from __future__ import annotations

LIKE_ESCAPE = "\\"


def contains_pattern(value: str) -> str:
    """Build a LIKE pattern matching `value` literally; user `%` and `_` are not wildcards."""
    escaped = (
        value.strip()
        .replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )
    return f"%{escaped}%"
