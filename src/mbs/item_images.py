from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbs.errors import NotFoundError
from mbs.media_assets import MediaAssetService
from mbs.models import AuditLog, Item, MediaAsset, MediaAssetLink, Setting, StoreItem
from mbs.settings import read_setting

ImageOwnerKind = Literal["ITEM", "STORE_ITEM"]


class ItemImageGalleryRepository:
    def get_owner(
        self,
        session: Session,
        owner_kind: ImageOwnerKind,
        owner_id: str,
        *,
        lock: bool = False,
    ) -> Item | StoreItem:
        if owner_kind == "ITEM":
            query = select(Item).where(Item.item_id == owner_id)
            owner = session.scalar(query.with_for_update() if lock else query)
            if owner is None or not owner.is_active:
                raise NotFoundError("Image owner not found")
            return owner
        query = select(StoreItem).where(StoreItem.store_item_id == owner_id)
        owner = session.scalar(query.with_for_update() if lock else query)
        if owner is None:
            raise NotFoundError("Image owner not found")
        return owner

    def list_active_images(
        self, session: Session, owner_kind: ImageOwnerKind, owner_id: str
    ) -> list[tuple[MediaAssetLink, MediaAsset]]:
        return list(
            session.execute(
                select(MediaAssetLink, MediaAsset)
                .join(MediaAsset, MediaAsset.asset_sha256 == MediaAssetLink.asset_sha256)
                .where(
                    MediaAssetLink.owner_kind == owner_kind,
                    MediaAssetLink.owner_id == owner_id,
                    MediaAssetLink.status == "CONFIRMED",
                    MediaAssetLink.detached_at.is_(None),
                )
                .order_by(MediaAssetLink.sort_order, MediaAssetLink.id)
            ).all()
        )

    def get_primary(
        self,
        session: Session,
        owner_kind: ImageOwnerKind,
        owner_id: str,
        *,
        lock: bool = False,
    ) -> MediaAssetLink | None:
        query = select(MediaAssetLink).where(
            MediaAssetLink.owner_kind == owner_kind,
            MediaAssetLink.owner_id == owner_id,
            MediaAssetLink.status == "CONFIRMED",
            MediaAssetLink.is_primary.is_(True),
            MediaAssetLink.detached_at.is_(None),
        )
        return session.scalar(query.with_for_update() if lock else query)

    def get_link(
        self,
        session: Session,
        owner_kind: ImageOwnerKind,
        owner_id: str,
        link_id: int,
        *,
        lock: bool = False,
    ) -> MediaAssetLink | None:
        query = select(MediaAssetLink).where(
            MediaAssetLink.id == link_id,
            MediaAssetLink.owner_kind == owner_kind,
            MediaAssetLink.owner_id == owner_id,
            MediaAssetLink.status == "CONFIRMED",
            MediaAssetLink.detached_at.is_(None),
        )
        return session.scalar(query.with_for_update() if lock else query)

    def find_active_asset_link(
        self,
        session: Session,
        owner_kind: ImageOwnerKind,
        owner_id: str,
        asset_sha256: str,
    ) -> MediaAssetLink | None:
        return session.scalar(
            select(MediaAssetLink).where(
                MediaAssetLink.owner_kind == owner_kind,
                MediaAssetLink.owner_id == owner_id,
                MediaAssetLink.asset_sha256 == asset_sha256,
                MediaAssetLink.status == "CONFIRMED",
                MediaAssetLink.detached_at.is_(None),
            )
        )

    def list_active_links(
        self,
        session: Session,
        owner_kind: ImageOwnerKind,
        owner_id: str,
        *,
        lock: bool = False,
    ) -> list[MediaAssetLink]:
        query = (
            select(MediaAssetLink)
            .where(
                MediaAssetLink.owner_kind == owner_kind,
                MediaAssetLink.owner_id == owner_id,
                MediaAssetLink.status == "CONFIRMED",
                MediaAssetLink.detached_at.is_(None),
            )
            .order_by(MediaAssetLink.id)
        )
        if lock:
            query = query.with_for_update()
        return list(session.scalars(query))

    def get_ready_image(
        self,
        session: Session,
        owner_kind: ImageOwnerKind,
        owner_id: str,
        link_id: int,
    ) -> tuple[MediaAssetLink, MediaAsset] | None:
        row = session.execute(
            select(MediaAssetLink, MediaAsset)
            .join(MediaAsset, MediaAsset.asset_sha256 == MediaAssetLink.asset_sha256)
            .where(
                MediaAssetLink.id == link_id,
                MediaAssetLink.owner_kind == owner_kind,
                MediaAssetLink.owner_id == owner_id,
                MediaAssetLink.status == "CONFIRMED",
                MediaAssetLink.detached_at.is_(None),
                MediaAsset.ingest_status == "READY",
            )
        ).one_or_none()
        return row

    def next_primary(
        self,
        session: Session,
        owner_kind: ImageOwnerKind,
        owner_id: str,
        excluded_link_id: int,
    ) -> MediaAssetLink | None:
        return session.scalar(
            select(MediaAssetLink)
            .where(
                MediaAssetLink.owner_kind == owner_kind,
                MediaAssetLink.owner_id == owner_id,
                MediaAssetLink.status == "CONFIRMED",
                MediaAssetLink.detached_at.is_(None),
                MediaAssetLink.id != excluded_link_id,
            )
            .order_by(MediaAssetLink.sort_order, MediaAssetLink.id)
            .with_for_update()
        )

    def max_sort_order(
        self, session: Session, owner_kind: ImageOwnerKind, owner_id: str
    ) -> int | None:
        from sqlalchemy import func

        return session.scalar(
            select(func.max(MediaAssetLink.sort_order)).where(
                MediaAssetLink.owner_kind == owner_kind,
                MediaAssetLink.owner_id == owner_id,
                MediaAssetLink.status == "CONFIRMED",
                MediaAssetLink.detached_at.is_(None),
            )
        )

    @staticmethod
    def max_upload_bytes(session: Session) -> str | None:
        return read_setting(session, "image_max_bytes")


class ItemImageGalleryService:
    def __init__(self, repository: ItemImageGalleryRepository | None = None) -> None:
        self._repository = repository or ItemImageGalleryRepository()

    def list_images(
        self, session: Session, owner_kind: ImageOwnerKind, owner_id: str
    ) -> dict[str, object]:
        owner = self._repository.get_owner(session, owner_kind, owner_id)
        links = self._repository.list_active_images(session, owner_kind, owner_id)
        primary_link = next(
            (link for link, asset in links if link.is_primary and asset.ingest_status == "READY"),
            None,
        )
        fallback_kind: ImageOwnerKind | None = None
        fallback_owner_id: str | None = None
        if primary_link is None and isinstance(owner, StoreItem) and owner.mapping_confirmed:
            fallback_kind, fallback_owner_id = "ITEM", owner.item_id
            primary_link = self._repository.get_primary(session, "ITEM", owner.item_id)
        if primary_link is None:
            fallback_kind = None
            fallback_owner_id = None
        resolved_primary = None
        if primary_link is not None:
            resolved_kind = fallback_kind or owner_kind
            resolved_id = fallback_owner_id or owner_id
            resolved_primary = {
                "owner_kind": resolved_kind,
                "owner_id": resolved_id,
                "link_id": primary_link.id,
                "thumbnail_url": self._image_url(
                    resolved_kind, resolved_id, primary_link.id, "thumbnail"
                ),
            }
        return {
            "owner_kind": owner_kind,
            "owner_id": owner_id,
            "resolved_primary": resolved_primary,
            "placeholder": resolved_primary is None,
            "images": [
                {
                    "link_id": link.id,
                    "asset_sha256": asset.asset_sha256,
                    "is_primary": link.is_primary,
                    "sort_order": link.sort_order,
                    "source_id": link.source_id,
                    "source_page": link.source_page,
                    "ingest_status": asset.ingest_status,
                    "thumbnail_url": self._image_url(owner_kind, owner_id, link.id, "thumbnail"),
                    "display_url": self._image_url(owner_kind, owner_id, link.id, "display"),
                }
                for link, asset in links
                if asset.ingest_status == "READY"
            ],
        }

    def max_upload_bytes(self, session: Session) -> int:
        value = self._repository.max_upload_bytes(session)
        try:
            parsed = int(value) if value is not None else 0
        except ValueError as error:
            raise ValueError("Image size setting is invalid") from error
        if parsed <= 0:
            raise ValueError("Image size setting is invalid")
        return parsed

    def upload_image(
        self,
        session: Session,
        asset_service: MediaAssetService,
        owner_kind: ImageOwnerKind,
        owner_id: str,
        source: bytes,
        media_type: str,
        actor_id: int,
    ) -> dict[str, object]:
        self._repository.get_owner(session, owner_kind, owner_id, lock=True)
        asset = asset_service.stage(session, source, media_type, actor_id)
        asset_service.promote(session, asset.asset_sha256)
        duplicate = self._repository.find_active_asset_link(
            session, owner_kind, owner_id, asset.asset_sha256
        )
        if duplicate is not None:
            session.commit()
            return {
                "link_id": duplicate.id,
                "asset_sha256": asset.asset_sha256,
                "idempotent": True,
                "replace_prompt_required": False,
                "is_primary": duplicate.is_primary,
            }

        primary = self._repository.get_primary(session, owner_kind, owner_id, lock=True)
        last_sort_order = self._repository.max_sort_order(session, owner_kind, owner_id)
        link = MediaAssetLink(
            asset_sha256=asset.asset_sha256,
            owner_kind=owner_kind,
            owner_id=owner_id,
            status="CONFIRMED",
            is_primary=primary is None,
            sort_order=(last_sort_order if last_sort_order is not None else -1) + 1,
            created_by=actor_id,
        )
        try:
            with session.begin_nested():
                session.add(link)
                session.add(
                    AuditLog(
                        event_type="ITEM_IMAGE_UPLOADED",
                        actor=str(actor_id),
                        entity_type=owner_kind,
                        entity_id=owner_id,
                        details=(
                            f"asset_sha256={asset.asset_sha256}; is_primary={primary is None}"
                        ),
                    )
                )
                session.flush()
        except IntegrityError as error:
            concurrent_duplicate = self._repository.find_active_asset_link(
                session, owner_kind, owner_id, asset.asset_sha256
            )
            if concurrent_duplicate is not None:
                session.commit()
                return {
                    "link_id": concurrent_duplicate.id,
                    "asset_sha256": asset.asset_sha256,
                    "idempotent": True,
                    "replace_prompt_required": False,
                    "is_primary": concurrent_duplicate.is_primary,
                }
            raise ImageGalleryConflictError("Image gallery changed; retry upload") from error
        session.commit()
        return {
            "link_id": link.id,
            "asset_sha256": asset.asset_sha256,
            "idempotent": False,
            "replace_prompt_required": primary is not None,
            "is_primary": link.is_primary,
        }

    def read_image(
        self,
        session: Session,
        asset_service: MediaAssetService,
        owner_kind: ImageOwnerKind,
        owner_id: str,
        link_id: int,
        variant: Literal["thumbnail", "display", "original"],
    ) -> tuple[bytes, str]:
        row = self._repository.get_ready_image(session, owner_kind, owner_id, link_id)
        if row is None:
            raise NotFoundError("Image not found")
        _, asset = row
        file_key, content_type = {
            "thumbnail": (asset.thumbnail_file_key, asset.thumbnail_media_type),
            "display": (asset.display_file_key, asset.display_media_type),
            "original": (asset.original_file_key, asset.original_media_type),
        }[variant]
        try:
            return asset_service.read_protected_file(file_key), content_type
        except (FileNotFoundError, OSError, ValueError) as error:
            raise NotFoundError("Protected image unavailable") from error

    def set_primary(
        self,
        session: Session,
        owner_kind: ImageOwnerKind,
        owner_id: str,
        link_id: int,
        actor_id: int,
        replace_primary: bool,
    ) -> dict[str, object]:
        self._repository.get_owner(session, owner_kind, owner_id, lock=True)
        link = self._repository.get_link(session, owner_kind, owner_id, link_id, lock=True)
        if link is None:
            raise NotFoundError("Image not found")
        primary = self._repository.get_primary(session, owner_kind, owner_id, lock=True)
        if primary is not None and primary.id != link.id and not replace_primary:
            return {"link_id": link.id, "replace_prompt_required": True}
        try:
            with session.begin_nested():
                if primary is not None and primary.id != link.id:
                    primary.is_primary = False
                link.is_primary = True
                session.add(
                    AuditLog(
                        event_type="ITEM_IMAGE_PRIMARY_CHANGED",
                        actor=str(actor_id),
                        entity_type=owner_kind,
                        entity_id=owner_id,
                        details=(
                            f"link_id={link.id}; replaced_link_id={primary.id if primary else None}"
                        ),
                    )
                )
                session.flush()
        except IntegrityError as error:
            raise ImageGalleryConflictError(
                "Primary image changed; refresh the gallery"
            ) from error
        session.commit()
        return {
            "link_id": link.id,
            "is_primary": True,
            "idempotent": primary is not None and primary.id == link.id,
        }

    def reorder(
        self,
        session: Session,
        owner_kind: ImageOwnerKind,
        owner_id: str,
        link_ids: list[int],
        actor_id: int,
    ) -> dict[str, object]:
        self._repository.get_owner(session, owner_kind, owner_id, lock=True)
        links = self._repository.list_active_links(session, owner_kind, owner_id, lock=True)
        by_id = {link.id: link for link in links}
        if len(link_ids) != len(set(link_ids)) or set(link_ids) != set(by_id):
            raise ImageGalleryConflictError(
                "Image order must include every active gallery image once"
            )
        for index, link_id in enumerate(link_ids):
            by_id[link_id].sort_order = index
        session.add(
            AuditLog(
                event_type="ITEM_IMAGE_GALLERY_REORDERED",
                actor=str(actor_id),
                entity_type=owner_kind,
                entity_id=owner_id,
                details=f"ordered_link_ids={link_ids}",
            )
        )
        session.commit()
        return {"owner_kind": owner_kind, "owner_id": owner_id, "link_ids": link_ids}

    def detach(
        self,
        session: Session,
        owner_kind: ImageOwnerKind,
        owner_id: str,
        link_id: int,
        actor_id: int,
    ) -> dict[str, object]:
        self._repository.get_owner(session, owner_kind, owner_id, lock=True)
        link = self._repository.get_link(session, owner_kind, owner_id, link_id, lock=True)
        if link is None:
            raise NotFoundError("Image not found")
        was_primary = link.is_primary
        link.is_primary = False
        link.detached_at = datetime.now(UTC)
        next_primary = (
            self._repository.next_primary(session, owner_kind, owner_id, link_id)
            if was_primary
            else None
        )
        if next_primary is not None:
            next_primary.is_primary = True
        session.add(
            AuditLog(
                event_type="ITEM_IMAGE_DETACHED",
                actor=str(actor_id),
                entity_type=owner_kind,
                entity_id=owner_id,
                details=(
                    f"link_id={link.id}; promoted_link_id="
                    f"{next_primary.id if next_primary else None}"
                ),
            )
        )
        session.commit()
        return {
            "link_id": link.id,
            "detached": True,
            "promoted_link_id": next_primary.id if next_primary else None,
        }

    @staticmethod
    def _image_url(
        owner_kind: ImageOwnerKind,
        owner_id: str,
        link_id: int,
        variant: Literal["thumbnail", "display"],
    ) -> str:
        return f"/api/v1/image-owners/{owner_kind}/{owner_id}/images/{link_id}/{variant}"


def get_item_image_gallery_service() -> ItemImageGalleryService:
    return ItemImageGalleryService()


class ImageGalleryConflictError(ValueError):
    pass