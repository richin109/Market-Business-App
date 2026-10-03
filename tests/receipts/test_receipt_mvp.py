from __future__ import annotations

from pathlib import Path

import pytest
from tests import test_receipt_pdf_extraction as pdf_extraction_tests
from tests import test_receipt_pipeline_wiring as pipeline_tests


def test_rm_023() -> None:
    pdf_extraction_tests.test_structured_parser_returns_distinct_receipt_fields_and_review_confidence()
    pdf_extraction_tests.test_walmart_image_page_parses_rows_taxes_and_holds_ambiguous_references()
    pdf_extraction_tests.test_rm_023_image_pdf_keeps_merchant_id_upc_weight_and_header_evidence_distinct()
    pdf_extraction_tests.test_rm_023_real_ocr_holds_incomplete_image_only_item_evidence()


def test_rm_025(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_extraction_tests.test_rm_025_image_only_order_sheet_segments_five_ten_and_fifteen_orders()
    pipeline_tests.test_concurrent_batch_retries_create_one_upload_and_outbox_event(
        tmp_path, monkeypatch
    )
    pipeline_tests.test_worker_processes_changed_single_image_versions_without_duplicate_receipts(
        tmp_path
    )
    pipeline_tests.test_batch_endpoint_processes_changed_multi_order_image_versions_idempotently(
        tmp_path, monkeypatch
    )
    pipeline_tests.test_batch_status_reports_partial_order_holds_without_losing_valid_orders(
        tmp_path, monkeypatch
    )
    pipeline_tests.test_duplicate_delivery_respects_active_worker_lease(tmp_path)
    pipeline_tests.test_superseded_worker_lease_cannot_commit_stale_ocr_result(tmp_path)
