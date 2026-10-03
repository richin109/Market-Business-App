from __future__ import annotations

from sqlalchemy.orm import Session

from mbs.domain.items import MappingCandidate, rank_mapping_candidates
from mbs.models import StoreItem
from mbs.repositories.items import ItemRepository
from mbs.settings import read_setting

repository = ItemRepository()


def suggest_item_mappings(session: Session, store_item_id: str) -> list[dict[str, object]]:
    store_item = repository.get_store_item(session, store_item_id)
    if store_item is None:
        raise ValueError("Store item not found")
    configured_limit = read_setting(session, "item_mapping_suggestion_limit")
    if configured_limit is None:
        raise ValueError("Item mapping suggestion limit is not configured")
    try:
        limit = int(configured_limit)
    except ValueError as error:
        raise ValueError("Item mapping suggestion limit must be an integer") from error
    if not 1 <= limit <= 100:
        raise ValueError("Item mapping suggestion limit must be between 1 and 100")

    candidate_items = repository.active_items_except(session, store_item.item_id)
    candidate_store_items = repository.confirmed_store_items(session)
    store_items_by_item: dict[str, list[StoreItem]] = {}
    for candidate in candidate_store_items:
        store_items_by_item.setdefault(candidate.item_id, []).append(candidate)

    candidates: list[MappingCandidate] = []
    for candidate_item in candidate_items:
        linked_items = store_items_by_item.get(candidate_item.item_id, [])
        candidates.append(
            MappingCandidate(
                item_id=candidate_item.item_id,
                common_name=candidate_item.common_name,
                descriptions=tuple(linked.latest_description for linked in linked_items),
                upcs=frozenset(linked.upc for linked in linked_items),
            )
        )
    return rank_mapping_candidates(store_item.latest_description, store_item.upc, candidates, limit)
