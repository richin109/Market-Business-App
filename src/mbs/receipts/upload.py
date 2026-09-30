from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from typing import Protocol

from mbs.receipts.duplicates import (
    InMemoryPerceptualDuplicateStore,
    PendingDuplicate,
    PerceptualDuplicateStore,
    PerceptualHasher,
)
from mbs.receipts.ocr import ExtractedReceipt, OCREngine, normalize_receipt
from mbs.receipts.repository import InMemoryReceiptRepository
from mbs.receipts.storage import (
    MalwareScanner,
    Outbox,
    OutboxEvent,
    ProtectedFileStore,
    ScanStatus,
)

ALLOWED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "application/pdf"})
DEFAULT_MAX_FILE_BYTES = 10_000_000
DEFAULT_PHASH_THRESHOLD = 6
FILE_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "application/pdf": (b"%PDF-",),
}


class UploadStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    RECEIPT_ID_DUPLICATE = "RECEIPT_ID_DUPLICATE"
    SCAN_PENDING = "SCAN_PENDING"
    MALWARE_REJECTED = "MALWARE_REJECTED"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"


@dataclass(frozen=True)
class UploadResult:
    source_sha256: str
    status: UploadStatus
    file_key: str | None = None
    matched_source_sha256: str | None = None
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
        file_store: ProtectedFileStore | None = None,
        malware_scanner: MalwareScanner | None = None,
        outbox: Outbox | None = None,
        perceptual_hasher: PerceptualHasher | None = None,
        perceptual_store: PerceptualDuplicateStore | None = None,
        perceptual_threshold: int = DEFAULT_PHASH_THRESHOLD,
    ) -> None:
        self._ocr_engine = ocr_engine
        self._max_file_bytes = max_file_bytes
        self._source_hash_store = source_hash_store or InMemorySourceHashStore()
        self._receipt_id_store = receipt_id_store or InMemoryReceiptIdStore()
        self._receipt_repository = receipt_repository or InMemoryReceiptRepository()
        self._file_store = file_store
        self._malware_scanner = malware_scanner
        self._outbox = outbox
        self._perceptual_hasher = perceptual_hasher
        self._perceptual_store = perceptual_store or InMemoryPerceptualDuplicateStore()
        self._perceptual_threshold = perceptual_threshold

    def upload(self, source: bytes, media_type: str) -> UploadResult:
        self._validate_source(source, media_type)
        source_sha256 = _source_sha256(source)
        if not self._source_hash_store.claim(source_sha256):
            return UploadResult(
                source_sha256=source_sha256,
                status=UploadStatus.EXACT_DUPLICATE,
            )

        if self._malware_scanner is not None:
            scan_status = self._malware_scanner.scan(source)
            if scan_status is ScanStatus.UNAVAILABLE:
                self._source_hash_store.release(source_sha256)
                return UploadResult(source_sha256, UploadStatus.SCAN_PENDING)
            if scan_status is ScanStatus.INFECTED:
                return UploadResult(source_sha256, UploadStatus.MALWARE_REJECTED)

        fingerprint: str | None = None
        if self._perceptual_hasher is not None:
            fingerprint = self._perceptual_hasher.fingerprint(source, media_type)
            matched_source = self._perceptual_store.find_near(
                fingerprint, self._perceptual_threshold
            )
            if matched_source is not None:
                self._perceptual_store.hold(
                    source_sha256,
                    PendingDuplicate(source, media_type, fingerprint),
                )
                return UploadResult(
                    source_sha256,
                    UploadStatus.POSSIBLE_DUPLICATE,
                    matched_source_sha256=matched_source,
                )

        return self._accept(
            source,
            media_type,
            source_sha256,
            fingerprint,
        )

    def resolve_possible_duplicate(
        self, source_sha256: str, process_as_new: bool
    ) -> UploadResult:
        pending = self._perceptual_store.take_pending(source_sha256)
        if pending is None:
            raise ValueError("No pending possible duplicate exists")
        if not process_as_new:
            self._source_hash_store.release(source_sha256)
            return UploadResult(source_sha256, UploadStatus.EXACT_DUPLICATE)
        return self._accept(
            pending.source,
            pending.media_type,
            source_sha256,
            pending.fingerprint,
        )

    def _accept(
        self,
        source: bytes,
        media_type: str,
        source_sha256: str,
        fingerprint: str | None,
    ) -> UploadResult:
        file_key: str | None = None
        if self._file_store is not None:
            file_key = self._file_store.save(source_sha256, source, media_type)
            if self._outbox is not None:
                self._outbox.publish(
                    OutboxEvent("RECEIPT_UPLOAD_ACCEPTED", source_sha256, file_key)
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
                file_key=file_key,
            )

        if fingerprint is not None:
            self._perceptual_store.save(source_sha256, fingerprint)
        self._receipt_repository.save(receipt)
        return UploadResult(
            source_sha256=source_sha256,
            status=UploadStatus.ACCEPTED,
            file_key=file_key,
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
