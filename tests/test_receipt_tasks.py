from typing import Any

from mbs.receipts.tasks import LocalOCREngine


def _document(transaction_number: str = "TC-700") -> dict[str, Any]:
    return {
        "receipt": {
            "store": "Synthetic Market",
            "date": "2026-09-30",
            "time": "14:05:06",
            "transaction_number": transaction_number,
            "total": "1.00",
        },
        "items": [{"description": "Milk", "line_total": "1.00"}],
    }


def test_ocr_boundary_preserves_provider_metadata_from_extractor() -> None:
    document = _document()
    document["metadata"] = {"provider": "synthetic-mock", "schema_version": "fixture-v2"}
    engine = LocalOCREngine(lambda source, media_type: document)

    result = engine.extract(b"synthetic", "image/png")

    assert result["metadata"] == {"provider": "synthetic-mock", "schema_version": "fixture-v2"}
