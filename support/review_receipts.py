"""Build a local, private receipt review page and expected-results manifest."""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

RECEIPTS = Path(__file__).resolve().parents[1] / "receipts"
TEMPLATE = Path(__file__).with_name("receipt_review.html")
MANIFEST = RECEIPTS / "expected-results.json"
REVIEW = RECEIPTS / "review.html"
RESULTS = RECEIPTS / "expected"


def result_name(filename: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", filename.lower()).strip("-")[:48]
    digest = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:10]
    return f"{slug}-{digest}.expected.json"


def draft(text: str, raw_text: str = "") -> dict[str, object]:
    order = re.search(r"\bOrder #\s*(\d+)\b", text)
    date = re.search(r"\bOrder Date[^\n]*\n\s*(\d{2}/\d{2}/\d{4})\b", text)
    prices = list(
        re.finditer(
            r"Qty \(Weight\) :\s*([\d.]*)\s+Qty\s+Total Price : \$([\d,]+\.\d{2})",
            raw_text,
        )
    )
    items = []
    for position, price in enumerate(prices):
        end = prices[position + 1].start() if position + 1 < len(prices) else len(raw_text)
        match = re.search(r"\n([^\n]+)\nItem: (\d+)", raw_text[price.end() : end])
        description = match[1].strip() if match else ""
        size = re.search(r"(?:^|\s)(\d+(?:\.\d+)?(?:OZ|Z))$", description, re.I)
        items.append(
            {
                "description": description,
                "item_number": match[2] if match else None,
                "size": size[1] if size else None,
                "quantity": price[1] or None,
                "line_total": price[2].replace(",", ""),
            }
        )
    summary = re.search(r"((?:^\$[\d,]+\.\d{2}\n){4,5})Order Summary", raw_text, re.M)
    subtotal = tax = total = None
    if summary:
        amounts = [
            Decimal(value.replace(",", ""))
            for value in re.findall(r"\$([\d,]+\.\d{2})", summary[1])
        ]
        if amounts[0] + amounts[1] + amounts[2] == amounts[3]:
            subtotal, tax, total = (str(amounts[0]), str(amounts[1]), str(amounts[3]))
    return {
        "store": (
            "BJ's Wholesale Club"
            if "BJ's Wholesale Club" in text
            else "Walmart"
            if "Walmart.com" in text
            else None
        ),
        "date": datetime.strptime(date[1], "%m/%d/%Y").date().isoformat() if date else None,
        "time": None,
        "transaction_number": order[1] if order else None,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "payment_method": None,
        "items": items,
    }


def collect(
    receipts: Path, previous: dict[str, object], refresh: bool = False
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    executable = shutil.which("pdftotext")
    old_entries = {
        entry["file"]: entry for entry in cast(list[dict[str, Any]], previous.get("receipts", []))
    }
    for path in sorted(receipts.iterdir()):
        if not path.is_file():
            continue
        is_pdf = path.open("rb").read(5) == b"%PDF-"
        if not is_pdf and path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            continue
        if is_pdf:
            if executable is None:
                raise RuntimeError("pdftotext is required to process PDF receipts")
            result = subprocess.run(
                [executable, "-layout", str(path), "-"],
                capture_output=True,
                check=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            text = result.stdout.strip()
            raw_text = subprocess.run(
                [executable, "-raw", str(path), "-"],
                capture_output=True,
                check=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).stdout
        else:
            text = ""
            raw_text = ""
        saved_path = RESULTS / result_name(path.name)
        existing = (
            json.loads(saved_path.read_text(encoding="utf-8"))
            if saved_path.exists()
            else old_entries.get(path.name, {})
        )
        if existing.get("file", path.name) != path.name:
            raise ValueError(f"Saved result does not match receipt: {saved_path}")
        parsed = draft(text, raw_text)
        expected = (
            parsed
            if refresh and not existing.get("reviewed", False)
            else existing.get("expected", parsed)
        ).copy()
        if not existing.get("reviewed", False):
            for field, value in parsed.items():
                if (
                    expected.get(field) is None or (field == "items" and not expected[field])
                ) and value:
                    expected[field] = value
        if isinstance(expected.get("items"), list):
            items = [item.copy() for item in cast(list[dict[str, Any]], expected["items"])]
            expected["items"] = items
            source_items = cast(list[dict[str, Any]], parsed["items"])
            for item, source in zip(items, source_items, strict=False):
                if all(
                    item.get(field) == source[field]
                    for field in ("description", "quantity", "line_total")
                ):
                    for field in ("item_number", "size"):
                        item.setdefault(field, source[field])
        entries.append(
            {
                "file": path.name,
                "result_file": saved_path.name,
                "expected": expected,
                "reviewed": existing.get("reviewed", False),
                "extracted_text": text,
                "media_type": "application/pdf"
                if is_pdf
                else ("image/png" if path.suffix.lower() == ".png" else "image/jpeg"),
            }
        )
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Replace unreviewed drafts")
    args = parser.parse_args()
    RESULTS.mkdir(exist_ok=True)
    previous = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    entries = collect(RECEIPTS, previous, refresh=args.refresh)
    MANIFEST.write_text(
        json.dumps(
            {
                "receipts": [
                    {key: entry[key] for key in ("file", "expected", "reviewed")}
                    for entry in entries
                ]
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    data = json.dumps(entries, ensure_ascii=False).replace("<", "\\u003c")
    REVIEW.write_text(
        TEMPLATE.read_text(encoding="utf-8").replace("__RECEIPTS__", data), encoding="utf-8"
    )
    print(f"Prepared {len(entries)} receipts: {REVIEW}")


if __name__ == "__main__":
    main()
