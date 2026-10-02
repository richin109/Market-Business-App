from __future__ import annotations

import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbs.models import Store, StoreAliasKey, StoreAliasSpelling
from mbs.settings import read_setting

STORE_ALIAS_NORMALIZATION_VERSION = "casefold-trim-whitespace-punctuation-store-number-v1"


class StoreResolutionRequired(ValueError):
    pass


def normalize_store_alias(value: str, version: str) -> str:
    if version != STORE_ALIAS_NORMALIZATION_VERSION:
        raise ValueError(f"Unsupported store alias normalization version: {version}")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w\s]|_", "", normalized)
    normalized = " ".join(normalized.split())
    normalized = re.sub(r"\s+(?:(?:store|unit)\s+)?\d+$", "", normalized)
    return " ".join(normalized.split())


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
        alias_key = session.scalar(
            select(StoreAliasKey)
            .where(StoreAliasKey.normalized_key == normalized_key)
            .execution_options(populate_existing=True)
        )
        if alias_key is None:
            store = _create_store(session, normalized_key, printed_store, location_signature)
            return store, normalized_key
        locked_store = session.scalar(
            select(Store).where(Store.store_id == alias_key.store_id).with_for_update()
        )
        if locked_store is None:
            raise RuntimeError("Store alias references a missing canonical store")
        refreshed_alias = session.scalar(
            select(StoreAliasKey)
            .where(StoreAliasKey.normalized_key == normalized_key)
            .execution_options(populate_existing=True)
        )
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
    locked_store = session.scalar(
        select(Store).where(Store.store_id == store.store_id).with_for_update()
    )
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
    alias_key = session.get(StoreAliasKey, normalized_key)
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
        with session.begin_nested():
            alias_key = StoreAliasKey(
                normalized_key=normalized_key,
                store_id=store.store_id,
                location_signature=location_signature,
            )
            session.add(alias_key)
            session.flush()
            _record_spelling(session, normalized_key, cleaned_alias)
        return alias_key, True
    except IntegrityError as error:
        alias_key = session.get(StoreAliasKey, normalized_key)
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
        with session.begin_nested():
            store = Store(display_name=printed_store)
            session.add(store)
            session.flush()
            session.add(
                StoreAliasKey(
                    normalized_key=normalized_key,
                    store_id=store.store_id,
                    location_signature=location_signature,
                )
            )
            session.flush()
            _record_spelling(session, normalized_key, printed_store)
        return store
    except IntegrityError as error:
        alias_key = session.get(StoreAliasKey, normalized_key)
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
        existing_store = session.get(Store, alias_key.store_id)
        if existing_store is None:
            raise RuntimeError("Store alias references a missing canonical store") from error
        existing_store = session.scalar(
            select(Store)
            .where(Store.store_id == alias_key.store_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if existing_store is None:
            raise RuntimeError("Store alias references a missing canonical store") from error
        _record_spelling(session, normalized_key, printed_store)
        return existing_store


def _record_spelling(session: Session, normalized_key: str, printed_store: str) -> None:
    existing = session.scalar(
        select(StoreAliasSpelling.id).where(
            StoreAliasSpelling.normalized_key == normalized_key,
            StoreAliasSpelling.raw_alias == printed_store,
        )
    )
    if existing is None:
        session.add(StoreAliasSpelling(normalized_key=normalized_key, raw_alias=printed_store))


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
