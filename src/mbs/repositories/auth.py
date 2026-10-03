from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs.models import AuthSession, Base, PasswordResetToken, User


class AuthRepository:
    def first_user(self, session: Session) -> User | None:
        return session.scalar(select(User))

    def user_by_name(self, session: Session, username: str, *, lock: bool = False) -> User | None:
        query = select(User).where(User.username == username)
        return session.scalar(query.with_for_update() if lock else query)

    def get_user(self, session: Session, user_id: int, *, lock: bool = False) -> User | None:
        if not lock:
            return session.get(User, user_id)
        return session.scalar(select(User).where(User.id == user_id).with_for_update())

    def auth_session(self, session: Session, token_hash: str) -> AuthSession | None:
        return session.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))

    def reset_token_for_update(
        self, session: Session, token_hash: str
    ) -> PasswordResetToken | None:
        return session.scalar(
            select(PasswordResetToken)
            .where(PasswordResetToken.token_hash == token_hash)
            .with_for_update()
        )

    def active_sessions_for_update(self, session: Session, user_id: int) -> list[AuthSession]:
        return list(
            session.scalars(
                select(AuthSession)
                .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
                .with_for_update()
            )
        )

    def unused_resets_for_update(self, session: Session, user_id: int) -> list[PasswordResetToken]:
        return list(
            session.scalars(
                select(PasswordResetToken)
                .where(PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None))
                .with_for_update()
            )
        )

    def list_users(self, session: Session) -> list[User]:
        return list(session.scalars(select(User).order_by(User.id)))

    def add(self, session: Session, record: Base) -> None:
        session.add(record)

    def flush(self, session: Session) -> None:
        session.flush()

    def commit(self, session: Session) -> None:
        session.commit()

    def commit_if_dirty(self, session: Session) -> None:
        if session.dirty:
            session.commit()
