from __future__ import annotations

import re
from typing import Any

from mbs.domain.pdf_extraction import PDFTextExtraction
from mbs.domain.receipt_text import parse_receipt_text


def _multi_order_document(
    text: str,
    extraction: PDFTextExtraction,
    source_hint: str,
) -> dict[str, Any] | None:
    header_pattern = re.compile(r"(?im)^\s*(?:Amazon|Walmart|BJ'S WHOLESALE CLUB|SAM'S CLUB)\s*$")
    starts = [match.start() for match in header_pattern.finditer(text)]
    if len(starts) < 2:
        return None
    segments = [
        text[start : starts[index + 1] if index + 1 < len(starts) else len(text)].strip()
        for index, start in enumerate(starts)
    ]
    parsed_orders = [parse_receipt_text(segment, extraction, source_hint) for segment in segments]
    orders = [parsed.document for parsed in parsed_orders]
    identities = [order["receipt"].get("transaction_number") for order in orders]
    duplicate_identity = len(set(identity for identity in identities if identity)) != len(
        [identity for identity in identities if identity]
    )
    if duplicate_identity:
        for order in orders:
            order["review_required"] = True
            order["extraction"]["issues"] = [
                *order["extraction"].get("issues", []),
                "DUPLICATE_ORDER_IDENTITIES_IN_SOURCE",
            ]
    metadata = orders[0].get("metadata", {}) if orders else {}
    issue_codes = sorted(
        {
            issue
            for order in orders
            for issue in order.get("extraction", {}).get("issues", [])
            if isinstance(issue, str)
        }
    )
    return {
        "orders": orders,
        "metadata": metadata,
        "extraction": {
            "content_kind": extraction.classification.content_kind.value,
            "method": extraction.method.value,
            "order_count": len(orders),
            "issues": issue_codes,
            "pages": [
                {
                    "page_number": page.page_number,
                    "native_text_chars": len(page.native_text.strip()),
                    "ocr_confidence": (
                        str(page.ocr_confidence) if page.ocr_confidence is not None else None
                    ),
                    "selected_source": page.selected_source,
                }
                for page in extraction.pages
            ],
        },
        "review_required": any(order.get("review_required") is True for order in orders),
    }
