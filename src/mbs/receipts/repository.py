from __future__ import annotations

from threading import Lock

from mbs.receipts.ocr import ExtractedReceipt


class InMemoryReceiptRepository:
    def __init__(self) -> None:
        self._receipts: dict[str, ExtractedReceipt] = {}
        self._lock = Lock()

    def save(self, receipt: ExtractedReceipt) -> None:
        with self._lock:
            if receipt.receipt_id in self._receipts:
                raise ValueError(f"Receipt already exists: {receipt.receipt_id}")
            self._receipts[receipt.receipt_id] = receipt

    def get(self, receipt_id: str) -> ExtractedReceipt | None:
        with self._lock:
            return self._receipts.get(receipt_id)
