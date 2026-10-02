import json
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any

import pytest
from support.review_receipts import collect, draft, result_name


def test_draft_reads_date_from_printed_order_layout() -> None:
    text = "BJ's Wholesale Club\nOrder #1782  Item Price\nOrder Date  Qty : 1\n09/22/2026  Qty"

    assert draft(text) == {
        "store": "BJ's Wholesale Club",
        "date": "2026-09-22",
        "time": None,
        "transaction_number": "1782",
        "subtotal": None,
        "tax": None,
        "total": None,
        "payment_method": None,
        "items": [],
    }


def test_collect_includes_extensionless_pdf_and_keeps_review_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = tmp_path / "checkout"
    receipt.write_bytes(b"%PDF-1.4 synthetic")

    def extract(*args: Any, **kwargs: Any) -> CompletedProcess[str]:
        return CompletedProcess(args, 0, stdout="Order #42\n", stderr="")

    monkeypatch.setattr("support.review_receipts.subprocess.run", extract)
    monkeypatch.setattr("support.review_receipts.shutil.which", lambda _: "pdftotext.exe")
    existing: dict[str, object] = {
        "receipts": [{"file": "checkout", "expected": {"total": "8.25"}, "reviewed": True}]
    }

    assert collect(tmp_path, existing) == [
        {
            "file": "checkout",
            "result_file": result_name("checkout"),
            "expected": {"total": "8.25"},
            "reviewed": True,
            "extracted_text": "Order #42",
            "media_type": "application/pdf",
        }
    ]
    assert collect(tmp_path, existing, refresh=True)[0]["expected"] == {"total": "8.25"}


def test_result_names_distinguish_extensionless_and_pdf_variants() -> None:
    assert result_name("Order details - Walmart.com") != result_name(
        "Order details - Walmart.com.pdf"
    )


def test_collect_reloads_saved_result_for_matching_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "checkout.pdf").write_bytes(b"%PDF-1.4 synthetic")
    results = tmp_path / "expected"
    results.mkdir()
    (results / result_name("checkout.pdf")).write_text(
        json.dumps({"file": "checkout.pdf", "expected": {"total": "8.25"}, "reviewed": True}),
        encoding="utf-8",
    )
    monkeypatch.setattr("support.review_receipts.RESULTS", results)
    monkeypatch.setattr("support.review_receipts.shutil.which", lambda _: "pdftotext.exe")
    monkeypatch.setattr(
        "support.review_receipts.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args, 0, stdout="", stderr=""),
    )

    entry = collect(tmp_path, {"receipts": []})[0]

    assert entry["expected"] == {"total": "8.25"}
    assert entry["reviewed"] is True


def test_collect_fills_unreviewed_missing_fields_without_overwriting_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "print.pdf").write_bytes(b"%PDF-1.4 synthetic")

    def extract(*args: Any, **kwargs: Any) -> CompletedProcess[str]:
        return CompletedProcess(
            args, 0, stdout="BJ's Wholesale Club\nOrder #42\nOrder Date Qty\n09/22/2026", stderr=""
        )

    monkeypatch.setattr("support.review_receipts.subprocess.run", extract)
    monkeypatch.setattr("support.review_receipts.shutil.which", lambda _: "pdftotext.exe")
    existing: dict[str, object] = {
        "receipts": [
            {
                "file": "print.pdf",
                "expected": {"store": "Verified Store", "date": None, "items": []},
                "reviewed": False,
            }
        ]
    }

    entry = collect(tmp_path, existing)[0]
    expected = entry["expected"]
    assert isinstance(expected, dict)

    assert expected["store"] == "Verified Store"
    assert expected["date"] == "2026-09-22"
    assert expected["transaction_number"] == "42"


def test_draft_pairs_bj_items_and_reconciles_summary() -> None:
    raw_text = (
        "Qty (Weight) : 1.04\nQty\nTotal Price : $8.31\nD&W CHEESE\nItem: 988551\n"
        "Qty (Weight) :\nQty\nTotal Price : $3.69\nPage footer\n"
        "Page header\nNATKETOBRD\nItem: 322283\n"
        "$12.00\n$0.00\n$0.00\n$12.00\n$0.50\nOrder Summary\n"
    )

    result = draft("BJ's Wholesale Club\nOrder #1782", raw_text)

    assert result["items"] == [
        {
            "description": "D&W CHEESE",
            "item_number": "988551",
            "size": None,
            "quantity": "1.04",
            "line_total": "8.31",
        },
        {
            "description": "NATKETOBRD",
            "item_number": "322283",
            "size": None,
            "quantity": None,
            "line_total": "3.69",
        },
    ]
    assert (result["subtotal"], result["tax"], result["total"]) == ("12.00", "0.00", "12.00")


def test_draft_keeps_same_description_rows_distinct_by_item_number() -> None:
    raw_text = (
        "Qty (Weight) : 1\nQty\nTotal Price : $7.49\nBLUBERRY 18Z\nItem: 14153\n"
        "Qty (Weight) : 1\nQty\nTotal Price : $7.49\nBLUBERRY 18Z\nItem: 99999\n"
    )

    items = draft("BJ's Wholesale Club", raw_text)["items"]

    assert items == [
        {
            "description": "BLUBERRY 18Z",
            "item_number": "14153",
            "size": "18Z",
            "quantity": "1",
            "line_total": "7.49",
        },
        {
            "description": "BLUBERRY 18Z",
            "item_number": "99999",
            "size": "18Z",
            "quantity": "1",
            "line_total": "7.49",
        },
    ]
