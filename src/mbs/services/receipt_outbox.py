from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from mbs.receipts.storage import LocalProtectedFileStore
from mbs.repositories.receipt_jobs import ReceiptJobRepository

repository = ReceiptJobRepository()


def dispatch_pending_uploads(
    session_factory: sessionmaker[Session],
    file_store: LocalProtectedFileStore,
    publish: Callable[[str], object],
) -> int:
    dispatched = 0
    now = datetime.now(UTC)
    with repository.transaction(session_factory) as session:
        events = repository.pending_events(session, now)
        for event in events:
            if event.dispatched_at is not None:
                event.dispatched_at = None
                event.last_error = "Worker lease expired; redispatching upload"
            event.dispatch_attempts += 1
            try:
                upload = repository.get_upload(session, event.upload_pk)
                if upload is None:
                    event.last_error = "Receipt upload not found"
                    continue
                if upload.staging_file_key is not None:
                    promoted_key = file_store.promote(
                        upload.staging_file_key,
                        upload.source_sha256,
                        upload.media_type,
                    )
                    if promoted_key != upload.file_key:
                        raise RuntimeError(
                            "Promoted receipt file key did not match its upload record"
                        )
                    upload.staging_file_key = None
                publish(event.upload_pk)
            except Exception as error:
                event.last_error = str(error)[:1000]
                continue
            event.dispatched_at = datetime.now(UTC)
            event.last_error = None
            dispatched += 1
    return dispatched
