from __future__ import annotations

from enum import StrEnum
from typing import Protocol


class ScanStatus(StrEnum):
    CLEAN = "CLEAN"
    INFECTED = "INFECTED"
    UNAVAILABLE = "UNAVAILABLE"


class MalwareScanner(Protocol):
    def scan(self, source: bytes) -> ScanStatus: ...


class ProtectedFileStore(Protocol):
    def key_for(self, source_sha256: str, media_type: str) -> str: ...

    def save(self, source_sha256: str, source: bytes, media_type: str) -> str: ...

    def stage(self, source_sha256: str, source: bytes, media_type: str) -> str: ...

    def promote(self, staging_key: str, source_sha256: str, media_type: str) -> str: ...

    def read(self, file_key: str) -> bytes: ...

    def delete(self, file_key: str) -> None: ...
