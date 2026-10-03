from __future__ import annotations

import hashlib
from dataclasses import dataclass

ALLOWED_IMAGE_TYPES = frozenset({"image/jpeg", "image/png"})


THUMBNAIL_MAX_SIDE = 320


DISPLAY_MAX_SIDE = 1_024


THUMBNAIL_TARGET_BYTES = 40_000


_SIGNATURES = {"image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG\r\n\x1a\n"}


@dataclass(frozen=True)
class _StagedFile:
    source: bytes
    media_type: str
    sha256: str
    staging_key: str
    final_key: str

    def as_record(self) -> dict[str, str]:
        return {
            "source_sha256": self.sha256,
            "media_type": self.media_type,
            "staging_key": self.staging_key,
            "final_key": self.final_key,
        }


def _sha256(source: bytes) -> str:
    return hashlib.sha256(source).hexdigest()
