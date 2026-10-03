from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbs.domain.stores import StoreResolutionRequired, _location_signature, normalize_store_alias
from mbs.models import Store, StoreAliasKey, StoreAliasSpelling
from mbs.repositories.stores import StoreRepository
from mbs.services.settings import read_setting

repository = StoreRepository()


def resolve_store(
    session: Session,
    printed_store: str | None,
    raw_document: dict[str, object],
) -> tuple[Store, str]:
    if printed_store is None or not printed_store.strip():
        raise StoreResolutionRequired("Printed store value is missing or unreadable")
    version = read_setting(session, "store_alias_normalization_version")
    if version is None:
        raise RuntimeError("Store alias normalization version is not configured")
    normalized_key = normalize_store_alias(printed_store, version)
    if not normalized_key:
        raise StoreResolutionRequired("Printed store value is missing or unreadable")
    location_signature = _location_signature(raw_document)
    for _ in range(3):
        alias_key = repository.get_alias(session, normalized_key, refresh=True)
        if alias_key is None:
            store = _create_store(session, normalized_key, printed_store, location_signature)
            return store, normalized_key
        locked_store = repository.get_store(session, alias_key.store_id, lock=True)
        if locked_store is None:
            raise RuntimeError("Store alias references a missing canonical store")
        refreshed_alias = repository.get_alias(session, normalized_key, refresh=True)
        if refreshed_alias is None:
            continue
        if refreshed_alias.store_id != locked_store.store_id:
            continue
        alias_key = refreshed_alias
        if (
            alias_key.location_signature is not None
            and location_signature is not None
            and alias_key.location_signature != location_signature
        ):
            raise StoreResolutionRequired("Store alias matches a conflicting known location")
        if alias_key.location_signature is None:
            alias_key.location_signature = location_signature
        _record_spelling(session, normalized_key, printed_store)
        return locked_store, normalized_key
    raise StoreResolutionRequired("Store alias changed during resolution; retry the import")


def add_store_alias(
    session: Session,
    store: Store,
    raw_alias: str,
    location_signature: str | None = None,
) -> tuple[StoreAliasKey, bool]:
    locked_store = repository.get_store(session, store.store_id, lock=True)
    if locked_store is None or locked_store.superseded_by_store_id is not None:
        raise StoreResolutionRequired("Aliases cannot be changed on a superseded store")
    store = locked_store
    cleaned_alias = raw_alias.strip()
    if not cleaned_alias:
        raise StoreResolutionRequired("Store alias must not be empty")
    version = read_setting(session, "store_alias_normalization_version")
    if version is None:
        raise RuntimeError("Store alias normalization version is not configured")
    normalized_key = normalize_store_alias(cleaned_alias, version)
    if not normalized_key:
        raise StoreResolutionRequired("Store alias must not be empty")
    alias_key = repository.get_alias(session, normalized_key)
    if alias_key is not None:
        if alias_key.store_id != store.store_id:
            raise StoreResolutionRequired(
                "Normalized store alias already belongs to another canonical store"
            )
        if (
            alias_key.location_signature is not None
            and location_signature is not None
            and alias_key.location_signature != location_signature
        ):
            raise StoreResolutionRequired("Store alias matches a conflicting known location")
        if alias_key.location_signature is None:
            alias_key.location_signature = location_signature
        _record_spelling(session, normalized_key, cleaned_alias)
        return alias_key, False

    try:
        with repository.savepoint(session):
            alias_key = StoreAliasKey(
                normalized_key=normalized_key,
                store_id=store.store_id,
                location_signature=location_signature,
            )
            repository.add(session, alias_key)
            repository.flush(session)
            _record_spelling(session, normalized_key, cleaned_alias)
        return alias_key, True
    except IntegrityError as error:
        alias_key = repository.get_alias(session, normalized_key)
        if alias_key is None:
            raise
        if alias_key.store_id != store.store_id:
            raise StoreResolutionRequired(
                "Normalized store alias already belongs to another canonical store"
            ) from error
        if (
            alias_key.location_signature is not None
            and location_signature is not None
            and alias_key.location_signature != location_signature
        ):
            raise StoreResolutionRequired(
                "Store alias matches a conflicting known location"
            ) from error
        _record_spelling(session, normalized_key, cleaned_alias)
        return alias_key, False


def _create_store(
    session: Session,
    normalized_key: str,
    printed_store: str,
    location_signature: str | None,
) -> Store:
    try:
        with repository.savepoint(session):
            store = Store(display_name=printed_store)
            repository.add(session, store)
            repository.flush(session)
            repository.add(
                session,
                StoreAliasKey(
                    normalized_key=normalized_key,
                    store_id=store.store_id,
                    location_signature=location_signature,
                ),
            )
            repository.flush(session)
            _record_spelling(session, normalized_key, printed_store)
        return store
    except IntegrityError as error:
        alias_key = repository.get_alias(session, normalized_key)
        if alias_key is None:
            raise
        if (
            alias_key.location_signature is not None
            and location_signature is not None
            and alias_key.location_signature != location_signature
        ):
            raise StoreResolutionRequired(
                "Store alias matches a conflicting known location"
            ) from error
        existing_store = repository.get_store(session, alias_key.store_id)
        if existing_store is None:
            raise RuntimeError("Store alias references a missing canonical store") from error
        existing_store = repository.get_store(session, alias_key.store_id, lock=True, refresh=True)
        if existing_store is None:
            raise RuntimeError("Store alias references a missing canonical store") from error
        _record_spelling(session, normalized_key, printed_store)
        return existing_store


def _record_spelling(session: Session, normalized_key: str, printed_store: str) -> None:
    existing = repository.spelling_id(session, normalized_key, printed_store)
    if existing is None:
        repository.add(
            session, StoreAliasSpelling(normalized_key=normalized_key, raw_alias=printed_store)
        )
