from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.database import configure_application_test_database_url, isolated_test_databases

configure_application_test_database_url()


@pytest.fixture(autouse=True)
def isolate_databases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("RECEIPT_STORAGE_PATH", str(tmp_path / "protected-files"))
    with isolated_test_databases():
        yield
