from __future__ import annotations


class NotFoundError(ValueError):
    """A referenced record does not exist; routes map this to HTTP 404."""


class ConflictError(ValueError):
    pass


class UnavailableError(ValueError):
    pass


class UnsupportedMediaError(ValueError):
    pass


class BackupError(RuntimeError):
    """A backup is incomplete, corrupt, or would overwrite existing data."""
