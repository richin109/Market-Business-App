from __future__ import annotations

import hashlib
import json
from datetime import date, time


def _receipt_id(store: str, receipt_date: date, receipt_time: time, reference: str) -> str:
    return f"{store}|{receipt_date.isoformat()}|{receipt_time.isoformat()}|{reference}"


def _request_signature(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()
