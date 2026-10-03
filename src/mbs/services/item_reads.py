from __future__ import annotations

from sqlalchemy.orm import Session

from mbs.errors import NotFoundError
from mbs.repositories.items import ItemReadRepository


class ItemReadService:
    def __init__(self, repository: ItemReadRepository | None = None) -> None:
        self._repository = repository or ItemReadRepository()

    def mapping_context(self, session: Session) -> dict[str, object]:
        rows = self._repository.mapping_rows(session)
        return {
            "store_items": [
                {
                    "store_item_id": store_item.store_item_id,
                    "item_id": item.item_id,
                    "common_name": item.common_name,
                    "store_common_name": store_item.common_name,
                    "store_name": store.display_name,
                    "store_product_id": store_item.store_product_id,
                    "description": store_item.latest_description,
                    "upc": store_item.upc,
                    "mapping_confirmed": store_item.mapping_confirmed,
                    "is_active": item.is_active,
                    "last_purchase_date": last_purchase_date,
                }
                for store_item, item, store, last_purchase_date in rows
            ],
            "canonical_items": self._repository.list_items(session, active_only=True),
        }

    def list_items(self, session: Session, query: str | None) -> list[dict[str, object]]:
        items = self._repository.list_items(session, query)
        counts = self._repository.store_item_counts(session)
        return [
            {
                "item_id": item.item_id,
                "common_name": item.common_name,
                "is_active": item.is_active,
                "is_store_observed": item.is_store_observed,
                "superseded_by_item_id": item.superseded_by_item_id,
                "store_item_count": counts.get(item.item_id, 0),
            }
            for item in items
        ]

    def list_store_items(
        self, session: Session, query: str | None, unmapped_only: bool
    ) -> list[dict[str, object]]:
        rows = self._repository.store_item_rows(session, query, unmapped_only)
        return [
            {
                "store_item_id": store_item.store_item_id,
                "store_id": store_item.store_id,
                "store_name": store_name,
                "store_product_id": store_item.store_product_id,
                "description": store_item.latest_description,
                "upc": store_item.upc,
                "common_name": store_item.common_name,
                "item_id": item.item_id,
                "item_common_name": item.common_name,
                "mapping_confirmed": store_item.mapping_confirmed,
                "last_purchase_date": (
                    last_purchase_date.isoformat() if last_purchase_date is not None else None
                ),
            }
            for store_item, item, store_name, last_purchase_date in rows
        ]

    def get_item(self, session: Session, item_id: str) -> dict[str, object]:
        item = self._repository.get_item(session, item_id)
        if item is None:
            raise NotFoundError("Item not found")
        return {
            "item_id": item.item_id,
            "common_name": item.common_name,
            "is_active": item.is_active,
            "is_store_observed": item.is_store_observed,
            "superseded_by_item_id": item.superseded_by_item_id,
            "store_items": [
                {
                    "store_item_id": store_item.store_item_id,
                    "store_id": store_item.store_id,
                    "store_product_id": store_item.store_product_id,
                    "description": store_item.latest_description,
                }
                for store_item in self._repository.item_mappings(session, item_id)
            ],
        }


def get_item_read_service() -> ItemReadService:
    return ItemReadService()
