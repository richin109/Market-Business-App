from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbs.domain.media_assets import ALLOWED_IMAGE_TYPES, DISPLAY_MAX_SIDE, _sha256, _StagedFile
from mbs.infrastructure.images import _encode_derivative, _encode_thumbnail, sanitize_image
from mbs.models import AuditLog, MediaAsset, MediaAssetLink, ReceiptItem, ReceiptSource
from mbs.receipts.duplicates import PerceptualHasher, PillowPerceptualHasher
from mbs.receipts.pdf_extraction import EmbeddedPDFImage
from mbs.receipts.storage import ProtectedFileStore
from mbs.repositories.media_assets import MediaAssetRepository
from mbs.services.settings import read_setting

repository = MediaAssetRepository()


class MediaAssetService:
    def __init__(
        self,
        file_store: ProtectedFileStore,
        perceptual_hasher: PerceptualHasher | None = None,
    ) -> None:
        self._file_store = file_store
        self._perceptual_hasher = perceptual_hasher or PillowPerceptualHasher()

    def stage(
        self,
        session: Session,
        source: bytes,
        media_type: str,
        actor_id: int | None,
    ) -> MediaAsset:
        allowed_setting = read_setting(session, "image_allowed_media_types")
        configured_types = frozenset(
            value.strip() for value in (allowed_setting or "").split(",") if value.strip()
        )
        allowed_image_types = ALLOWED_IMAGE_TYPES & configured_types
        max_file_bytes = _read_positive_setting(session, "image_max_bytes")
        max_dimension_px = _read_positive_setting(session, "image_max_dimension_px")
        normalized, image, width, height = sanitize_image(
            source,
            media_type,
            allowed_image_types,
            max_file_bytes,
            max_dimension_px,
        )
        asset_sha256 = _sha256(normalized)
        existing = repository.get_asset(session, asset_sha256)
        if existing is not None:
            image.close()
            return existing

        perceptual_hash = self._perceptual_hasher.fingerprint(normalized, media_type)
        perceptual_match = repository.perceptual_match(session, perceptual_hash)
        if perceptual_match is not None:
            image.close()
            return perceptual_match

        staged_files: list[_StagedFile] = []
        try:
            display_bytes, display_type = _encode_derivative(image, DISPLAY_MAX_SIDE)
            thumbnail_bytes, thumbnail_type = _encode_thumbnail(image)
            variants = (
                (normalized, media_type),
                (display_bytes, display_type),
                (thumbnail_bytes, thumbnail_type),
            )
            for variant_bytes, variant_type in variants:
                digest = _sha256(variant_bytes)
                staging_key = self._file_store.stage(digest, variant_bytes, variant_type)
                staged_files.append(
                    _StagedFile(
                        source=variant_bytes,
                        media_type=variant_type,
                        sha256=digest,
                        staging_key=staging_key,
                        final_key=self._file_store.key_for(digest, variant_type),
                    )
                )

            asset = MediaAsset(
                asset_sha256=asset_sha256,
                original_media_type=media_type,
                original_file_key=staged_files[0].final_key,
                display_file_key=staged_files[1].final_key,
                display_media_type=display_type,
                thumbnail_file_key=staged_files[2].final_key,
                thumbnail_media_type=thumbnail_type,
                staging_files=[file.as_record() for file in staged_files],
                byte_size=len(normalized),
                width_px=width,
                height_px=height,
                display_size_bytes=len(display_bytes),
                thumbnail_size_bytes=len(thumbnail_bytes),
                perceptual_hash=perceptual_hash,
                scan_status="NOT_SCANNED",
                ingest_status="STAGED",
                created_by=actor_id,
            )
            try:
                with repository.savepoint(session):
                    repository.add(session, asset)
                    repository.add(
                        session,
                        AuditLog(
                            event_type="MEDIA_ASSET_IMAGE_NOT_SCANNED",
                            actor=str(actor_id) if actor_id is not None else None,
                            entity_type="MediaAsset",
                            entity_id=asset_sha256,
                            details="D-09/D-68 validated JPEG/PNG no-scan boundary",
                        ),
                    )
                    repository.flush(session)
            except IntegrityError:
                for file in staged_files:
                    self._file_store.delete(file.staging_key)
                concurrent_asset = repository.get_asset(session, asset_sha256)
                if concurrent_asset is None:
                    concurrent_asset = repository.perceptual_match(session, perceptual_hash)
                if concurrent_asset is None:
                    raise
                return concurrent_asset
            return asset
        except Exception:
            for file in staged_files:
                self._file_store.delete(file.staging_key)
            raise
        finally:
            image.close()

    def read_protected_file(self, file_key: str) -> bytes:
        return self._file_store.read(file_key)

    def promote(self, session: Session, asset_sha256: str) -> MediaAsset:
        asset = repository.get_asset(session, asset_sha256, lock=True)
        if asset is None:
            raise ValueError("Media asset not found")
        if asset.ingest_status == "READY":
            return asset
        if not isinstance(asset.staging_files, list):
            raise ValueError("Staged media asset has no staged files")
        for entry in asset.staging_files:
            if not isinstance(entry, dict):
                raise ValueError("Staged media file record is invalid")
            promoted_key = self._file_store.promote(
                str(entry["staging_key"]),
                str(entry["source_sha256"]),
                str(entry["media_type"]),
            )
            if promoted_key != entry["final_key"]:
                raise RuntimeError("Promoted media asset key did not match its database record")
        asset.staging_files = None
        asset.ingest_status = "READY"
        repository.flush(session)
        return asset

    @staticmethod
    def persist_pdf_image_candidates(
        session: Session,
        source: ReceiptSource,
        candidates: tuple[EmbeddedPDFImage, ...],
        receipt_items: list[ReceiptItem],
        file_store: ProtectedFileStore,
        actor_id: int | None,
    ) -> list[MediaAssetLink]:
        from mbs.services.receipt_image_ingest import persist_pdf_image_candidates

        return persist_pdf_image_candidates(
            session, source, candidates, receipt_items, file_store, actor_id
        )


def _read_positive_setting(session: Session, key: str) -> int:
    value = read_setting(session, key)
    try:
        parsed = int(value) if value is not None else 0
    except ValueError as error:
        raise ValueError(f"Image setting {key} must be a positive integer") from error
    if parsed <= 0:
        raise ValueError(f"Image setting {key} must be a positive integer")
    return parsed
