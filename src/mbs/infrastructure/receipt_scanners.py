from __future__ import annotations

from mbs.domain.receipt_storage import ScanStatus


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


class UnavailablePDFScanner:
    def scan(self, source: bytes) -> ScanStatus:
        return ScanStatus.UNAVAILABLE
