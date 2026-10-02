import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.database import isolated_test_databases

os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get("MBS_TEST_DATABASE_URL", "postgresql+psycopg://localhost/mbs_test"),
)


@pytest.fixture(autouse=True)
def isolate_databases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("RECEIPT_STORAGE_PATH", str(tmp_path / "protected-files"))
    with isolated_test_databases():
        yield
