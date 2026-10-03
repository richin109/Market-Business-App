from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs.models import ReceiptUpload
from mbs.repositories.receipts import ReceiptRepository


class ReceiptUploadRepository(ReceiptRepository):
    def accepted_fingerprints(self, session: Session) -> list[tuple[str, str | None]]:
        return [
            (source_hash, fingerprint)
            for source_hash, fingerprint in session.execute(
                select(ReceiptUpload.source_sha256, ReceiptUpload.perceptual_hash).where(
                    ReceiptUpload.perceptual_hash.is_not(None),
                    ReceiptUpload.duplicate_status.is_distinct_from("POSSIBLE_DUPLICATE"),
                    ReceiptUpload.duplicate_status.is_distinct_from("CONFIRMED_DUPLICATE"),
                )
            )
        ]

    def source_hash(self, session: Session, source_sha256: str) -> ReceiptUpload | None:
        return session.scalar(
            select(ReceiptUpload).where(ReceiptUpload.source_sha256 == source_sha256)
        )

    def upload_for_update(self, session: Session, upload_pk: str) -> ReceiptUpload | None:
        return session.scalar(
            select(ReceiptUpload).where(ReceiptUpload.upload_pk == upload_pk).with_for_update()
        )

    def get_upload(self, session: Session, upload_pk: str) -> ReceiptUpload | None:
        return session.get(ReceiptUpload, upload_pk)
