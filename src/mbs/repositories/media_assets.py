from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from mbs.models import MediaAsset, MediaAssetLink
from mbs.repositories.receipts import ReceiptRepository


class MediaAssetRepository(ReceiptRepository):
    def get_asset(
        self, session: Session, asset_sha256: str, *, lock: bool = False
    ) -> MediaAsset | None:
        if not lock:
            return session.get(MediaAsset, asset_sha256)
        return session.scalar(
            select(MediaAsset).where(MediaAsset.asset_sha256 == asset_sha256).with_for_update()
        )

    def perceptual_match(self, session: Session, perceptual_hash: str) -> MediaAsset | None:
        return session.scalar(
            select(MediaAsset).where(MediaAsset.perceptual_hash == perceptual_hash)
        )

    def candidate_key(self, session: Session, candidate_key: str) -> MediaAssetLink | None:
        return session.scalar(
            select(MediaAssetLink).where(
                MediaAssetLink.owner_kind == "RECEIPT_LINE_CANDIDATE",
                MediaAssetLink.owner_id == candidate_key,
            )
        )
