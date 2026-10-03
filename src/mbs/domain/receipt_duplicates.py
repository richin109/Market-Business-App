from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class PerceptualHasher(Protocol):
    def fingerprint(self, source: bytes, media_type: str) -> str: ...


@dataclass(frozen=True)
class PendingDuplicate:
    source: bytes
    media_type: str
    fingerprint: str


class PerceptualDuplicateStore(Protocol):
    def find_near(self, fingerprint: str, threshold: int) -> str | None: ...

    def save(self, source_sha256: str, fingerprint: str) -> None: ...

    def hold(self, source_sha256: str, pending: PendingDuplicate) -> None: ...

    def take_pending(self, source_sha256: str) -> PendingDuplicate | None: ...


def _hamming_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()
