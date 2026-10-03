from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

ALLOWED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "application/pdf"})


DEFAULT_MAX_FILE_BYTES = 10_000_000


DEFAULT_MAX_IMAGE_DIMENSION_PX = 10_000


DEFAULT_PHASH_THRESHOLD = 6


FILE_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "application/pdf": (b"%PDF-",),
}


class UploadStatus(StrEnum):
    QUEUED = "QUEUED"
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    SCAN_PENDING = "SCAN_PENDING"
    MALWARE_REJECTED = "MALWARE_REJECTED"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"


@dataclass(frozen=True)
class UploadResult:
    source_sha256: str
    status: UploadStatus
    upload_pk: str | None = None
    file_key: str | None = None
    matched_source_sha256: str | None = None
    idempotent: bool = False


def _source_sha256(source: bytes) -> str:
    return hashlib.sha256(source).hexdigest()


def _has_valid_signature(source: bytes, media_type: str) -> bool:
    return any(source.startswith(signature) for signature in FILE_SIGNATURES[media_type])


def validate_upload_bytes(source: bytes, media_type: str, max_file_bytes: int) -> None:
    if media_type not in ALLOWED_MEDIA_TYPES:
        raise ValueError(f"Unsupported media type: {media_type}")
    if not source:
        raise ValueError("Receipt source must not be empty")
    if len(source) > max_file_bytes:
        raise ValueError("Receipt source exceeds the configured size limit")
    if not _has_valid_signature(source, media_type):
        raise ValueError("Receipt source signature does not match its media type")
