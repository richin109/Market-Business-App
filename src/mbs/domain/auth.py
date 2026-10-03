from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

SESSION_IDLE_TIMEOUT = timedelta(hours=2)


SESSION_ABSOLUTE_TIMEOUT = timedelta(hours=12)


SESSION_TOUCH_INTERVAL = timedelta(minutes=1)


RESET_TOKEN_TIMEOUT = timedelta(minutes=30)


LOGIN_IP_WINDOW = timedelta(minutes=1)


LOGIN_ACCOUNT_LOCK = timedelta(minutes=15)


MIN_PASSWORD_LENGTH = 12


class Role(StrEnum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    VIEWER = "VIEWER"


class LoginRateLimited(Exception):
    pass


class AccountLocked(Exception):
    pass


@dataclass(frozen=True)
class ThrottleThresholds:
    ip_limit_reached: bool = False
    account_lock_started: bool = False


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()
