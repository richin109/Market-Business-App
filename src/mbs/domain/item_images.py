from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Literal

ImageOwnerKind = Literal["ITEM", "STORE_ITEM"]


class ImageGalleryConflictError(ValueError):
    pass


@dataclass(frozen=True)
class GalleryOrder:
    link_ids: tuple[int, ...]

    def validate(self, active_link_ids: Collection[int]) -> None:
        if len(self.link_ids) != len(set(self.link_ids)) or set(self.link_ids) != set(
            active_link_ids
        ):
            raise ImageGalleryConflictError(
                "Image order must include every active gallery image once"
            )


def replacement_required(primary_id: int | None, link_id: int, confirmed: bool) -> bool:
    return primary_id is not None and primary_id != link_id and not confirmed


def parse_image_upload_limit(value: str | None) -> int:
    try:
        parsed = int(value) if value is not None else 0
    except ValueError as error:
        raise ValueError("Image size setting is invalid") from error
    if parsed <= 0:
        raise ValueError("Image size setting is invalid")
    return parsed
