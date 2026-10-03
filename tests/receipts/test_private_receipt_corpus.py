from __future__ import annotations

import hashlib
import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pytest

from mbs.infrastructure.receipt_ocr import LocalReceiptOCREngine

_HEADER_FIELDS = {
    "store": ("store",),
    "date": ("date",),
    "time": ("time",),
    "transaction_number": ("transaction_number",),
    "subtotal": ("subtotal",),
    "tax": ("tax",),
    "total": ("total",),
    "payment_method": ("payment_method",),
    "card_last_four": ("card_last_four", "payment_suffix", "masked_card_suffix"),
}
_ITEM_FIELDS = {
    "description": ("description",),
    "item_number": ("store_product_id", "item_number"),
    "line_total": ("line_total",),
    "quantity": ("quantity",),
    "size": ("printed_size", "size"),
}


def _equal_value(expected: object, actual: object) -> bool:
    if expected is None or actual is None:
        return expected is actual
    try:
        return Decimal(str(expected).strip().replace("$", "").replace(",", "")) == Decimal(
            str(actual).strip().replace("$", "").replace(",", "")
        )
    except (InvalidOperation, ValueError):
        return str(expected).strip().casefold() == str(actual).strip().casefold()


def _field_comparisons(
    expected: dict[str, Any], actual: dict[str, Any], field_map: dict[str, tuple[str, ...]]
) -> list[dict[str, object]]:
    comparisons: list[dict[str, object]] = []
    for expected_key, actual_keys in field_map.items():
        if expected_key not in expected:
            continue
        actual_key = next((key for key in actual_keys if key in actual), actual_keys[0])
        actual_value = actual.get(actual_key)
        comparisons.append(
            {
                "field": expected_key,
                "expected": expected[expected_key],
                "actual": actual_value,
                "match": _equal_value(expected[expected_key], actual_value),
            }
        )
    return comparisons


def _evaluate_order(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, object]:
    expected_header = expected.get("receipt", expected)
    actual_header = actual.get("receipt", {})
    header_comparisons = (
        _field_comparisons(expected_header, actual_header, _HEADER_FIELDS)
        if isinstance(expected_header, dict) and isinstance(actual_header, dict)
        else []
    )
    expected_items = expected.get("items", [])
    actual_items = actual.get("items", [])
    item_results: list[dict[str, object]] = []
    if isinstance(expected_items, list) and isinstance(actual_items, list):
        for index, expected_item in enumerate(expected_items):
            actual_item = actual_items[index] if index < len(actual_items) else {}
            if isinstance(expected_item, dict) and isinstance(actual_item, dict):
                item_results.append(
                    {
                        "index": index,
                        "comparisons": _field_comparisons(
                            expected_item, actual_item, _ITEM_FIELDS
                        ),
                    }
                )
    return {
        "header": header_comparisons,
        "items": item_results,
        "expected_item_count": len(expected_items) if isinstance(expected_items, list) else 0,
        "actual_item_count": len(actual_items) if isinstance(actual_items, list) else 0,
        "review_required": actual.get("review_required") is True,
        "issue_codes": (actual.get("extraction", {}).get("issues", [])
                        if isinstance(actual.get("extraction"), dict) else []),
    }


def test_rm_024(record_property: Any) -> None:
    if os.environ.get("CI", "").casefold() in {"1", "true", "yes"}:
        pytest.skip("The private receipt corpus must never run in CI")
    reference_dir_value = os.environ.get("MBS_REFERENCE_PDF_DIR")
    if not reference_dir_value:
        pytest.skip("Set MBS_REFERENCE_PDF_DIR for the isolated local accuracy evaluation")

    reference_dir = Path(reference_dir_value).expanduser().resolve()
    if not reference_dir.is_dir():
        pytest.fail("The configured private receipt directory does not exist")
    expected_path = Path(
        os.environ.get("MBS_REFERENCE_EXPECTED_RESULTS", reference_dir / "expected-results.json")
    ).expanduser().resolve()
    if not expected_path.is_file():
        pytest.fail("The configured reviewed-expectation file does not exist")

    expected_data = json.loads(expected_path.read_text(encoding="utf-8"))
    expected_rows = expected_data.get("receipts") if isinstance(expected_data, dict) else None
    if not isinstance(expected_rows, list):
        pytest.fail("Expected results must contain a receipts list")

    inputs = sorted(
        path
        for path in reference_dir.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".pdf", ".png", ".jpg", ".jpeg"}
    )
    if not inputs:
        pytest.fail("The configured private receipt directory contains no supported files")
    files_by_name: dict[str, list[Path]] = {}
    for path in inputs:
        files_by_name.setdefault(path.name.casefold(), []).append(path)

    engine = LocalReceiptOCREngine()
    report: dict[str, Any] = {
        "input_count": len(inputs),
        "expectation_count": len(expected_rows),
        "evaluations": [],
        "unmatched_input_count": 0,
        "missing_input_count": 0,
        "unreviewed_expectation_count": 0,
        "checksum_missing_count": 0,
        "accuracy_eligible_expectation_count": 0,
        "accuracy_thresholds": None,
        "accuracy_claim": False,
    }
    matched_names: set[str] = set()
    for row in expected_rows:
        if not isinstance(row, dict) or not isinstance(row.get("file"), str):
            report["evaluations"].append({"state": "INVALID_EXPECTATION_ENTRY"})
            continue
        name = Path(row["file"]).name.casefold()
        matches = files_by_name.get(name, [])
        if len(matches) != 1:
            report["missing_input_count"] += int(not matches)
            report["evaluations"].append(
                {
                    "file": row["file"],
                    "state": "MISSING_INPUT" if not matches else "AMBIGUOUS_INPUT",
                }
            )
            continue

        source_path = matches[0]
        matched_names.add(name)
        source = source_path.read_bytes()
        source_hash = hashlib.sha256(source).hexdigest()
        expected_hash = row.get("sha256", row.get("checksum_sha256"))
        checksum_matches = expected_hash == source_hash if expected_hash else None
        if not row.get("reviewed"):
            report["unreviewed_expectation_count"] += 1
        if not expected_hash:
            report["checksum_missing_count"] += 1
        eligible = row.get("reviewed") is True and checksum_matches is True
        report["accuracy_eligible_expectation_count"] += int(eligible)
        evaluation: dict[str, Any] = {
            "file": str(source_path),
            "sha256": source_hash,
            "checksum_matches": checksum_matches,
            "reviewed": row.get("reviewed") is True,
            "accuracy_eligible": eligible,
        }
        try:
            media_type = (
                "application/pdf"
                if source_path.suffix.casefold() == ".pdf"
                else {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                }[source_path.suffix.casefold()]
            )
            extracted = engine.extract(source, media_type)
            actual_orders = extracted.get("orders")
            if not isinstance(actual_orders, list):
                actual_orders = [extracted]
            expected = row.get("expected", {})
            expected_orders = expected.get("orders") if isinstance(expected, dict) else None
            if not isinstance(expected_orders, list):
                expected_orders = [expected]
            evaluation["orders"] = [
                _evaluate_order(
                    expected_order,
                    actual_orders[index] if index < len(actual_orders) else {},
                )
                for index, expected_order in enumerate(expected_orders)
                if isinstance(expected_order, dict)
            ]
            evaluation["expected_order_count"] = len(expected_orders)
            evaluation["actual_order_count"] = len(actual_orders)
        except Exception as error:
            evaluation["error_type"] = type(error).__name__
        report["evaluations"].append(evaluation)

    report["unmatched_input_count"] = sum(
        path.name.casefold() not in matched_names for path in inputs
    )
    report_path = Path(
        os.environ.get("MBS_RM024_REPORT_PATH", ".local/logs/rm-024-accuracy-report.json")
    ).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    for key in (
        "input_count",
        "expectation_count",
        "unmatched_input_count",
        "missing_input_count",
        "unreviewed_expectation_count",
        "checksum_missing_count",
        "accuracy_eligible_expectation_count",
    ):
        record_property(key, report[key])
    record_property("accuracy_claim", False)
