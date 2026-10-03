from __future__ import annotations

from threading import Lock

from mbs.domain.receipt_duplicates import PendingDuplicate, _hamming_distance


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
