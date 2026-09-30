from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class ScanStatus(StrEnum):
    CLEAN = "CLEAN"
    INFECTED = "INFECTED"
    UNAVAILABLE = "UNAVAILABLE"


class MalwareScanner(Protocol):
    def scan(self, source: bytes) -> ScanStatus: ...


class ProtectedFileStore(Protocol):
    def save(self, source_sha256: str, source: bytes, media_type: str) -> str: ...


class Outbox(Protocol):
    def publish(self, event: OutboxEvent) -> None: ...


@dataclass(frozen=True)
class OutboxEvent:
    event_type: str
    source_sha256: str
    file_key: str


class ClamAVScanner:
    """Adapter boundary for clamd; the callable keeps local tests provider-free."""

    def __init__(self, scan_bytes: object) -> None:
        self._scan_bytes = scan_bytes

    def scan(self, source: bytes) -> ScanStatus:
        try:
            result = self._scan_bytes(source)  # type: ignore[operator]
        except OSError:
            return ScanStatus.UNAVAILABLE
        if result is None:
            return ScanStatus.UNAVAILABLE
        return ScanStatus.CLEAN if result else ScanStatus.INFECTED


class LocalProtectedFileStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def save(self, source_sha256: str, source: bytes, media_type: str) -> str:
        extension = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "application/pdf": ".pdf",
        }[media_type]
        relative_key = Path("receipts") / source_sha256[:2] / f"{source_sha256}{extension}"
        target = (self._root / relative_key).resolve()
        if self._root not in target.parents:
            raise ValueError("Protected file path escaped the configured store")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError(f"Protected file already exists: {relative_key}")
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
            temporary.write(source)
            temporary_path = Path(temporary.name)
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, target)
        return relative_key.as_posix()


class InMemoryOutbox:
    def __init__(self) -> None:
        self.events: list[OutboxEvent] = []

    def publish(self, event: OutboxEvent) -> None:
        self.events.append(event)
