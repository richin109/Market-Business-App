from __future__ import annotations


class NotFoundError(ValueError):
    """A referenced record does not exist; routes map this to HTTP 404."""
