from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.orm import Session

from mbs.domain.item_images import (
    GalleryOrder,
    ImageGalleryConflictError,
    ImageOwnerKind,
    parse_image_upload_limit,
    replacement_required,
)
from mbs.errors import NotFoundError
from mbs.media_assets import MediaAssetService
from mbs.models import Item, MediaAssetLink, StoreItem
from mbs.repositories.item_images import (
    GalleryPersistenceConflictError,
    ItemImageGalleryRepository,
)


class ItemImageGalleryService:
    def __init__(self, repository: ItemImageGalleryRepository | None = None) -> None:
        self._repository = repository or ItemImageGalleryRepository()

    def require_owner(
        self, session: Session, owner_kind: ImageOwnerKind, owner_id: str, *, lock: bool = False
    ) -> Item | StoreItem:
        owner = self._repository.get_owner(session, owner_kind, owner_id, lock=lock)
        if owner is None or (isinstance(owner, Item) and not owner.is_active):
            raise NotFoundError("Image owner not found")
        return owner

    def list_images(
        self, session: Session, owner_kind: ImageOwnerKind, owner_id: str
    ) -> dict[str, object]:
        owner = self.require_owner(session, owner_kind, owner_id)
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
        return parse_image_upload_limit(self._repository.max_upload_bytes(session))

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
        self.require_owner(session, owner_kind, owner_id, lock=True)
        asset = asset_service.stage(session, source, media_type, actor_id)
        asset_service.promote(session, asset.asset_sha256)
        duplicate = self._repository.find_active_asset_link(
            session, owner_kind, owner_id, asset.asset_sha256
        )
        if duplicate is not None:
            self._repository.commit(session)
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
            with self._repository.savepoint(session):
                self._repository.add_link(session, link)
                self._repository.record_event(
                    session,
                    "ITEM_IMAGE_UPLOADED",
                    actor_id,
                    owner_kind,
                    owner_id,
                    f"asset_sha256={asset.asset_sha256}; is_primary={primary is None}",
                )
        except GalleryPersistenceConflictError as error:
            concurrent_duplicate = self._repository.find_active_asset_link(
                session, owner_kind, owner_id, asset.asset_sha256
            )
            if concurrent_duplicate is not None:
                self._repository.commit(session)
                return {
                    "link_id": concurrent_duplicate.id,
                    "asset_sha256": asset.asset_sha256,
                    "idempotent": True,
                    "replace_prompt_required": False,
                    "is_primary": concurrent_duplicate.is_primary,
                }
            raise ImageGalleryConflictError("Image gallery changed; retry upload") from error
        self._repository.commit(session)
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
        self.require_owner(session, owner_kind, owner_id, lock=True)
        link = self._repository.get_link(session, owner_kind, owner_id, link_id, lock=True)
        if link is None:
            raise NotFoundError("Image not found")
        primary = self._repository.get_primary(session, owner_kind, owner_id, lock=True)
        if replacement_required(primary.id if primary else None, link.id, replace_primary):
            return {"link_id": link.id, "replace_prompt_required": True}
        try:
            with self._repository.savepoint(session):
                if primary is not None and primary.id != link.id:
                    self._repository.set_primary(primary, False)
                self._repository.set_primary(link, True)
                self._repository.record_event(
                    session,
                    "ITEM_IMAGE_PRIMARY_CHANGED",
                    actor_id,
                    owner_kind,
                    owner_id,
                    f"link_id={link.id}; replaced_link_id={primary.id if primary else None}",
                )
        except GalleryPersistenceConflictError as error:
            raise ImageGalleryConflictError("Primary image changed; refresh the gallery") from error
        self._repository.commit(session)
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
        self.require_owner(session, owner_kind, owner_id, lock=True)
        links = self._repository.list_active_links(session, owner_kind, owner_id, lock=True)
        by_id = {link.id: link for link in links}
        order = GalleryOrder(tuple(link_ids))
        order.validate(by_id)
        for index, link_id in enumerate(order.link_ids):
            self._repository.set_order(by_id[link_id], index)
        self._repository.record_event(
            session,
            "ITEM_IMAGE_GALLERY_REORDERED",
            actor_id,
            owner_kind,
            owner_id,
            f"ordered_link_ids={link_ids}",
        )
        self._repository.commit(session)
        return {"owner_kind": owner_kind, "owner_id": owner_id, "link_ids": link_ids}

    def detach(
        self,
        session: Session,
        owner_kind: ImageOwnerKind,
        owner_id: str,
        link_id: int,
        actor_id: int,
    ) -> dict[str, object]:
        self.require_owner(session, owner_kind, owner_id, lock=True)
        link = self._repository.get_link(session, owner_kind, owner_id, link_id, lock=True)
        if link is None:
            raise NotFoundError("Image not found")
        was_primary = link.is_primary
        self._repository.detach_link(link, datetime.now(UTC))
        next_primary = (
            self._repository.next_primary(session, owner_kind, owner_id, link_id)
            if was_primary
            else None
        )
        if next_primary is not None:
            self._repository.set_primary(next_primary, True)
        self._repository.record_event(
            session,
            "ITEM_IMAGE_DETACHED",
            actor_id,
            owner_kind,
            owner_id,
            f"link_id={link.id}; promoted_link_id={next_primary.id if next_primary else None}",
        )
        self._repository.commit(session)
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
