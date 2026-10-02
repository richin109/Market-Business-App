from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pymupdf
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbs.auth import Role, create_session, create_user
from mbs.db import get_session
from mbs.items import register_store_item
from mbs.main import app
from mbs.media_assets import MediaAssetService, _encode_thumbnail
from mbs.models import (
    AuditLog,
    Item,
    MediaAsset,
    MediaAssetLink,
    Setting,
    Store,
)
from mbs.receipts.pdf_extraction import extract_embedded_pdf_images
from mbs.receipts.storage import LocalProtectedFileStore
from mbs.routers.dependencies import get_media_asset_service
from tests.database import postgres_test_url


def _database(path: Path) -> tuple[Engine, Session]:
    engine = create_engine(postgres_test_url(path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(path).replace("%", "%%"))
    command.upgrade(config, "head")
    return engine, Session(engine)


def _jpeg_with_exif(
    size: tuple[int, int] = (1600, 1000),
    color: tuple[int, int, int] = (40, 120, 80),
) -> bytes:
    image = Image.new("RGB", size, color=color)
    exif = Image.Exif()
    exif[274] = 6
    buffer = BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


class _FixedPerceptualHasher:
    def fingerprint(self, source: bytes, media_type: str) -> str:
        return "a" * 32


def _set_setting(session: Session, key: str, value: str) -> None:
    setting = session.get(Setting, key)
    assert setting is not None
    setting.value = value


def _png_image(size: tuple[int, int], color: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", size, color=color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_im_001_extracts_two_embedded_images_with_region_and_line_provenance() -> None:
    first_image = _png_image((160, 120), (35, 110, 70))
    second_image = _png_image((180, 140), (100, 40, 150))
    pdf = cast(Any, pymupdf).open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((40, 80), "Synthetic product one")
    page.insert_image(cast(Any, pymupdf).Rect(300, 50, 460, 170), stream=first_image)
    page.insert_text((40, 300), "Synthetic product two")
    page.insert_image(cast(Any, pymupdf).Rect(300, 270, 480, 410), stream=second_image)

    candidates = extract_embedded_pdf_images(
        pdf.tobytes(),
        {
            "items": [
                {"description": "Synthetic product one"},
                {"description": "Synthetic product two"},
            ]
        },
        100,
    )

    assert len(candidates) == 2
    first, second = candidates
    assert first.media_type == second.media_type == "image/png"
    assert first.page_number == second.page_number == 1
    assert (first.pixel_width, first.pixel_height) == (160, 120)
    assert (second.pixel_width, second.pixel_height) == (180, 140)
    assert first.region == (300.0, 50.0, 460.0, 170.0)
    assert second.region == (300.0, 270.0, 480.0, 410.0)
    assert first.item_index == 0
    assert second.item_index == 1
    assert first.image_bytes.startswith(bytes.fromhex("89504e470d0a1a0a"))


@pytest.mark.parametrize(
    ("max_image_bytes", "max_dimension_px"),
    [(1_000_000, 100), (100, 10_000)],
    ids=["dimension-setting", "byte-setting"],
)
def test_im_001_skips_images_over_configured_limits_before_candidate_creation(
    max_image_bytes: int,
    max_dimension_px: int,
) -> None:
    pdf = cast(Any, pymupdf).open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((40, 80), "Synthetic oversized image")
    page.insert_image(
        cast(Any, pymupdf).Rect(300, 50, 460, 170),
        stream=_png_image((160, 120), (35, 110, 70)),
    )

    candidates = extract_embedded_pdf_images(
        pdf.tobytes(),
        {"items": [{"description": "Synthetic oversized image"}]},
        100,
        max_image_bytes,
        max_dimension_px,
    )

    assert candidates == ()


def test_im_001_retains_unmatched_images_without_assigning_a_line() -> None:
    pdf = cast(Any, pymupdf).open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((40, 80), "Unrelated receipt text")
    page.insert_image(
        cast(Any, pymupdf).Rect(300, 50, 460, 170),
        stream=_png_image((160, 120), (35, 110, 70)),
    )

    candidates = extract_embedded_pdf_images(
        pdf.tobytes(), {"items": [{"description": "Different product"}]}, 100
    )

    assert len(candidates) == 1
    assert candidates[0].item_index is None


def test_im_001_excludes_full_page_small_header_and_barcode_images() -> None:
    full_page = _png_image((600, 800), (90, 90, 90))
    small = _png_image((80, 80), (20, 130, 90))
    logo = _png_image((240, 80), (15, 60, 160))
    barcode_image = Image.new("RGB", (360, 120), "white")
    drawing = ImageDraw.Draw(barcode_image)
    for position in range(4, 356, 4):
        drawing.rectangle((position, 10, position + 1, 110), fill="black")
    barcode_buffer = BytesIO()
    barcode_image.save(barcode_buffer, format="PNG")

    pdf = cast(Any, pymupdf).open()
    page = pdf.new_page(width=600, height=800)
    page.insert_image(cast(Any, pymupdf).Rect(0, 0, 600, 800), stream=full_page)
    page.insert_image(cast(Any, pymupdf).Rect(250, 200, 330, 280), stream=small)
    page.insert_image(cast(Any, pymupdf).Rect(20, 10, 260, 90), stream=logo)
    page.insert_image(
        cast(Any, pymupdf).Rect(200, 300, 560, 420),
        stream=barcode_buffer.getvalue(),
    )

    candidates = extract_embedded_pdf_images(pdf.tobytes(), {"items": []}, 100)

    assert candidates == ()


def _patterned_png(position: int, color: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (160, 120), "white")
    ImageDraw.Draw(image).rectangle((position, 10, position + 42, 110), fill=color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_im_002_owner_galleries_upload_replace_reorder_detach_and_fallback(
    tmp_path: Path,
) -> None:
    engine, session = _database(tmp_path / "owner-galleries.db")
    file_store = LocalProtectedFileStore(tmp_path / "owner-gallery-files")
    service = MediaAssetService(file_store)
    manager = create_user(session, "gallery-manager", "synthetic password", Role.MANAGER)
    viewer = create_user(session, "gallery-viewer", "synthetic password", Role.VIEWER)
    manager_token, manager_csrf = create_session(session, manager)
    viewer_token, viewer_csrf = create_session(session, viewer)
    store = Store(display_name="Synthetic Gallery Store")
    session.add(store)
    session.flush()
    store_item = register_store_item(
        session,
        store.store_id,
        "GALLERY-SKU-1",
        "Synthetic cups",
        actor_id=manager.id,
    )
    item = session.get(Item, store_item.item_id)
    assert item is not None
    store_item.mapping_confirmed = True
    session.commit()
    item_id = item.item_id
    store_item_id = store_item.store_item_id
    session.close()

    def override_session() -> Any:
        with Session(engine) as active_session:
            yield active_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_media_asset_service] = lambda: service
    manager_headers = {
        "Cookie": f"mbs_session={manager_token}",
        "X-CSRF-Token": manager_csrf,
    }
    viewer_headers = {
        "Cookie": f"mbs_session={viewer_token}",
        "X-CSRF-Token": viewer_csrf,
    }
    item_path = f"/api/v1/image-owners/ITEM/{item_id}/images"
    store_path = f"/api/v1/image-owners/STORE_ITEM/{store_item_id}/images"
    try:
        client = TestClient(app)
        initial = client.get(item_path, headers=viewer_headers)
        assert initial.status_code == 200 and initial.json()["placeholder"] is True
        assert (
            client.post(
                item_path,
                content=_patterned_png(5, (200, 30, 40)),
                headers={
                    "Cookie": f"mbs_session={viewer_token}",
                    "Content-Type": "image/png",
                    "X-CSRF-Token": viewer_csrf,
                },
            ).status_code
            == 403
        )
        assert (
            client.post(
                item_path,
                content=_patterned_png(5, (200, 30, 40)),
                headers={"Cookie": f"mbs_session={manager_token}", "Content-Type": "image/png"},
            ).status_code
            == 403
        )

        first_bytes = _patterned_png(5, (200, 30, 40))
        first = client.post(
            item_path,
            content=first_bytes,
            headers={**manager_headers, "Content-Type": "image/png"},
        )
        assert first.status_code == 200 and first.json()["is_primary"] is True
        duplicate = client.post(
            item_path,
            content=first_bytes,
            headers={**manager_headers, "Content-Type": "image/png"},
        )
        assert duplicate.status_code == 200 and duplicate.json()["idempotent"] is True

        second = client.post(
            item_path,
            content=_patterned_png(65, (20, 140, 50)),
            headers={**manager_headers, "Content-Type": "image/png"},
        )
        assert second.status_code == 200 and second.json()["replace_prompt_required"] is True
        second_link = second.json()["link_id"]
        prompt = client.post(
            f"{item_path}/{second_link}/primary",
            headers=manager_headers,
            json={"replace_primary": False},
        )
        assert prompt.status_code == 200 and prompt.json()["replace_prompt_required"] is True
        replaced = client.post(
            f"{item_path}/{second_link}/primary",
            headers=manager_headers,
            json={"replace_primary": True},
        )
        assert replaced.status_code == 200 and replaced.json()["is_primary"] is True

        third = client.post(
            item_path,
            content=_patterned_png(110, (35, 55, 210)),
            headers={**manager_headers, "Content-Type": "image/png"},
        )
        assert third.status_code == 200 and third.json()["is_primary"] is False
        item_gallery = client.get(item_path, headers=viewer_headers).json()
        ordered_ids = [image["link_id"] for image in item_gallery["images"]]
        assert len(ordered_ids) == 3
        reordered = client.put(
            f"{item_path}/order",
            headers=manager_headers,
            json={"link_ids": list(reversed(ordered_ids))},
        )
        assert reordered.status_code == 200

        store_fallback = client.get(store_path, headers=viewer_headers).json()
        assert store_fallback["resolved_primary"]["owner_kind"] == "ITEM"
        store_image = client.post(
            store_path,
            content=_patterned_png(30, (180, 80, 15)),
            headers={**manager_headers, "Content-Type": "image/png"},
        )
        assert store_image.status_code == 200 and store_image.json()["is_primary"] is True
        store_link_id = store_image.json()["link_id"]
        store_primary = client.get(store_path, headers=viewer_headers).json()
        assert store_primary["resolved_primary"]["owner_kind"] == "STORE_ITEM"

        detached = client.delete(f"{store_path}/{store_link_id}", headers=manager_headers)
        assert detached.status_code == 200 and detached.json()["detached"] is True
        resolved_after_detach = client.get(store_path, headers=viewer_headers).json()
        assert resolved_after_detach["resolved_primary"]["owner_kind"] == "ITEM"
        assert (
            client.get(
                f"{store_path}/{store_link_id}/thumbnail", headers=viewer_headers
            ).status_code
            == 404
        )
        primary_image = client.get(f"{item_path}/{second_link}/thumbnail", headers=viewer_headers)
        assert primary_image.status_code == 200
        assert primary_image.headers["cache-control"] == "private, no-store, max-age=0"
        assert primary_image.headers["x-content-type-options"] == "nosniff"
        detached_primary = client.delete(f"{item_path}/{second_link}", headers=manager_headers)
        assert detached_primary.status_code == 200
        assert detached_primary.json()["promoted_link_id"] is not None

        with Session(engine) as verify_session:
            assert verify_session.scalar(select(func.count(MediaAsset.asset_sha256))) == 4
            assert (
                verify_session.scalar(
                    select(func.count(MediaAssetLink.id)).where(
                        MediaAssetLink.owner_kind == "ITEM",
                        MediaAssetLink.owner_id == item_id,
                        MediaAssetLink.is_primary.is_(True),
                        MediaAssetLink.detached_at.is_(None),
                    )
                )
                == 1
            )
            assert (
                verify_session.scalar(
                    select(AuditLog).where(AuditLog.event_type == "ITEM_IMAGE_DETACHED")
                )
                is not None
            )
            remaining = verify_session.scalar(
                select(MediaAsset).where(MediaAsset.asset_sha256 == second.json()["asset_sha256"])
            )
            assert remaining is not None
            assert file_store.read(remaining.original_file_key)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_s17_thumbnail_respects_target_for_high_entropy_images() -> None:
    noisy_image = Image.effect_noise((320, 320), 100).convert("RGB")
    thumbnail, media_type = _encode_thumbnail(noisy_image)
    with Image.open(BytesIO(thumbnail)) as decoded:
        assert max(decoded.size) <= 320
    assert media_type in {"image/webp", "image/jpeg"}
    assert len(thumbnail) <= 40_000


def test_s17_asset_ingest_sanitizes_derives_and_deduplicates(tmp_path: Path) -> None:
    engine, session = _database(tmp_path / "media-assets.db")
    try:
        actor = create_user(session, "media-manager", "synthetic password", Role.MANAGER)
        file_store = LocalProtectedFileStore(tmp_path / "protected-media")
        service = MediaAssetService(file_store, _FixedPerceptualHasher())
        source = _jpeg_with_exif()

        staged = service.stage(session, source, "image/jpeg", actor.id)
        session.commit()
        assert staged.ingest_status == "STAGED"
        assert staged.scan_status == "NOT_SCANNED"

        ready = service.promote(session, staged.asset_sha256)
        session.commit()
        original = Image.open(BytesIO(file_store.read(ready.original_file_key)))
        display = Image.open(BytesIO(file_store.read(ready.display_file_key)))
        thumbnail = Image.open(BytesIO(file_store.read(ready.thumbnail_file_key)))

        assert ready.ingest_status == "READY"
        assert original.getexif() == {}
        assert max(ready.width_px, ready.height_px) <= 2_000
        assert max(display.size) <= 1_024
        assert max(thumbnail.size) <= 320
        assert ready.thumbnail_size_bytes <= 40_000
        assert ready.display_media_type == ready.thumbnail_media_type == "image/webp"
        assert service.promote(session, staged.asset_sha256).ingest_status == "READY"
        assert session.scalar(select(func.count(MediaAsset.asset_sha256))) == 1
        assert (
            session.scalar(
                select(AuditLog).where(AuditLog.event_type == "MEDIA_ASSET_IMAGE_NOT_SCANNED")
            )
            is not None
        )

        session.add(
            MediaAssetLink(
                asset_sha256=ready.asset_sha256,
                owner_kind="ITEM",
                owner_id="synthetic-item",
                status="CONFIRMED",
                is_primary=True,
            )
        )
        session.commit()
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(
                    MediaAssetLink(
                        asset_sha256=ready.asset_sha256,
                        owner_kind="ITEM",
                        owner_id="synthetic-item",
                        status="CONFIRMED",
                        is_primary=True,
                    )
                )
                session.flush()
        assert session.scalar(select(func.count(MediaAssetLink.id))) == 1

        retried = service.stage(session, source, "image/jpeg", actor.id)
        session.commit()
        assert retried.asset_sha256 == ready.asset_sha256
        assert retried.ingest_status == "READY"
        perceptual_duplicate = service.stage(
            session,
            _jpeg_with_exif((800, 500), color=(41, 120, 80)),
            "image/jpeg",
            actor.id,
        )
        assert perceptual_duplicate.asset_sha256 == ready.asset_sha256
        assert session.scalar(select(func.count(MediaAsset.asset_sha256))) == 1
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("source", "media_type", "setting", "value", "error"),
    [
        (b"<svg/>", "image/png", None, None, "signature"),
        (bytes.fromhex("89504e470d0a1a0a") + b"not an image", "image/png", None, None, "invalid"),
        (_jpeg_with_exif(), "image/jpeg", "image_max_bytes", "100", "size limit"),
        (
            _jpeg_with_exif((2400, 1000)),
            "image/jpeg",
            "image_max_dimension_px",
            "2000",
            "dimensions",
        ),
        (
            _jpeg_with_exif(),
            "image/jpeg",
            "image_allowed_media_types",
            "image/png",
            "Unsupported image media type",
        ),
        (_jpeg_with_exif((20, 20)), "image/jpeg", None, None, "decompression bomb"),
    ],
    ids=[
        "signature",
        "malformed",
        "byte-limit",
        "dimension-limit",
        "configured-media-type",
        "decompression-bomb",
    ],
)
def test_s17_asset_ingest_rejects_invalid_images_and_limits(
    tmp_path: Path,
    source: bytes,
    media_type: str,
    setting: str | None,
    value: str | None,
    error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, session = _database(tmp_path / f"rejected-media-{error.replace(' ', '-')}.db")
    try:
        actor = create_user(session, "media-manager", "synthetic password", Role.MANAGER)
        file_store = LocalProtectedFileStore(tmp_path / "protected-media")
        if setting is not None and value is not None:
            _set_setting(session, setting, value)
        if error == "decompression bomb":
            monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
        service = MediaAssetService(file_store)

        expected_error = "safety limits" if error == "decompression bomb" else error
        with pytest.raises(ValueError, match=expected_error):
            service.stage(session, source, media_type, actor.id)

        assert session.scalar(select(func.count(MediaAsset.asset_sha256))) == 0
        assert list((tmp_path / "protected-media").rglob("*")) == []
    finally:
        session.close()
        engine.dispose()
