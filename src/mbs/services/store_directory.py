from __future__ import annotations

from sqlalchemy.orm import Session

from mbs.domain.stores import StoreAdministrationConflict
from mbs.errors import NotFoundError
from mbs.models import AuditLog
from mbs.repositories.stores import StoreRepository
from mbs.services.store_admin import merge_stores, split_store_aliases
from mbs.services.store_registry import add_store_alias


class StoreDirectoryService:
    def __init__(self, repository: StoreRepository | None = None) -> None:
        self._repository = repository or StoreRepository()

    def page_context(self, session: Session) -> dict[str, object]:
        rows = self._repository.page_rows(session)
        aliases_by_store: dict[str, list[dict[str, str]]] = {}
        for store_id, key, raw_alias in self._repository.alias_rows(session):
            if raw_alias is not None:
                aliases_by_store.setdefault(store_id, []).append(
                    {"normalized_key": key, "raw_alias": raw_alias}
                )
        stores: list[dict[str, object]] = []
        for store, count, purchased in rows:
            aliases = aliases_by_store.get(store.store_id, [])
            stores.append(
                {
                    "store_id": store.store_id,
                    "display_name": store.display_name,
                    "is_active": store.is_active,
                    "alias_count": len({alias["normalized_key"] for alias in aliases}),
                    "receipt_count": count,
                    "last_purchase_date": purchased,
                    "aliases": aliases,
                }
            )
        return {"stores": stores}

    def list_stores(
        self, session: Session, query: str | None, active_only: bool
    ) -> list[dict[str, object]]:
        return [
            {
                "store_id": store.store_id,
                "display_name": store.display_name,
                "is_active": store.is_active,
                "superseded_by_store_id": store.superseded_by_store_id,
                "alias_count": aliases,
                "receipt_count": count,
                "last_purchase_date": purchased.isoformat() if purchased is not None else None,
            }
            for store, aliases, count, purchased in self._repository.directory_rows(
                session, query, active_only
            )
        ]

    def get_store(self, session: Session, store_id: str) -> dict[str, object]:
        store = self._repository.get_store(session, store_id)
        if store is None:
            raise NotFoundError("Store not found")
        return {
            "store_id": store.store_id,
            "display_name": store.display_name,
            "is_active": store.is_active,
            "superseded_by_store_id": store.superseded_by_store_id,
            "aliases": [
                {"normalized_key": key, "raw_alias": raw_alias}
                for key, raw_alias in self._repository.alias_spellings(session, store_id)
            ],
        }

    def update_store(
        self,
        session: Session,
        store_id: str,
        display_name: str | None,
        is_active: bool | None,
        confirm_duplicate_name: bool,
        actor_id: int,
    ) -> dict[str, object]:
        store = self._repository.get_store(session, store_id, lock=True)
        if store is None:
            raise NotFoundError("Store not found")
        if store.superseded_by_store_id is not None:
            raise StoreAdministrationConflict("A superseded store cannot be edited")
        if display_name is None and is_active is None:
            raise ValueError("At least one store field must be provided")
        old_name, old_active = store.display_name, store.is_active
        if display_name is not None:
            normalized_name = display_name.strip()
            if not normalized_name:
                raise ValueError("Name is required")
            duplicates = self._repository.active_stores_except(session, store_id)
            if not confirm_duplicate_name and any(
                other.display_name.casefold() == normalized_name.casefold() for other in duplicates
            ):
                raise StoreAdministrationConflict(
                    "Another active store uses this display name; explicit confirmation is required"
                )
            store.display_name = normalized_name
        if is_active is not None:
            store.is_active = is_active
        if old_name != store.display_name or old_active != store.is_active:
            self._repository.add(
                session,
                AuditLog(
                    event_type="STORE_UPDATED",
                    actor=str(actor_id),
                    entity_type="Store",
                    entity_id=store.store_id,
                    details=(
                        f"display_name={old_name!r}->{store.display_name!r}; "
                        f"is_active={old_active}->{store.is_active}"
                    ),
                ),
            )
        self._repository.commit(session)
        return {
            "store_id": store.store_id,
            "display_name": store.display_name,
            "is_active": store.is_active,
        }

    def add_alias(
        self,
        session: Session,
        store_id: str,
        raw_alias: str,
        location_signature: str | None,
        actor_id: int,
    ) -> dict[str, object]:
        store = self._repository.get_store(session, store_id)
        if store is None:
            raise NotFoundError("Store not found")
        alias_key, created = add_store_alias(session, store, raw_alias, location_signature)
        self._repository.add(
            session,
            AuditLog(
                event_type="STORE_ALIAS_ADDED" if created else "STORE_ALIAS_CONFIRMED",
                actor=str(actor_id),
                entity_type="Store",
                entity_id=store.store_id,
                details=(
                    f"raw_alias={raw_alias!r}; normalized_key={alias_key.normalized_key}; "
                    f"created={created}"
                ),
            ),
        )
        self._repository.commit(session)
        return {
            "store_id": store.store_id,
            "normalized_key": alias_key.normalized_key,
            "raw_alias": raw_alias.strip(),
            "created": created,
        }

    def merge_stores(
        self,
        session: Session,
        source_store_id: str,
        target_store_id: str,
        actor_id: int,
        reason: str,
        source_event_id: str,
    ) -> dict[str, object]:
        target, idempotent = merge_stores(
            session, source_store_id, target_store_id, actor_id, reason, source_event_id
        )
        self._repository.commit(session)
        return {
            "store_id": target.store_id,
            "display_name": target.display_name,
            "idempotent": idempotent,
        }

    def split_stores(
        self,
        session: Session,
        source_store_id: str,
        alias_keys: list[str],
        actor_id: int,
        reason: str,
        source_event_id: str,
        new_display_name: str,
    ) -> dict[str, object]:
        target, idempotent = split_store_aliases(
            session,
            source_store_id,
            alias_keys,
            actor_id,
            reason,
            source_event_id,
            new_display_name=new_display_name,
        )
        self._repository.commit(session)
        return {
            "store_id": target.store_id,
            "display_name": target.display_name,
            "idempotent": idempotent,
        }


def get_store_directory_service() -> StoreDirectoryService:
    return StoreDirectoryService()
