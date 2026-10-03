from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs.models import AuditLog, Setting


class SettingsRepository:
    def get_setting(self, session: Session, key: str) -> Setting | None:
        return session.scalar(select(Setting).where(Setting.key == key))

    def values(self, session: Session, keys: tuple[str, ...]) -> dict[str, str | None]:
        return {
            key: value
            for key, value in session.execute(
                select(Setting.key, Setting.value).where(Setting.key.in_(keys))
            )
        }

    def lock_settings(self, session: Session, keys: tuple[str, ...]) -> dict[str, Setting]:
        return {
            row.key: row
            for row in session.scalars(
                select(Setting).where(Setting.key.in_(keys)).with_for_update()
            )
        }

    def update_value(
        self, session: Session, setting: Setting, value: str | None, actor_id: int, reason: str
    ) -> None:
        session.add(
            AuditLog(
                event_type="RETENTION_SETTING_UPDATED",
                actor=str(actor_id),
                entity_type="Setting",
                entity_id=setting.key,
                details=f"old={setting.value}; new={value}; reason={reason}",
            )
        )
        setting.value = value

    def flush(self, session: Session) -> None:
        session.flush()

    def commit(self, session: Session) -> None:
        session.commit()
