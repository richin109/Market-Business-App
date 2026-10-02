from __future__ import annotations

import hashlib
import json
import tempfile
from http.client import HTTPConnection
from io import BytesIO
from pathlib import Path
from time import monotonic, sleep
from typing import TypedDict, cast
from uuid import uuid4

from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from mbs.auth import Role, create_session, create_user
from mbs.database_config import database_url
from mbs.db import SessionLocal
from mbs.media_assets import MediaAssetService
from mbs.models import (
    MediaAsset,
    MediaAssetLink,
    Receipt,
    ReceiptItem,
    ReceiptSource,
    ReceiptUpload,
    User,
)
from mbs.receipts.ocr import normalize_receipt
from mbs.receipts.pdf_extraction import EmbeddedPDFImage
from mbs.receipts.persistence import create_upload, persist_extracted_receipt
from mbs.receipts.storage import LocalProtectedFileStore, receipt_storage_root

STATE_PATH = Path(tempfile.gettempdir()) / "mbs-s13-restart-smoke.json"
BATCH_SIZE = 5


class SmokeState(TypedDict):
    run_id: str
    manager_username: str
    receipt_pks: list[str]
    version: int


def _require_dev_database() -> None:
    url = make_url(database_url())
    if (
        url.get_backend_name() != "postgresql"
        or url.host != "postgres"
        or url.port not in {None, 5432}
        or url.database != "mbs"
    ):
        raise SystemExit("S13 smoke only permits the local Compose database named mbs")


def _state() -> SmokeState:
    return cast(SmokeState, json.loads(STATE_PATH.read_text(encoding="utf-8")))


def _write_state(state: SmokeState) -> None:
    STATE_PATH.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")


def _save_upload(
    session: Session,
    file_store: LocalProtectedFileStore,
    content: bytes,
    media_type: str,
    actor: int,
) -> ReceiptUpload:
    digest = hashlib.sha256(content).hexdigest()
    key = file_store.save(digest, content, media_type)
    return create_upload(session, digest, key, media_type, len(content), actor)


def _seed_batch(state: SmokeState, version: int) -> None:
    run_id = str(state["run_id"])
    file_store = LocalProtectedFileStore(receipt_storage_root())
    created_receipts: list[str] = []
    with SessionLocal.begin() as session:
        manager = session.scalar(select(User).where(User.username == state["manager_username"]))
        if manager is None:
            raise RuntimeError("Synthetic smoke manager is missing")
        for offset in range(BATCH_SIZE):
            order_number = (version - 1) * BATCH_SIZE + offset
            transaction_number = f"S13-{run_id}-V{version}-{order_number + 1:02d}"
            content = f"%PDF-1.7 synthetic source {transaction_number}".encode()
            upload = _save_upload(session, file_store, content, "application/pdf", manager.id)
            receipt = persist_extracted_receipt(
                session,
                normalize_receipt(
                    {
                        "receipt": {
                            "store": "Synthetic S13 Market",
                            "date": "2026-10-02",
                            "time": f"09:{order_number:02d}:00",
                            "transaction_number": transaction_number,
                            "total": "1.00",
                        },
                        "items": [
                            {
                                "description": f"Synthetic item {order_number + 1:02d}",
                                "line_total": "1.00",
                            }
                        ],
                    }
                ),
                upload,
                increment_ocr_attempts=False,
            )
            session.flush()
            created_receipts.append(receipt.receipt_pk)

            if order_number == 0:
                supplement_bytes = f"%PDF-1.7 synthetic supplement {run_id}".encode()
                supplement = _save_upload(
                    session, file_store, supplement_bytes, "application/pdf", manager.id
                )
                supplement.processing_status = "SUCCEEDED"
                session.add(
                    ReceiptSource(
                        receipt_pk=receipt.receipt_pk,
                        upload_pk=supplement.upload_pk,
                        source_sha256=supplement.source_sha256,
                        association_kind="SUPPLEMENT",
                        raw_ocr_document={},
                        extracted_document={"items": []},
                    )
                )
                session.flush()

                image = Image.new("RGB", (160, 120), "white")
                ImageDraw.Draw(image).rectangle((12, 12, 92, 108), fill=(35, 105, 70))
                image_buffer = BytesIO()
                image.save(image_buffer, format="PNG")
                primary_source = session.scalar(
                    select(ReceiptSource).where(
                        ReceiptSource.receipt_pk == receipt.receipt_pk,
                        ReceiptSource.association_kind == "PRIMARY",
                    )
                )
                line = session.scalar(
                    select(ReceiptItem).where(ReceiptItem.receipt_pk == receipt.receipt_pk)
                )
                if primary_source is None or line is None:
                    raise RuntimeError("Synthetic source fixture was not persisted")
                MediaAssetService.persist_pdf_image_candidates(
                    session,
                    primary_source,
                    (
                        EmbeddedPDFImage(
                            image_bytes=image_buffer.getvalue(),
                            media_type="image/png",
                            page_number=1,
                            region=(12.0, 12.0, 92.0, 108.0),
                            page_width=600.0,
                            page_height=800.0,
                            pixel_width=160,
                            pixel_height=120,
                            item_index=0,
                        ),
                    ),
                    [line],
                    file_store,
                    manager.id,
                )

    state["receipt_pks"] = [*state["receipt_pks"], *created_receipts]
    state["version"] = version
    _write_state(state)


def seed() -> None:
    _require_dev_database()
    state: SmokeState
    if STATE_PATH.exists():
        state = _state()
        if state["version"] != 0 or state["receipt_pks"]:
            raise SystemExit("A non-empty S13 smoke run already exists in this container")
    else:
        run_id = uuid4().hex[:10]
        state = {
            "run_id": run_id,
            "manager_username": f"s13-smoke-{run_id}",
            "receipt_pks": [],
            "version": 0,
        }
        with SessionLocal.begin() as session:
            create_user(
                session,
                str(state["manager_username"]),
                "synthetic-only-s13-password",
                Role.MANAGER,
            )
        _write_state(state)
    _seed_batch(state, 1)
    print(json.dumps({"run_id": state["run_id"], "orders": BATCH_SIZE, "version": 1}))


def append() -> None:
    _require_dev_database()
    state = _state()
    version = int(state["version"]) + 1
    if version > 3 or len(state["receipt_pks"]) != (version - 1) * BATCH_SIZE:
        raise SystemExit("Only the next 5-order synthetic source version may be appended")
    _seed_batch(state, version)
    print(
        json.dumps(
            {
                "run_id": state["run_id"],
                "orders": len(state["receipt_pks"]),
                "version": version,
            }
        )
    )


def verify() -> None:
    _require_dev_database()
    state = _state()
    receipt_pks = [str(value) for value in state["receipt_pks"]]
    expected_count = int(state["version"]) * BATCH_SIZE
    if len(receipt_pks) != expected_count:
        raise AssertionError("Synthetic source-version count is inconsistent")
    root = receipt_storage_root()
    file_store = LocalProtectedFileStore(root)
    with SessionLocal.begin() as session:
        receipts = session.scalars(select(Receipt).where(Receipt.receipt_pk.in_(receipt_pks))).all()
        if len(receipts) != expected_count:
            raise AssertionError("Receipt lineage did not survive the Compose restart")
        sources = session.scalars(
            select(ReceiptSource)
            .where(ReceiptSource.receipt_pk.in_(receipt_pks))
            .order_by(ReceiptSource.receipt_pk, ReceiptSource.id)
        ).all()
        if len(sources) != expected_count + 1:
            raise AssertionError("Primary and supplemental source associations were not retained")
        upload_ids = [source.upload_pk for source in sources]
        smoke_uploads = session.scalars(
            select(ReceiptUpload).where(ReceiptUpload.upload_pk.in_(upload_ids))
        ).all()
        if len(smoke_uploads) != len(upload_ids) or any(
            upload.ocr_attempts != 0 for upload in smoke_uploads
        ):
            raise AssertionError("A smoke source was sent through OCR")
        source_uploads = {upload.upload_pk: upload for upload in smoke_uploads}
        source_hashes = {
            upload_id: upload.source_sha256 for upload_id, upload in source_uploads.items()
        }
        for source in sources:
            content = file_store.read(source_uploads[source.upload_pk].file_key)
            if hashlib.sha256(content).hexdigest() != source_hashes[source.upload_pk]:
                raise AssertionError("A protected source checksum changed across restart")

        first_pk = receipt_pks[0]
        first_receipt = session.get(Receipt, first_pk)
        if first_receipt is None:
            raise AssertionError("First synthetic receipt was not retained")
        first_source_ids = [source.id for source in sources if source.receipt_pk == first_pk]
        candidate = session.scalar(
            select(MediaAssetLink).where(
                MediaAssetLink.owner_kind == "RECEIPT_LINE_CANDIDATE",
                MediaAssetLink.source_id.in_(first_source_ids),
            )
        )
        asset = (
            session.get(MediaAsset, candidate.asset_sha256) if candidate is not None else None
        )
        if asset is None or candidate is None:
            raise AssertionError("Synthetic receipt media candidate was not retained")
        media_key = asset.thumbnail_file_key
        expected_media_hash = Path(media_key).stem
        expected_transaction = first_receipt.transaction_number
        candidate_id = candidate.id
        manager = session.scalar(
            select(User).where(User.username == state["manager_username"])
        )
        if manager is None:
            raise AssertionError("Synthetic smoke manager was not retained")
        token, _ = create_session(session, manager)

    def get(path: str) -> tuple[int, bytes]:
        deadline = monotonic() + 30
        while True:
            connection = HTTPConnection("127.0.0.1", 8000, timeout=2)
            try:
                connection.request(
                    "GET",
                    path,
                    headers={"Cookie": f"mbs_session={token}"},
                )
                response = connection.getresponse()
                return response.status, response.read()
            except ConnectionRefusedError:
                if monotonic() >= deadline:
                    raise
                sleep(0.25)
            finally:
                connection.close()

    status, detail = get(f"/api/v1/receipts/{first_pk}")
    if status != 200 or expected_transaction.encode() not in detail:
        raise AssertionError("Receipt detail is not reviewable after restart")
    status, review = get(f"/api/v1/receipts/{first_pk}/review")
    if status != 200 or b"Synthetic item 01" not in review:
        raise AssertionError("Receipt review page is not available after restart")
    status, thumbnail = get(
        f"/api/v1/receipts/{first_pk}/image-candidates/{candidate_id}/thumbnail"
    )
    if status != 200 or hashlib.sha256(thumbnail).hexdigest() != expected_media_hash:
        raise AssertionError("Protected media candidate is not reviewable after restart")
    for source_id, source_receipt_pk, upload_id in (
        (source.id, source.receipt_pk, source.upload_pk) for source in sources
    ):
        status, content = get(
            f"/api/v1/receipts/{source_receipt_pk}/sources/{source_id}/content"
        )
        if status != 200 or hashlib.sha256(content).hexdigest() != source_hashes[upload_id]:
            raise AssertionError("Protected source is not reviewable after restart")

    print(
        json.dumps(
            {
                "run_id": state["run_id"],
                "version": state["version"],
                "orders": expected_count,
                "source_associations": len(sources),
                "ocr_attempts": 0,
                "review": "passed",
                "protected_sources": "passed",
                "media_thumbnail": "passed",
            }
        )
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("seed", "append", "verify"))
    action = parser.parse_args().action
    {"seed": seed, "append": append, "verify": verify}[action]()
