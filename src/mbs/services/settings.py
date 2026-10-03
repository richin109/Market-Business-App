from __future__ import annotations

from sqlalchemy.orm import Session

from mbs.domain.settings import RETENTION_KEYS, validate_retention_update
from mbs.errors import NotFoundError
from mbs.repositories.settings import SettingsRepository

repository = SettingsRepository()


def read_setting(session: Session, key: str) -> str | None:
    setting = repository.get_setting(session, key)
    if setting is None:
        raise KeyError(f"Unknown setting: {key}")
    return setting.value


def read_retention_settings(session: Session) -> dict[str, int | None]:
    values = repository.values(session, RETENTION_KEYS)
    return {key: None if (raw := values.get(key)) is None else int(raw) for key in RETENTION_KEYS}


def update_retention_settings(
    session: Session, updates: dict[str, int | None], actor_id: int, reason: str
) -> dict[str, int | None]:
    normalized_reason = validate_retention_update(updates, reason)
    rows = repository.lock_settings(session, RETENTION_KEYS)
    for key, days in updates.items():
        setting = rows.get(key)
        if setting is None:
            raise NotFoundError(f"Setting not found: {key}")
        new_value = None if days is None else str(days)
        if setting.value != new_value:
            repository.update_value(session, setting, new_value, actor_id, normalized_reason)
    repository.flush(session)
    return read_retention_settings(session)


def change_retention_settings(
    session: Session, updates: dict[str, int | None], actor_id: int, reason: str
) -> dict[str, int | None]:
    result = update_retention_settings(session, updates, actor_id, reason)
    repository.commit(session)
    return result
