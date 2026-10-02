from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs.errors import NotFoundError
from mbs.models import AuditLog, Setting

RETENTION_KEYS = ("receipt_source_retention_days", "receipt_raw_retention_days")
MAX_RETENTION_DAYS = 36500


def read_setting(session: Session, key: str) -> str | None:
    setting = session.scalar(select(Setting).where(Setting.key == key))
    if setting is None:
        raise KeyError(f"Unknown setting: {key}")
    return setting.value


def read_retention_settings(session: Session) -> dict[str, int | None]:
    values: dict[str, str | None] = {
        key: value
        for key, value in session.execute(
            select(Setting.key, Setting.value).where(Setting.key.in_(RETENTION_KEYS))
        )
    }
    return {key: None if (raw := values.get(key)) is None else int(raw) for key in RETENTION_KEYS}


def update_retention_settings(
    session: Session, updates: dict[str, int | None], actor_id: int, reason: str
) -> dict[str, int | None]:
    """Record retention periods only; no purge job exists, so NULL keeps everything (D-15)."""
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("A reason is required to change retention settings")
    unknown = set(updates) - set(RETENTION_KEYS)
    if unknown:
        raise ValueError(f"Unsupported retention setting: {sorted(unknown)[0]}")
    for key, days in updates.items():
        if days is not None and not 1 <= days <= MAX_RETENTION_DAYS:
            raise ValueError(f"{key} must be between 1 and {MAX_RETENTION_DAYS} days or unset")
    rows = {
        row.key: row
        for row in session.scalars(
            select(Setting).where(Setting.key.in_(RETENTION_KEYS)).with_for_update()
        )
    }
    for key, days in updates.items():
        setting = rows.get(key)
        if setting is None:
            raise NotFoundError(f"Setting not found: {key}")
        new_value = None if days is None else str(days)
        if setting.value == new_value:
            continue
        session.add(
            AuditLog(
                event_type="RETENTION_SETTING_UPDATED",
                actor=str(actor_id),
                entity_type="Setting",
                entity_id=key,
                details=f"old={setting.value}; new={new_value}; reason={normalized_reason}",
            )
        )
        setting.value = new_value
    session.flush()
    return read_retention_settings(session)
