from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from typing import Protocol

from mbs.receipts.ocr import ExtractedReceipt, OCREngine, normalize_receipt
from mbs.receipts.repository import InMemoryReceiptRepository

ALLOWED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "application/pdf"})
DEFAULT_MAX_FILE_BYTES = 10_000_000
FILE_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "application/pdf": (b"%PDF-",),
}


class UploadStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    RECEIPT_ID_DUPLICATE = "RECEIPT_ID_DUPLICATE"


@dataclass(frozen=True)
class UploadResult:
    source_sha256: str
    status: UploadStatus
    receipt: ExtractedReceipt | None = None


class SourceHashStore(Protocol):
    def claim(self, source_sha256: str) -> bool: ...

    def release(self, source_sha256: str) -> None: ...


class ReceiptIdStore(Protocol):
    def claim(self, receipt_id: str) -> bool: ...


class ReceiptRepository(Protocol):
    def save(self, receipt: ExtractedReceipt) -> None: ...

    def get(self, receipt_id: str) -> ExtractedReceipt | None: ...


class InMemorySourceHashStore:
    def __init__(self) -> None:
        self._claimed_hashes: set[str] = set()
        self._lock = Lock()

    def claim(self, source_sha256: str) -> bool:
        with self._lock:
            if source_sha256 in self._claimed_hashes:
                return False
            self._claimed_hashes.add(source_sha256)
            return True

    def release(self, source_sha256: str) -> None:
        with self._lock:
            self._claimed_hashes.discard(source_sha256)


class InMemoryReceiptIdStore:
    def __init__(self) -> None:
        self._receipt_ids: set[str] = set()
        self._lock = Lock()

    def claim(self, receipt_id: str) -> bool:
        with self._lock:
            if receipt_id in self._receipt_ids:
                return False
            self._receipt_ids.add(receipt_id)
            return True


class ReceiptUploadService:
    def __init__(
        self,
        ocr_engine: OCREngine,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        source_hash_store: SourceHashStore | None = None,
        receipt_id_store: ReceiptIdStore | None = None,
        receipt_repository: ReceiptRepository | None = None,
    ) -> None:
        self._ocr_engine = ocr_engine
        self._max_file_bytes = max_file_bytes
        self._source_hash_store = source_hash_store or InMemorySourceHashStore()
        self._receipt_id_store = receipt_id_store or InMemoryReceiptIdStore()
        self._receipt_repository = receipt_repository or InMemoryReceiptRepository()

    def upload(self, source: bytes, media_type: str) -> UploadResult:
        self._validate_source(source, media_type)
        source_sha256 = _source_sha256(source)
        if not self._source_hash_store.claim(source_sha256):
            return UploadResult(
                source_sha256=source_sha256,
                status=UploadStatus.EXACT_DUPLICATE,
            )

        try:
            receipt = self._extract_receipt(source, media_type)
        except Exception:
            self._source_hash_store.release(source_sha256)
            raise

        if not self._receipt_id_store.claim(receipt.receipt_id):
            return UploadResult(
                source_sha256=source_sha256,
                status=UploadStatus.RECEIPT_ID_DUPLICATE,
            )

        self._receipt_repository.save(receipt)
        return UploadResult(
            source_sha256=source_sha256,
            status=UploadStatus.ACCEPTED,
            receipt=receipt,
        )

    def get_receipt(self, receipt_id: str) -> ExtractedReceipt | None:
        return self._receipt_repository.get(receipt_id)

    def _validate_source(self, source: bytes, media_type: str) -> None:
        if media_type not in ALLOWED_MEDIA_TYPES:
            raise ValueError(f"Unsupported media type: {media_type}")
        if not source:
            raise ValueError("Receipt source must not be empty")
        if len(source) > self._max_file_bytes:
            raise ValueError("Receipt source exceeds the configured size limit")
        if not _has_valid_signature(source, media_type):
            raise ValueError("Receipt source signature does not match its media type")

    def _extract_receipt(self, source: bytes, media_type: str) -> ExtractedReceipt:
        document = self._ocr_engine.extract(source, media_type)
        return normalize_receipt(document)


def _source_sha256(source: bytes) -> str:
    return hashlib.sha256(source).hexdigest()


def _has_valid_signature(source: bytes, media_type: str) -> bool:
    return any(source.startswith(signature) for signature in FILE_SIGNATURES[media_type])
