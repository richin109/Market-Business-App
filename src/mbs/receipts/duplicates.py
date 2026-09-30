from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from threading import Lock
from typing import Protocol

import imagehash
from PIL import Image


class PerceptualHasher(Protocol):
    def fingerprint(self, source: bytes, media_type: str) -> str: ...


class PillowPerceptualHasher:
    def fingerprint(self, source: bytes, media_type: str) -> str:
        if media_type not in {"image/jpeg", "image/png"}:
            raise ValueError("Perceptual image hashing requires a rendered image page")
        with Image.open(BytesIO(source)) as image:
            return str(imagehash.phash(image.convert("RGB")))


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


class InMemoryPerceptualDuplicateStore:
    def __init__(self) -> None:
        self._fingerprints: dict[str, str] = {}
        self._pending: dict[str, PendingDuplicate] = {}
        self._lock = Lock()

    def find_near(self, fingerprint: str, threshold: int) -> str | None:
        with self._lock:
            for source_sha256, stored in self._fingerprints.items():
                if _hamming_distance(stored, fingerprint) <= threshold:
                    return source_sha256
        return None

    def save(self, source_sha256: str, fingerprint: str) -> None:
        with self._lock:
            self._fingerprints[source_sha256] = fingerprint

    def hold(self, source_sha256: str, pending: PendingDuplicate) -> None:
        with self._lock:
            self._pending[source_sha256] = pending

    def take_pending(self, source_sha256: str) -> PendingDuplicate | None:
        with self._lock:
            return self._pending.pop(source_sha256, None)


def _hamming_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()
