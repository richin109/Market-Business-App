from __future__ import annotations

from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from mbs.domain.receipt_normalization import BusinessDisposition
from mbs.domain.remembered_rules import RememberedItemRule, RuleMatchKind, find_item_rule
from mbs.domain.units import UNIT_ALIASES
from mbs.errors import NotFoundError
from mbs.repositories.receipt_reads import ReceiptReadRepository
from mbs.services.receipt_reads import _store_items_for_lines
from mbs.services.receipt_sources import repeated_source_line_indexes

repository = ReceiptReadRepository()


def receipt_review_context(session: Session, receipt_pk: str) -> dict[str, object]:
    receipt = repository.get_receipt(session, receipt_pk, active_only=True)
    if receipt is None:
        raise NotFoundError("Receipt not found")
    raw_extraction = receipt.raw_ocr_document.get("extraction")
    raw_header = receipt.raw_ocr_document.get("receipt")
    extraction_evidence = {
        "field_candidates": (
            raw_extraction.get("field_candidates", {}) if isinstance(raw_extraction, dict) else {}
        ),
        "issues": raw_extraction.get("issues", []) if isinstance(raw_extraction, dict) else [],
        "references": (
            raw_header.get("reference_candidates", {}) if isinstance(raw_header, dict) else {}
        ),
        "card_last_four": (
            raw_header.get("card_last_four") if isinstance(raw_header, dict) else None
        ),
    }
    raw_confidences = (
        raw_extraction.get("field_confidence") if isinstance(raw_extraction, dict) else None
    )
    low_confidence_fields: set[str] = set()
    if isinstance(raw_confidences, dict):
        for field, value in raw_confidences.items():
            try:
                if Decimal(str(value)) < Decimal("0.62"):
                    low_confidence_fields.add(str(field))
            except (InvalidOperation, ValueError):
                continue
    raw_missing_fields = (
        raw_extraction.get("missing_fields") if isinstance(raw_extraction, dict) else None
    )
    missing_fields = (
        {field for field in raw_missing_fields if isinstance(field, str)}
        if isinstance(raw_missing_fields, list)
        else set()
    )
    attention_fields = low_confidence_fields | missing_fields
    lines = repository.lines(session, receipt_pk)
    store_items = _store_items_for_lines(session, lines)
    item_ids = {line.item_id for line in lines if line.item_id is not None}
    canonical_items = {item.item_id: item for item in repository.canonical_items(session, item_ids)}
    line_ids = [line.id for line in lines]
    approvals = {
        approval.receipt_item_id: approval
        for approval in repository.approval_versions(session, line_ids)
    }
    source_rows = repository.source_uploads(session, receipt_pk)
    source_views: list[dict[str, object]] = []
    for source, upload in source_rows:
        source_items = source.extracted_document.get("items")
        repeated_indexes = (
            repeated_source_line_indexes(lines, source_items, store_items)
            if source.association_kind == "PENDING"
            else ()
        )
        repeated_lines: list[dict[str, object]] = []
        if isinstance(source_items, list):
            for source_line_index in repeated_indexes:
                candidate = source_items[source_line_index]
                if isinstance(candidate, dict):
                    repeated_lines.append(
                        {
                            "index": source_line_index,
                            "description": candidate.get("description", "Unlabelled line"),
                            "store_product_id": candidate.get("store_product_id"),
                            "upc": candidate.get("upc"),
                            "source_page": candidate.get("source_page") or 1,
                            "source_line_number": candidate.get("source_line_number")
                            or source_line_index + 1,
                        }
                    )
        source_views.append(
            {
                "id": source.id,
                "kind": source.association_kind,
                "media_type": upload.media_type,
                "page_count": max(upload.page_count or 1, 1),
                "content_url": (f"/api/v1/receipts/{receipt_pk}/sources/{source.id}/content"),
                "repeated_lines": repeated_lines,
            }
        )
    candidates_by_line: dict[int, list[dict[str, object]]] = {}
    unassigned_image_candidates: list[dict[str, object]] = []
    source_ids = [source.id for source, _ in source_rows]
    if source_ids:
        candidate_rows = repository.source_candidates(session, source_ids)
        for candidate, _asset in candidate_rows:
            candidate_view: dict[str, object] = {
                "id": candidate.id,
                "source_id": candidate.source_id,
                "status": candidate.status,
                "reason": candidate.rejection_reason,
                "page": candidate.source_page,
                "region": candidate.source_region,
                "thumbnail_url": (
                    f"/api/v1/receipts/{receipt_pk}/image-candidates/{candidate.id}/thumbnail"
                ),
            }
            if candidate.receipt_item_id in line_ids:
                candidates_by_line.setdefault(candidate.receipt_item_id, []).append(candidate_view)
            else:
                unassigned_image_candidates.append(candidate_view)
    review_lines: list[dict[str, object]] = []
    remembered_items = {
        remembered.store_item_id: remembered
        for remembered in repository.remembered_items(session, receipt.store_id)
        if remembered.last_disposition is not None
    }
    remembered_rules = tuple(
        RememberedItemRule(
            store_item_id=remembered.store_item_id,
            vendor=receipt.store,
            description=remembered.latest_description,
            disposition=BusinessDisposition(remembered.last_disposition),
            upc=remembered.upc,
        )
        for remembered in remembered_items.values()
        if remembered.last_disposition is not None
    )
    raw_item_candidates = (
        raw_extraction.get("item_candidates", {}) if isinstance(raw_extraction, dict) else {}
    )
    native_item_candidates = (
        raw_item_candidates.get("native", []) if isinstance(raw_item_candidates, dict) else []
    )
    ocr_item_candidates = (
        raw_item_candidates.get("ocr", []) if isinstance(raw_item_candidates, dict) else []
    )
    for line_index, line in enumerate(lines):
        raw_item = line.raw_ocr_item if isinstance(line.raw_ocr_item, dict) else {}
        native_item = (
            native_item_candidates[line_index]
            if isinstance(native_item_candidates, list)
            and line_index < len(native_item_candidates)
            and isinstance(native_item_candidates[line_index], dict)
            else {}
        )
        ocr_item = (
            ocr_item_candidates[line_index]
            if isinstance(ocr_item_candidates, list)
            and line_index < len(ocr_item_candidates)
            and isinstance(ocr_item_candidates[line_index], dict)
            else {}
        )
        store_item = store_items.get(line.store_item_id) if line.store_item_id is not None else None
        canonical_item = canonical_items.get(line.item_id) if line.item_id is not None else None
        approval = approvals.get(line.id)
        primary = line.business_disposition
        subtype = line.disposition_subtype
        rule_suggestion: str | None = None
        if primary == BusinessDisposition.UNCLASSIFIED.value and store_item is not None:
            primary = store_item.last_disposition or primary
            subtype = store_item.last_disposition_subtype or "NONE"
        if (
            primary == BusinessDisposition.UNCLASSIFIED.value
            and approval is None
            and not line.is_excluded
        ):
            rule_match = find_item_rule(
                remembered_rules, receipt.store, line.description, line.upc, line.store_item_id
            )
            if rule_match is not None:
                labels = sorted({rule.disposition.value for rule in rule_match.candidates})
                upc_rule = (
                    rule_match.rule
                    if rule_match.kind is RuleMatchKind.EXACT
                    and rule_match.rule is not None
                    and line.upc is not None
                    and rule_match.rule.upc == line.upc
                    else None
                )
                if upc_rule is not None:
                    remembered_item = remembered_items[upc_rule.store_item_id]
                    primary = upc_rule.disposition.value
                    subtype = remembered_item.last_disposition_subtype or "NONE"
                prefix = (
                    "Matches a remembered item: "
                    if rule_match.kind is RuleMatchKind.EXACT
                    else "Ambiguous remembered matches: "
                )
                rule_suggestion = prefix + ", ".join(
                    label.replace("_", " ").title() for label in labels
                )
        review_lines.append(
            {
                "id": line.id,
                "description": line.description,
                "extraction_evidence": {
                    "merchant_item_number": raw_item.get("store_product_id")
                    or raw_item.get("identifier_candidate"),
                    "upc": raw_item.get("upc"),
                    "printed_size": raw_item.get("printed_size"),
                    "quantity": raw_item.get("quantity"),
                    "weight_lb": raw_item.get("weight_lb"),
                    "raw_line_text": raw_item.get("raw_line_text"),
                    "native_candidate": native_item,
                    "ocr_candidate": ocr_item,
                },
                "image_candidates": candidates_by_line.get(line.id, []),
                "rule_suggestion": rule_suggestion,
                "display_name": (
                    (store_item.common_name if store_item is not None else None)
                    or (canonical_item.common_name if canonical_item is not None else None)
                    or line.description
                ),
                "store_product_id": (
                    store_item.store_product_id if store_item is not None else None
                ),
                "identifier_source": (
                    store_item.identifier_source if store_item is not None else None
                ),
                "mapping_confirmed": (
                    store_item.mapping_confirmed if store_item is not None else False
                ),
                "category": line.category,
                "quantity": str(line.quantity) if line.quantity is not None else None,
                "weight_lb": str(line.weight_lb) if line.weight_lb is not None else None,
                "package_count": (
                    str(line.package_count) if line.package_count is not None else None
                ),
                "pack_size": str(line.pack_size) if line.pack_size is not None else None,
                "pack_unit": line.pack_unit,
                "remembered_pack_size": (
                    str(store_item.remembered_pack_size)
                    if store_item is not None and store_item.remembered_pack_size is not None
                    else None
                ),
                "remembered_pack_unit": (
                    store_item.remembered_pack_unit if store_item is not None else None
                ),
                "package_suggestion": (
                    line.pack_size is None
                    and store_item is not None
                    and store_item.remembered_pack_size is not None
                    and store_item.remembered_pack_unit is not None
                ),
                "has_store_item": store_item is not None,
                "store_item_id": line.store_item_id,
                "package_review_warning": (
                    line.package_count is None or line.pack_size is None or line.pack_unit is None
                ),
                "low_confidence": (
                    "items" in low_confidence_fields
                    or (line.ocr_confidence is not None and line.ocr_confidence < Decimal("0.62"))
                ),
                "upc": line.upc,
                "unit_price": str(line.unit_price) if line.unit_price is not None else None,
                "line_total": str(line.line_total),
                "is_excluded": line.is_excluded,
                "exclusion_reason": line.exclusion_reason,
                "business_disposition": primary,
                "disposition_subtype": subtype,
                "approved": approval is not None,
                "posting_status": approval.posting_status if approval is not None else None,
                "posting_kind": approval.posting_kind if approval is not None else None,
            }
        )
    return {
        "receipt": receipt,
        "lines": review_lines,
        "sources": source_views,
        "unassigned_image_candidates": unassigned_image_candidates,
        "dispositions": [item.value for item in BusinessDisposition],
        "corrections_locked": bool(approvals),
        "unit_aliases": UNIT_ALIASES,
        "attention_fields": attention_fields,
        "extraction_evidence": extraction_evidence,
        "total_mismatch": receipt.receipt_document.get("total_mismatch") is True,
        "can_add_line": receipt.source_type == "MANUAL"
        or any(source["kind"] in {"PRIMARY", "SUPPLEMENT"} for source in source_views),
    }
