from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from PIL import Image, ImageDraw
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from mbs import backup as backup_module
from mbs.backup import (
    BackupError,
    create_backup,
    restore_backup,
    verify_backup,
    verify_restored,
)
from mbs.media_assets import MediaAssetService
from mbs.models import MediaAsset, Receipt, ReceiptSource, ReceiptUpload
from mbs.receipts.ocr import normalize_receipt
from mbs.receipts.persistence import create_upload, persist_extracted_receipt
from mbs.receipts.storage import LocalProtectedFileStore
from tests.database import postgres_test_url

SOURCES = {
    "image/png": b"synthetic-png-bytes",
    "application/pdf": b"%PDF-1.7 synthetic order page two",
}


def _migrate(path: Path) -> str:
    url = postgres_test_url(path)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    return url


def _seed(url: str, storage: Path) -> str:
    """One receipt with two protected source files, like a multi-file order (RM-022)."""
    store = LocalProtectedFileStore(storage)
    engine = create_engine(url)
    with Session(engine) as session:
        uploads = []
        for media_type, content in SOURCES.items():
            digest = hashlib.sha256(content).hexdigest()
            key = store.save(digest, content, media_type)
            uploads.append(create_upload(session, digest, key, media_type, len(content)))
        receipt = persist_extracted_receipt(
            session,
            normalize_receipt(
                {
                    "receipt": {
                        "store": "Synthetic Backup Market",
                        "date": "2026-09-30",
                        "time": "09:30:00",
                        "transaction_number": "BK-1",
                        "total": "3.00",
                    },
                    "items": [{"description": "Eggs", "line_total": "3.00"}],
                }
            ),
            uploads[0],
        )
        session.add(
            ReceiptSource(
                receipt_pk=receipt.receipt_pk,
                upload_pk=uploads[1].upload_pk,
                source_sha256=uploads[1].source_sha256,
                association_kind="SUPPLEMENT",
                raw_ocr_document={},
                extracted_document={},
            )
        )
        image = Image.new("RGB", (160, 120), "white")
        ImageDraw.Draw(image).rectangle((12, 12, 92, 108), fill=(40, 110, 70))
        image_bytes = BytesIO()
        image.save(image_bytes, format="PNG")
        media_service = MediaAssetService(store)
        asset = media_service.stage(session, image_bytes.getvalue(), "image/png", None)
        media_service.promote(session, asset.asset_sha256)
        session.commit()
        receipt_pk = receipt.receipt_pk
    engine.dispose()
    return receipt_pk


def test_rm_016_backup_restores_rows_and_files_with_matching_checksums(tmp_path: Path) -> None:
    source_url = _migrate(tmp_path / "source.db")
    source_storage = tmp_path / "source-files"
    receipt_pk = _seed(source_url, source_storage)
    backup_dir = tmp_path / "backup"

    result = create_backup(source_url, source_storage, backup_dir)
    manifest = verify_backup(backup_dir)

    assert result.file_count == 4
    assert result.row_counts["receipts"] == 1
    assert result.row_counts["receipt_sources"] == 2
    assert result.row_counts["media_assets"] == 1
    assert manifest["row_counts"] == result.row_counts

    restored_url = postgres_test_url(tmp_path / "restored")
    restored_storage = tmp_path / "restored-files"
    assert restore_backup(backup_dir, restored_url, restored_storage) == []

    # Restart survival (RM-010): the restored data is readable with no OCR involved.
    engine = create_engine(restored_url)
    try:
        with Session(engine) as session:
            receipt = session.get(Receipt, receipt_pk)
            assert receipt is not None and receipt.transaction_number == "BK-1"
            sources = session.scalars(
                select(ReceiptSource).where(ReceiptSource.receipt_pk == receipt_pk)
            ).all()
            assert len(sources) == 2
            for upload in session.scalars(select(ReceiptUpload)):
                restored_bytes = (restored_storage / upload.file_key).read_bytes()
                assert hashlib.sha256(restored_bytes).hexdigest() == upload.source_sha256
            assets = session.scalars(select(MediaAsset)).all()
            assert len(assets) == 1
            asset = assets[0]
            variants = (
                (asset.original_file_key, asset.asset_sha256),
                (asset.display_file_key, Path(asset.display_file_key).stem),
                (asset.thumbnail_file_key, Path(asset.thumbnail_file_key).stem),
            )
            for key, expected_sha256 in variants:
                restored_bytes = (restored_storage / key).read_bytes()
                assert hashlib.sha256(restored_bytes).hexdigest() == expected_sha256
    finally:
        engine.dispose()


def test_rm_025_order_sets_preserve_all_receipt_source_lineage_on_restore(
    tmp_path: Path,
) -> None:
    source_url = _migrate(tmp_path / "multi-order-source")
    source_storage = tmp_path / "multi-order-files"
    file_store = LocalProtectedFileStore(source_storage)
    engine = create_engine(source_url)
    expected_receipts: dict[str, str] = {}
    expected_uploads: dict[str, tuple[str, str]] = {}
    try:
        with Session(engine) as session:
            for version, first_order in ((1, 1), (2, 6), (3, 11)):
                for order_number in range(first_order, first_order + 5):
                    transaction_number = f"SYNTHETIC-V{version}-{order_number:02d}"
                    content = f"%PDF-1.7 synthetic version {version}, order {order_number}".encode()
                    digest = hashlib.sha256(content).hexdigest()
                    file_key = file_store.save(digest, content, "application/pdf")
                    upload = create_upload(
                        session, digest, file_key, "application/pdf", len(content)
                    )
                    receipt = persist_extracted_receipt(
                        session,
                        normalize_receipt(
                            {
                                "receipt": {
                                    "store": "Synthetic Versioned Market",
                                    "date": "2026-10-02",
                                    "time": f"10:{order_number:02d}:00",
                                    "transaction_number": transaction_number,
                                    "total": "1.00",
                                },
                                "items": [
                                    {
                                        "description": f"Synthetic item {order_number:02d}",
                                        "line_total": "1.00",
                                    }
                                ],
                            }
                        ),
                        upload,
                        increment_ocr_attempts=False,
                    )
                    expected_receipts[receipt.receipt_pk] = transaction_number
                    expected_uploads[upload.upload_pk] = (file_key, digest)
            session.commit()
    finally:
        engine.dispose()

    backup_dir = tmp_path / "multi-order-backup"
    result = create_backup(source_url, source_storage, backup_dir)
    assert result.row_counts["receipts"] == 15
    assert result.row_counts["receipt_sources"] == 15

    restored_url = postgres_test_url(tmp_path / "multi-order-restored")
    restored_storage = tmp_path / "multi-order-restored-files"
    assert restore_backup(backup_dir, restored_url, restored_storage) == []

    restored_engine = create_engine(restored_url)
    try:
        with Session(restored_engine) as session:
            receipts = session.scalars(
                select(Receipt).where(Receipt.receipt_pk.in_(expected_receipts))
            ).all()
            assert {receipt.receipt_pk: receipt.transaction_number for receipt in receipts} == (
                expected_receipts
            )
            sources = session.scalars(
                select(ReceiptSource).where(ReceiptSource.receipt_pk.in_(expected_receipts))
            ).all()
            assert len(sources) == 15
            assert {source.upload_pk for source in sources} == set(expected_uploads)
            uploads = session.scalars(
                select(ReceiptUpload).where(ReceiptUpload.upload_pk.in_(expected_uploads))
            ).all()
            assert all(upload.ocr_attempts == 0 for upload in uploads)
            for upload_pk, (file_key, digest) in expected_uploads.items():
                content = (restored_storage / file_key).read_bytes()
                assert hashlib.sha256(content).hexdigest() == digest
                assert any(
                    source.upload_pk == upload_pk and source.source_sha256 == digest
                    for source in sources
                )
    finally:
        restored_engine.dispose()


def test_backup_counts_and_dump_share_snapshot_during_concurrent_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = _migrate(tmp_path / "snapshot-source")
    storage = tmp_path / "snapshot-files"
    _seed(url, storage)
    original_run = backup_module._run_postgres_tool

    def write_after_snapshot(arguments: list[str], connection_url: URL) -> None:
        if arguments[0] == "pg_dump":
            writer = create_engine(url)
            try:
                with Session(writer) as session:
                    create_upload(session, "a" * 64, "receipts/synthetic-later.png", "image/png", 1)
                    session.commit()
            finally:
                writer.dispose()
        original_run(arguments, connection_url)

    monkeypatch.setattr(backup_module, "_run_postgres_tool", write_after_snapshot)
    backup_dir = tmp_path / "snapshot-backup"
    result = create_backup(url, storage, backup_dir)
    assert result.row_counts["receipt_uploads"] == 2
    reader = create_engine(url)
    try:
        with Session(reader) as session:
            assert session.scalar(select(func.count()).select_from(ReceiptUpload)) == 3
    finally:
        reader.dispose()
    restored_url = postgres_test_url(tmp_path / "snapshot-restored")
    assert restore_backup(backup_dir, restored_url, tmp_path / "snapshot-restored-files") == []


def test_verify_backup_fails_on_corruption_or_missing_manifest(tmp_path: Path) -> None:
    url = _migrate(tmp_path / "source.db")
    storage = tmp_path / "files"
    _seed(url, storage)
    backup_dir = tmp_path / "backup"
    create_backup(url, storage, backup_dir)

    victim = next((backup_dir / "files").rglob("*.pdf"))
    victim.write_bytes(b"tampered")
    with pytest.raises(BackupError, match="file: receipts/"):
        verify_backup(backup_dir)

    restored_storage = tmp_path / "restored-files"
    restored_url = postgres_test_url(tmp_path / "corrupt-target")
    with pytest.raises(BackupError):
        restore_backup(backup_dir, restored_url, restored_storage)
    engine = create_engine(restored_url)
    try:
        assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()
    assert not restored_storage.exists()

    (backup_dir / "manifest.json").unlink()
    with pytest.raises(BackupError, match="incomplete"):
        verify_backup(backup_dir)


def test_backup_and_restore_refuse_to_overwrite_existing_data(tmp_path: Path) -> None:
    url = _migrate(tmp_path / "source.db")
    storage = tmp_path / "files"
    _seed(url, storage)
    backup_dir = tmp_path / "backup"
    create_backup(url, storage, backup_dir)

    with pytest.raises(BackupError, match="not empty"):
        create_backup(url, storage, backup_dir)
    with pytest.raises(BackupError, match="not empty"):
        restore_backup(backup_dir, postgres_test_url(tmp_path / "new"), storage)
    with pytest.raises(BackupError, match="already exists"):
        restore_backup(backup_dir, url, tmp_path / "other-files")


def test_verify_restored_reports_missing_and_mismatched_files(tmp_path: Path) -> None:
    url = _migrate(tmp_path / "source.db")
    storage = tmp_path / "files"
    _seed(url, storage)
    counts = {"receipt_uploads": 2}
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            assert verify_restored(session, storage, counts) == []
            (next(storage.rglob("*.pdf"))).write_bytes(b"changed")
            png_upload = next(
                upload
                for upload in session.scalars(select(ReceiptUpload))
                if upload.media_type == "image/png"
            )
            (storage / png_upload.file_key).unlink()
            problems = verify_restored(session, storage, {"receipt_uploads": 3})
    finally:
        engine.dispose()

    assert any("checksum mismatch" in problem for problem in problems)
    assert any("source file missing" in problem for problem in problems)
    assert any("row count receipt_uploads: expected 3, found 2" in p for p in problems)


def test_manifest_with_unsafe_paths_or_garbage_is_rejected(tmp_path: Path) -> None:
    url = _migrate(tmp_path / "source.db")
    storage = tmp_path / "files"
    _seed(url, storage)
    backup_dir = tmp_path / "backup"
    create_backup(url, storage, backup_dir)
    manifest_path = backup_dir / "manifest.json"
    original = manifest_path.read_text(encoding="utf-8")

    manifest_path.write_text(original.replace("database.pgdump", "../database.pgdump"))
    with pytest.raises(BackupError, match="invalid"):
        verify_backup(backup_dir)
    manifest_path.write_text(original.replace('"receipts/', '"../receipts/', 1))
    with pytest.raises(BackupError, match="invalid"):
        verify_backup(backup_dir)
    manifest_path.write_text("{not json")
    with pytest.raises(BackupError, match="unreadable"):
        verify_backup(backup_dir)


def test_manifest_rejects_symlinked_backup_file(tmp_path: Path) -> None:
    url = _migrate(tmp_path / "source.db")
    storage = tmp_path / "files"
    _seed(url, storage)
    backup_dir = tmp_path / "backup"
    create_backup(url, storage, backup_dir)

    external_file = tmp_path / "outside-backup-root.bin"
    external_file.write_bytes(b"synthetic external content")
    symlinked_file = backup_dir / "files" / "untrusted-link.bin"
    symlinked_file.symlink_to(external_file)
    manifest_path = backup_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["untrusted-link.bin"] = hashlib.sha256(
        external_file.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupError, match="symbolic link"):
        verify_backup(backup_dir)

    symlinked_file.unlink()
    manifest["files"].pop("untrusted-link.bin")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    symlinked_file.symlink_to(external_file)
    with pytest.raises(BackupError, match="symbolic link"):
        verify_backup(backup_dir)

    symlinked_file.unlink()
    (backup_dir / "files" / "unlisted.bin").write_bytes(b"synthetic unlisted content")
    with pytest.raises(BackupError, match="do not match the manifest"):
        verify_backup(backup_dir)


def test_manifest_rejects_symlinked_database_dump(tmp_path: Path) -> None:
    url = _migrate(tmp_path / "source.db")
    storage = tmp_path / "files"
    _seed(url, storage)
    backup_dir = tmp_path / "backup"
    create_backup(url, storage, backup_dir)

    external_dump = tmp_path / "outside-backup-root.pgdump"
    external_dump.write_bytes((backup_dir / "database.pgdump").read_bytes())
    (backup_dir / "database.pgdump").unlink()
    (backup_dir / "database.pgdump").symlink_to(external_dump)

    with pytest.raises(BackupError, match="database dump"):
        verify_backup(backup_dir)


def test_failed_file_restore_removes_partial_state_so_retry_is_possible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = _migrate(tmp_path / "source.db")
    storage = tmp_path / "files"
    _seed(url, storage)
    backup_dir = tmp_path / "backup"
    create_backup(url, storage, backup_dir)
    restored_url = postgres_test_url(tmp_path / "restored")
    restored_storage = tmp_path / "restored-files"

    def fail_copy(source: Path, target: Path) -> dict[str, str]:
        target.mkdir(parents=True)
        (target / "partial").write_bytes(b"x")
        raise OSError("disk full")

    monkeypatch.setattr("mbs.backup._copy_tree", fail_copy)
    with pytest.raises(OSError, match="disk full"):
        restore_backup(backup_dir, restored_url, restored_storage)
    monkeypatch.undo()

    engine = create_engine(restored_url)
    try:
        assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()
    assert list(restored_storage.iterdir()) == []
    assert restore_backup(backup_dir, restored_url, restored_storage) == []
