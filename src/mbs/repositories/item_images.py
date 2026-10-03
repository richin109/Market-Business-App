from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbs.domain.item_images import ImageOwnerKind
from mbs.models import AuditLog, Item, MediaAsset, MediaAssetLink, StoreItem
from mbs.repositories.settings import SettingsRepository


class GalleryPersistenceConflictError(Exception):
    pass


class ItemImageGalleryRepository:
    def get_owner(
        self,
        session: Session,
        owner_kind: ImageOwnerKind,
        owner_id: str,
        *,
        lock: bool = False,
    ) -> Item | StoreItem | None:
        if owner_kind == "ITEM":
            query = select(Item).where(Item.item_id == owner_id)
            owner = session.scalar(query.with_for_update() if lock else query)
            return owner
        store_item_query = select(StoreItem).where(StoreItem.store_item_id == owner_id)
        store_item = session.scalar(
            store_item_query.with_for_update() if lock else store_item_query
        )
        return store_item

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
        *,
        lock: bool = False,
    ) -> MediaAssetLink | None:
        query = select(MediaAssetLink).where(
            MediaAssetLink.owner_kind == owner_kind,
            MediaAssetLink.owner_id == owner_id,
            MediaAssetLink.asset_sha256 == asset_sha256,
            MediaAssetLink.status == "CONFIRMED",
            MediaAssetLink.detached_at.is_(None),
        )
        return session.scalar(query.with_for_update() if lock else query)

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
        setting = SettingsRepository().get_setting(session, "image_max_bytes")
        if setting is None:
            raise KeyError("Unknown setting: image_max_bytes")
        return setting.value

    @contextmanager
    def savepoint(self, session: Session) -> Iterator[None]:
        try:
            with session.begin_nested():
                yield
                session.flush()
        except IntegrityError as error:
            raise GalleryPersistenceConflictError from error

    def add_link(self, session: Session, link: MediaAssetLink) -> None:
        session.add(link)

    def record_event(
        self,
        session: Session,
        event_type: str,
        actor_id: int,
        owner_kind: ImageOwnerKind,
        owner_id: str,
        details: str,
    ) -> None:
        session.add(
            AuditLog(
                event_type=event_type,
                actor=str(actor_id),
                entity_type=owner_kind,
                entity_id=owner_id,
                details=details,
            )
        )

    def set_primary(self, link: MediaAssetLink, is_primary: bool) -> None:
        link.is_primary = is_primary

    def set_order(self, link: MediaAssetLink, sort_order: int) -> None:
        link.sort_order = sort_order

    def detach_link(self, link: MediaAssetLink, detached_at: datetime) -> None:
        link.is_primary = False
        link.detached_at = detached_at

    def commit(self, session: Session) -> None:
        session.commit()
