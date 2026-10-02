import tempfile
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from mbs.receipts.storage import (
    ClamAVScanner,
    LocalProtectedFileStore,
    ScanStatus,
    receipt_storage_root,
)


def test_receipt_storage_root_has_one_default_and_honors_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RECEIPT_STORAGE_PATH", raising=False)

    assert receipt_storage_root() == tmp_path / ".local" / "receipts"

    configured_path = tmp_path / "shared-receipts"
    monkeypatch.setenv("RECEIPT_STORAGE_PATH", str(configured_path))
    assert receipt_storage_root() == configured_path


def test_clamav_adapter_maps_connection_failure_to_unavailable() -> None:
    def unavailable(source: bytes) -> bool:
        raise OSError("clamd unavailable")

    assert ClamAVScanner(unavailable).scan(b"synthetic") is ScanStatus.UNAVAILABLE


def test_protected_file_store_is_idempotent_for_identical_content(tmp_path: Path) -> None:
    store = LocalProtectedFileStore(tmp_path)
    source = b"synthetic protected bytes"
    source_sha256 = "a" * 64

    first_key = store.save(source_sha256, source, "image/png")
    retry_key = store.save(source_sha256, source, "image/png")

    assert first_key == retry_key
    assert store.read(first_key) == source

    with pytest.raises(FileExistsError, match="content mismatch"):
        store.save(source_sha256, b"different bytes", "image/png")


def test_protected_file_store_cleans_temporary_file_after_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalProtectedFileStore(tmp_path)

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("synthetic promotion failure")

    monkeypatch.setattr("mbs.receipts.storage.os.replace", fail_replace)
    with pytest.raises(OSError, match="synthetic promotion failure"):
        store.save("b" * 64, b"synthetic source", "image/png")

    assert not any(path.is_file() for path in tmp_path.rglob("*"))


@pytest.mark.parametrize("operation", ["save", "stage"])
def test_protected_file_store_cleans_temporary_file_after_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    store = LocalProtectedFileStore(tmp_path)
    real_named_temporary_file = tempfile.NamedTemporaryFile

    class FailingWrite:
        def __init__(self, **kwargs: Any) -> None:
            self.file = real_named_temporary_file(**kwargs)

        def __enter__(self) -> "FailingWrite":
            self.file.__enter__()
            return self

        @property
        def name(self) -> str:
            return self.file.name

        def write(self, source: bytes) -> None:
            raise OSError("synthetic write failure")

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            self.file.__exit__(exc_type, exc, traceback)

    monkeypatch.setattr("mbs.receipts.storage.tempfile.NamedTemporaryFile", FailingWrite)
    with pytest.raises(OSError, match="synthetic write failure"):
        getattr(store, operation)("c" * 64, b"synthetic source", "image/png")

    assert not any(path.is_file() for path in tmp_path.rglob("*"))
