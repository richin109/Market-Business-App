from __future__ import annotations

import logging

from mbs.receipts.tasks import dispatch_pending_receipt_uploads

logger = logging.getLogger(__name__)


def request_outbox_dispatch() -> None:
    try:
        dispatch_pending_receipt_uploads.delay()
    except Exception:
        logger.warning("Receipt outbox dispatch request failed", exc_info=True)
