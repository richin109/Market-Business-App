from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
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
from mbs.models import Receipt, ReceiptSource, ReceiptUpload
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

    assert result.file_count == 2
    assert result.row_counts["receipts"] == 1
    assert result.row_counts["receipt_sources"] == 2
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
    finally:
        engine.dispose()


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
            next(storage.rglob("*.png")).unlink()
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
