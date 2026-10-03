from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from mbs.database_config import database_url as configured_database_url
from mbs.errors import BackupError as BackupError
from mbs.receipts.storage import receipt_storage_root
from mbs.repositories.backups import COUNTED_MODELS as COUNTED_MODELS
from mbs.repositories.backups import BackupRepository

MANIFEST_NAME = "manifest.json"
FILES_DIR = "files"
MANIFEST_VERSION = 1
repository = BackupRepository()


@dataclass(frozen=True)
class BackupResult:
    path: Path
    file_count: int
    row_counts: dict[str, int]


def create_backup(database_url: str, storage_root: Path, destination: Path) -> BackupResult:
    """Write a checksummed database dump and protected-file copy; the manifest is written last."""
    if destination.exists() and any(destination.iterdir()):
        raise BackupError(f"Backup destination is not empty: {destination}")
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise BackupError("The backup adapter supports PostgreSQL only")
    url = url.set(drivername="postgresql+psycopg")
    destination.mkdir(parents=True, exist_ok=True)
    os.chmod(destination, 0o700)
    database_name, counts = _dump_database(url, destination)
    files = _copy_tree(storage_root, destination / FILES_DIR)
    manifest = {
        "version": MANIFEST_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "database_kind": url.get_backend_name(),
        "database_file": database_name,
        "database_sha256": _sha256(destination / database_name),
        "files": files,
        "row_counts": counts,
    }
    temporary = destination / f"{MANIFEST_NAME}.tmp"
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, destination / MANIFEST_NAME)
    return BackupResult(destination, len(files), counts)


def verify_backup(backup_dir: Path) -> dict[str, object]:
    """Return the manifest after proving every recorded checksum still matches."""
    manifest = _read_manifest(backup_dir)
    problems: list[str] = []
    database_file = backup_dir / str(manifest["database_file"])
    if (
        database_file.is_symlink()
        or not database_file.is_file()
        or _sha256(database_file) != manifest["database_sha256"]
    ):
        problems.append(f"database dump: {manifest['database_file']}")
    files = manifest["files"]
    if not isinstance(files, dict):
        raise BackupError("Backup manifest is invalid")
    files_root = backup_dir / FILES_DIR
    actual_files: set[str] = set()
    if files_root.is_symlink():
        raise BackupError("Backup contains a symbolic link")
    if files_root.is_dir():
        for path in files_root.rglob("*"):
            if path.is_symlink():
                raise BackupError("Backup contains a symbolic link")
            if path.is_file():
                actual_files.add(path.relative_to(files_root).as_posix())
    if actual_files != set(files):
        raise BackupError("Backup files do not match the manifest")
    for relative, digest in files.items():
        copied = files_root / relative
        if not copied.is_file() or _sha256(copied) != digest:
            problems.append(f"file: {relative}")
    if problems:
        raise BackupError("Backup verification failed: " + "; ".join(sorted(problems)))
    return manifest


def restore_backup(backup_dir: Path, database_url: str, storage_root: Path) -> list[str]:
    """Restore into an empty target, then verify it; returns problems (empty when clean)."""
    manifest = verify_backup(backup_dir)
    url = make_url(database_url)
    if manifest["database_kind"] != url.get_backend_name():
        raise BackupError("Backup and target database engines differ")
    if url.get_backend_name() != "postgresql":
        raise BackupError("The backup adapter supports PostgreSQL only")
    url = url.set(drivername="postgresql+psycopg")
    if storage_root.exists() and any(storage_root.iterdir()):
        raise BackupError(f"Restore target storage is not empty: {storage_root}")
    _ensure_empty_database(url)
    try:
        _copy_tree(backup_dir / FILES_DIR, storage_root)
        _restore_database(url, backup_dir / str(manifest["database_file"]))
    except BaseException:
        _discard_partial_restore(storage_root)
        raise
    with repository.verification_session(url) as session:
        expected = manifest["row_counts"]
        if not isinstance(expected, dict):
            raise BackupError("Backup manifest is invalid")
        return verify_restored(session, storage_root, expected)


def verify_restored(
    session: Session, storage_root: Path, expected_counts: dict[str, int]
) -> list[str]:
    """Check row counts and that every referenced protected file exists with the right bytes."""
    problems: list[str] = []
    actual = _row_counts(session)
    for name, count in expected_counts.items():
        if actual.get(name) != count:
            problems.append(f"row count {name}: expected {count}, found {actual.get(name)}")

    def present(key: str) -> bool:
        return (storage_root / key).is_file()

    for upload in repository.uploads(session):
        candidates = [key for key in (upload.file_key, upload.staging_file_key) if key]
        found = next((key for key in candidates if present(key)), None)
        if found is None:
            problems.append(f"upload {upload.upload_pk}: source file missing")
        elif _sha256(storage_root / found) != upload.source_sha256:
            problems.append(f"upload {upload.upload_pk}: source checksum mismatch")
    for asset in repository.assets(session):
        if asset.ingest_status == "READY":
            keys = [asset.original_file_key, asset.display_file_key, asset.thumbnail_file_key]
        else:
            keys = [str(entry["staging_key"]) for entry in asset.staging_files or []]
        for key in keys:
            if not present(key):
                problems.append(f"media asset {asset.asset_sha256}: missing {key}")
    return problems


def _read_manifest(backup_dir: Path) -> dict[str, object]:
    path = backup_dir / MANIFEST_NAME
    if not path.is_file():
        raise BackupError("Backup manifest is missing; the backup is incomplete")
    try:
        manifest: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BackupError("Backup manifest is unreadable") from error
    if not isinstance(manifest, dict) or manifest.get("version") != MANIFEST_VERSION:
        raise BackupError("Unsupported backup manifest version")
    database_file = manifest.get("database_file")
    files = manifest.get("files")
    if not isinstance(database_file, str) or Path(database_file).name != database_file:
        raise BackupError("Backup manifest is invalid")
    if not isinstance(files, dict) or any(
        Path(relative).is_absolute() or ".." in Path(relative).parts for relative in files
    ):
        raise BackupError("Backup manifest is invalid")
    return manifest


def _row_counts(session: Session) -> dict[str, int]:
    return repository.row_counts(session)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_tree(source: Path, target: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    if not source.is_dir():
        return checksums
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise BackupError(f"Symbolic links are not supported in protected storage: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        checksums[relative.as_posix()] = _sha256(destination)
        if checksums[relative.as_posix()] != _sha256(path):
            raise BackupError(f"File changed while copying: {relative.as_posix()}")
    return checksums


def _dump_database(url: URL, destination: Path) -> tuple[str, dict[str, int]]:
    """Dump the database and count rows from the same consistent view the dump used."""
    backend = url.get_backend_name()
    if backend == "postgresql":
        return repository.dump_postgres(url, destination, _run_postgres_tool)
    raise BackupError(f"Unsupported database engine: {backend}")


def _ensure_empty_database(url: URL) -> None:
    repository.ensure_empty_database(url)


def _restore_database(url: URL, dump: Path) -> None:
    _ensure_empty_database(url)
    _run_postgres_tool(
        [
            "pg_restore",
            "--no-owner",
            "--no-acl",
            "--single-transaction",
            "--exit-on-error",
            str(dump),
        ],
        url,
    )


def _discard_partial_restore(storage_root: Path) -> None:
    if storage_root.is_dir():
        for child in storage_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()


def _run_postgres_tool(arguments: list[str], url: URL) -> None:
    command = [
        arguments[0],
        "--host",
        url.host or "localhost",
        "--port",
        str(url.port or 5432),
        "--username",
        url.username or "",
        "--dbname",
        url.database or "",
        *arguments[1:],
    ]
    environment = dict(os.environ)
    environment["PGPASSWORD"] = url.password or ""
    for option, variable in {
        "options": "PGOPTIONS",
        "sslmode": "PGSSLMODE",
        "sslrootcert": "PGSSLROOTCERT",
        "sslcert": "PGSSLCERT",
        "sslkey": "PGSSLKEY",
    }.items():
        value = url.query.get(option)
        if isinstance(value, str):
            environment[variable] = value
    try:
        subprocess.run(command, check=True, env=environment, capture_output=True)  # noqa: S603
    except FileNotFoundError as error:
        raise BackupError(f"{arguments[0]} is not installed or not on PATH") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode(errors="replace").strip()[:500]
        raise BackupError(f"{arguments[0]} failed: {detail}") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mbs.backup")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "verify", "restore"):
        commands.add_parser(name).add_argument("path", type=Path)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "verify":
            verify_backup(arguments.path)
            print("Backup checksums verified")
            return 0
        database_url = configured_database_url()
        storage_root = receipt_storage_root()
        if arguments.command == "create":
            result = create_backup(database_url, storage_root, arguments.path)
            print(f"Backup written: {result.file_count} files, rows {result.row_counts}")
            return 0
        problems = restore_backup(arguments.path, database_url, storage_root)
    except (RuntimeError, ValueError) as error:
        print(f"Backup failed: {error}")
        return 1
    for problem in problems:
        print(f"Restore problem: {problem}")
    print("Restore verified" if not problems else "Restore verification FAILED")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
