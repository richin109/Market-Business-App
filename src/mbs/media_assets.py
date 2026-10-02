from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbs.models import (
    AuditLog,
    MediaAsset,
    MediaAssetLink,
    ReceiptItem,
    ReceiptSource,
)
from mbs.receipts.duplicates import PerceptualHasher, PillowPerceptualHasher
from mbs.receipts.pdf_extraction import EmbeddedPDFImage
from mbs.receipts.storage import ProtectedFileStore
from mbs.settings import read_setting

ALLOWED_IMAGE_TYPES = frozenset({"image/jpeg", "image/png"})
THUMBNAIL_MAX_SIDE = 320
DISPLAY_MAX_SIDE = 1_024
THUMBNAIL_TARGET_BYTES = 40_000

_SIGNATURES = {"image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG\r\n\x1a\n"}


@dataclass(frozen=True)
class _StagedFile:
    source: bytes
    media_type: str
    sha256: str
    staging_key: str
    final_key: str

    def as_record(self) -> dict[str, str]:
        return {
            "source_sha256": self.sha256,
            "media_type": self.media_type,
            "staging_key": self.staging_key,
            "final_key": self.final_key,
        }


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
        normalized, image, width, height = self._sanitize(
            source,
            media_type,
            allowed_image_types,
            max_file_bytes,
            max_dimension_px,
        )
        asset_sha256 = _sha256(normalized)
        existing = session.get(MediaAsset, asset_sha256)
        if existing is not None:
            image.close()
            return existing

        perceptual_hash = self._perceptual_hasher.fingerprint(normalized, media_type)
        perceptual_match = session.scalar(
            select(MediaAsset).where(MediaAsset.perceptual_hash == perceptual_hash)
        )
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
                with session.begin_nested():
                    session.add(asset)
                    session.add(
                        AuditLog(
                            event_type="MEDIA_ASSET_IMAGE_NOT_SCANNED",
                            actor=str(actor_id) if actor_id is not None else None,
                            entity_type="MediaAsset",
                            entity_id=asset_sha256,
                            details="D-09/D-68 validated JPEG/PNG no-scan boundary",
                        )
                    )
                    session.flush()
            except IntegrityError:
                for file in staged_files:
                    self._file_store.delete(file.staging_key)
                concurrent_asset = session.get(MediaAsset, asset_sha256)
                if concurrent_asset is None:
                    concurrent_asset = session.scalar(
                        select(MediaAsset).where(MediaAsset.perceptual_hash == perceptual_hash)
                    )
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
        asset = session.scalar(
            select(MediaAsset).where(MediaAsset.asset_sha256 == asset_sha256).with_for_update()
        )
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
        session.flush()
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
        service = MediaAssetService(file_store)
        created: list[MediaAssetLink] = []
        for candidate in candidates:
            content_sha256 = _sha256(candidate.image_bytes)
            region_key = ":".join(f"{coordinate:.4f}" for coordinate in candidate.region)
            candidate_key = _sha256(
                f"{source.source_sha256}:{candidate.page_number}:{region_key}:{content_sha256}".encode()
            )
            existing_candidate = session.scalar(
                select(MediaAssetLink).where(
                    MediaAssetLink.owner_kind == "RECEIPT_LINE_CANDIDATE",
                    MediaAssetLink.owner_id == candidate_key,
                )
            )
            if existing_candidate is not None:
                continue

            try:
                asset = service.stage(
                    session,
                    candidate.image_bytes,
                    candidate.media_type,
                    actor_id,
                )
            except ValueError:
                session.add(
                    AuditLog(
                        event_type="RECEIPT_IMAGE_CANDIDATE_INGEST_REJECTED",
                        actor=str(actor_id) if actor_id is not None else None,
                        entity_type="ReceiptSource",
                        entity_id=str(source.id),
                        details=(
                            f"source_id={source.id}; page={candidate.page_number}; "
                            "issue=INVALID_IMAGE_CONTENT"
                        ),
                    )
                )
                continue
            service.promote(session, asset.asset_sha256)
            line = (
                receipt_items[candidate.item_index]
                if candidate.item_index is not None
                and 0 <= candidate.item_index < len(receipt_items)
                else None
            )
            link = MediaAssetLink(
                asset_sha256=asset.asset_sha256,
                owner_kind="RECEIPT_LINE_CANDIDATE",
                owner_id=candidate_key,
                status="PENDING",
                source_id=source.id,
                receipt_item_id=line.id if line is not None else None,
                source_page=candidate.page_number,
                source_region={
                    "bbox": list(candidate.region),
                    "page_width": candidate.page_width,
                    "page_height": candidate.page_height,
                    "pixel_width": candidate.pixel_width,
                    "pixel_height": candidate.pixel_height,
                    "item_index": candidate.item_index,
                },
                created_by=actor_id,
            )
            try:
                with session.begin_nested():
                    session.add(link)
                    session.add(
                        AuditLog(
                            event_type="RECEIPT_IMAGE_CANDIDATE_CREATED",
                            actor=str(actor_id) if actor_id is not None else None,
                            entity_type="MediaAssetLink",
                            entity_id=candidate_key,
                            details=(
                                f"source_id={source.id}; page={candidate.page_number}; "
                                f"line={line.id if line is not None else 'unassigned'}"
                            ),
                        )
                    )
                    session.flush()
            except IntegrityError:
                concurrent_candidate = session.scalar(
                    select(MediaAssetLink).where(
                        MediaAssetLink.owner_kind == "RECEIPT_LINE_CANDIDATE",
                        MediaAssetLink.owner_id == candidate_key,
                    )
                )
                if concurrent_candidate is None:
                    raise
                continue
            created.append(link)
        return created

    def _sanitize(
        self,
        source: bytes,
        media_type: str,
        allowed_image_types: frozenset[str],
        max_file_bytes: int,
        max_dimension_px: int,
    ) -> tuple[bytes, Image.Image, int, int]:
        if media_type not in allowed_image_types:
            raise ValueError(f"Unsupported image media type: {media_type}")
        if not source or len(source) > max_file_bytes:
            raise ValueError("Image is empty or exceeds the configured size limit")
        if not source.startswith(_SIGNATURES[media_type]):
            raise ValueError("Image signature does not match its media type")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(source)) as probe:
                    probe.verify()
                with Image.open(BytesIO(source)) as opened:
                    oriented = ImageOps.exif_transpose(opened)
                    normalized_image = _normalized_mode(oriented, media_type)
        except (
            OSError,
            UnidentifiedImageError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as error:
            raise ValueError("Image is invalid or exceeds Pillow's safety limits") from error
        if max(normalized_image.size) > max_dimension_px:
            normalized_image.close()
            raise ValueError("Image dimensions exceed the configured limit")
        output = BytesIO()
        image_format = "JPEG" if media_type == "image/jpeg" else "PNG"
        normalized_image.save(output, format=image_format, optimize=True)
        clean_bytes = output.getvalue()
        if len(clean_bytes) > max_file_bytes:
            normalized_image.close()
            raise ValueError("Sanitized image exceeds the configured size limit")
        return clean_bytes, normalized_image, normalized_image.width, normalized_image.height


def _read_positive_setting(session: Session, key: str) -> int:
    value = read_setting(session, key)
    try:
        parsed = int(value) if value is not None else 0
    except ValueError as error:
        raise ValueError(f"Image setting {key} must be a positive integer") from error
    if parsed <= 0:
        raise ValueError(f"Image setting {key} must be a positive integer")
    return parsed


def _normalized_mode(image: Image.Image, media_type: str) -> Image.Image:
    if media_type == "image/jpeg":
        return image.convert("RGB")
    if "A" in image.getbands():
        return image.convert("RGBA")
    return image.convert("RGB")


def _encode_derivative(image: Image.Image, max_side: int) -> tuple[bytes, str]:
    resized = _resize_without_upscale(image, max_side)
    buffer = BytesIO()
    try:
        resized.save(buffer, format="WEBP", quality=80, method=6)
        return buffer.getvalue(), "image/webp"
    except (OSError, ValueError):
        return _encode_jpeg(resized), "image/jpeg"
    finally:
        if resized is not image:
            resized.close()


def _encode_thumbnail(image: Image.Image) -> tuple[bytes, str]:
    last_result = b""
    last_media_type = "image/webp"
    for max_side in (320, 256, 192, 128, 96, 64, 32, 16, 8, 4, 2, 1):
        resized = _resize_without_upscale(image, max_side)
        try:
            for quality in (80, 70, 60, 50, 40):
                buffer = BytesIO()
                try:
                    resized.save(buffer, format="WEBP", quality=quality, method=6)
                    result, media_type = buffer.getvalue(), "image/webp"
                except (OSError, ValueError):
                    result, media_type = _encode_jpeg(resized, quality), "image/jpeg"
                last_result, last_media_type = result, media_type
                if len(result) <= THUMBNAIL_TARGET_BYTES:
                    return result, media_type
        finally:
            if resized is not image:
                resized.close()
    return last_result, last_media_type


def _resize_without_upscale(image: Image.Image, max_side: int) -> Image.Image:
    longest_side = max(image.size)
    if longest_side <= max_side:
        return image.copy()
    ratio = max_side / longest_side
    dimensions = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    return image.resize(dimensions, Image.Resampling.LANCZOS)


def _encode_jpeg(image: Image.Image, quality: int = 80) -> bytes:
    if image.mode in {"RGBA", "LA"}:
        background = Image.new("RGB", image.size, "white")
        alpha = image.getchannel("A")
        background.paste(image.convert("RGB"), mask=alpha)
        image = background
    else:
        image = image.convert("RGB")
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def _sha256(source: bytes) -> str:
    return hashlib.sha256(source).hexdigest()
