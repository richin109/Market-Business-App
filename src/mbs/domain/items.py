from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class MappingCandidate:
    item_id: str
    common_name: str | None
    descriptions: tuple[str, ...]
    upcs: frozenset[str | None]


def rank_mapping_candidates(
    description: str, upc: str | None, candidates: list[MappingCandidate], limit: int
) -> list[dict[str, object]]:
    normalized_description = _normalize_item_text(description)
    suggestions: list[dict[str, object]] = []
    for candidate in candidates:
        reasons: set[str] = set()
        score = 0.0
        if upc is not None and upc in candidate.upcs:
            score += 100
            reasons.add("Shared UPC")
        common_name = _normalize_item_text(candidate.common_name or "")
        if common_name and common_name == normalized_description:
            score += 90
            reasons.add("Common name matches printed description")
        descriptions = {_normalize_item_text(value) for value in candidate.descriptions}
        if normalized_description and normalized_description in descriptions:
            score += 80
            reasons.add("Previously confirmed description")
        closest_description = max(
            (
                SequenceMatcher(None, normalized_description, value).ratio()
                for value in descriptions
                if value
            ),
            default=0.0,
        )
        if closest_description >= 0.55 and "Previously confirmed description" not in reasons:
            score += closest_description * 40
            reasons.add("Similar confirmed description")
        if reasons:
            suggestions.append(
                {
                    "item_id": candidate.item_id,
                    "common_name": candidate.common_name,
                    "score": round(score, 3),
                    "reasons": sorted(reasons),
                }
            )

    def sort_key(suggestion: dict[str, object]) -> tuple[float, str]:
        score = suggestion["score"]
        return (-(score if isinstance(score, float) else 0.0), str(suggestion["item_id"]))

    suggestions.sort(key=sort_key)
    return suggestions[:limit]


def _normalize_common_name(common_name: str | None) -> str | None:
    if common_name is None:
        return None
    normalized_name = common_name.strip()
    if len(normalized_name) > 255:
        raise ValueError("Common name must be 255 characters or fewer")
    return normalized_name or None


def _request_signature(payload: dict[str, str]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _child_event_id(source_event_id: str, store_item_id: str) -> str:
    return "item-merge:" + hashlib.sha256(f"{source_event_id}:{store_item_id}".encode()).hexdigest()


def _normalize_item_text(value: str) -> str:
    return " ".join(value.casefold().split())
