from __future__ import annotations

import os
import tempfile
from pathlib import Path


def receipt_storage_root() -> Path:
    configured_path = os.environ.get("RECEIPT_STORAGE_PATH", ".local/receipts")
    return Path(configured_path).expanduser().resolve()


class LocalProtectedFileStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def save(self, source_sha256: str, source: bytes, media_type: str) -> str:
        relative_key = self._final_key(source_sha256, media_type)
        target = self._resolve(relative_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() == source:
                return relative_key.as_posix()
            raise FileExistsError(f"Protected file content mismatch: {relative_key}")
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(source)
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, target)
        except OSError:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
        return relative_key.as_posix()

    def stage(self, source_sha256: str, source: bytes, media_type: str) -> str:
        extension = self._extension(media_type)
        relative_key = Path(".staging") / f"{source_sha256}{extension}"
        target = self._resolve(relative_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() == source:
                return relative_key.as_posix()
            raise FileExistsError(f"Staged file content mismatch: {relative_key}")
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(source)
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, target)
        except OSError:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
        return relative_key.as_posix()

    def key_for(self, source_sha256: str, media_type: str) -> str:
        return self._final_key(source_sha256, media_type).as_posix()

    def promote(self, staging_key: str, source_sha256: str, media_type: str) -> str:
        staging_path = self._resolve(Path(staging_key))
        source = staging_path.read_bytes() if staging_path.exists() else None
        final_key = self._final_key(source_sha256, media_type)
        final_path = self._resolve(final_key)
        if source is None:
            if final_path.exists():
                return final_key.as_posix()
            raise FileNotFoundError(f"Staged receipt source is missing: {staging_key}")
        self.save(source_sha256, source, media_type)
        staging_path.unlink(missing_ok=True)
        return final_key.as_posix()

    def read(self, file_key: str) -> bytes:
        return self._resolve(Path(file_key)).read_bytes()

    def delete(self, file_key: str) -> None:
        self._resolve(Path(file_key)).unlink(missing_ok=True)

    def _resolve(self, relative_key: Path) -> Path:
        target = (self._root / relative_key).resolve()
        if self._root not in target.parents:
            raise ValueError("Protected file path escaped the configured store")
        return target

    @staticmethod
    def _extension(media_type: str) -> str:
        try:
            return {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/webp": ".webp",
                "application/pdf": ".pdf",
            }[media_type]
        except KeyError as error:
            raise ValueError(f"Unsupported media type: {media_type}") from error

    @classmethod
    def _final_key(cls, source_sha256: str, media_type: str) -> Path:
        return Path("receipts") / source_sha256[:2] / f"{source_sha256}{cls._extension(media_type)}"
