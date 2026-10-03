from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mbs.models import Receipt, ReceiptOutboxEvent, ReceiptSource, ReceiptUpload, Setting
from mbs.repositories.receipt_uploads import ReceiptUploadRepository
from mbs.repositories.settings import SettingsRepository


class ReceiptJobRepository(ReceiptUploadRepository):
    @contextmanager
    def transaction(self, factory: sessionmaker[Session]) -> Iterator[Session]:
        with factory.begin() as session:
            yield session

    @contextmanager
    def session(self, factory: sessionmaker[Session]) -> Iterator[Session]:
        with factory() as session:
            yield session

    def image_setting(self, session: Session, key: str) -> Setting | None:
        return SettingsRepository().get_setting(session, key)

    def receipt_identity(
        self, session: Session, receipt_id: str, *, lock: bool = False
    ) -> Receipt | None:
        query = select(Receipt).where(Receipt.receipt_id == receipt_id)
        return session.scalar(query.with_for_update() if lock else query)

    def source_id(self, session: Session, upload_pk: str, receipt_pk: str) -> int | None:
        return session.scalar(
            select(ReceiptSource.id).where(
                ReceiptSource.upload_pk == upload_pk,
                ReceiptSource.receipt_pk == receipt_pk,
            )
        )

    def source(self, session: Session, upload_pk: str, receipt_pk: str) -> ReceiptSource | None:
        return session.scalar(
            select(ReceiptSource).where(
                ReceiptSource.upload_pk == upload_pk,
                ReceiptSource.receipt_pk == receipt_pk,
            )
        )

    def pending_events(self, session: Session, now: datetime) -> list[ReceiptOutboxEvent]:
        return list(
            session.scalars(
                select(ReceiptOutboxEvent)
                .join(ReceiptUpload, ReceiptUpload.upload_pk == ReceiptOutboxEvent.upload_pk)
                .where(
                    or_(
                        ReceiptOutboxEvent.dispatched_at.is_(None),
                        and_(
                            ReceiptUpload.processing_status == "RUNNING",
                            or_(
                                ReceiptUpload.processing_lease_until.is_(None),
                                ReceiptUpload.processing_lease_until <= now,
                            ),
                        ),
                    )
                )
                .order_by(ReceiptOutboxEvent.id)
                .limit(50)
                .with_for_update(skip_locked=True)
            )
        )


def is_receipt_id_collision(error: IntegrityError) -> bool:
    constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if constraint_name == "uq_tbl_receipts_receipt_id":
        return True
    return "UNIQUE constraint failed: tbl_receipts.receipt_id" in str(error.orig)
