import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import String, create_engine, inspect, select
from sqlalchemy.orm import Session

from mbs.models import Base, Setting
from mbs.settings import read_setting
from tests.database import (
    configure_application_test_database_url,
    configured_test_database_url,
    postgres_test_url,
)


def test_test_bootstrap_overrides_inherited_application_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_url = "postgresql+psycopg://synthetic:synthetic@localhost/mbs_test"
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://app:secret@localhost/production")
    monkeypatch.setenv("MBS_TEST_DATABASE_URL", test_url)

    assert configure_application_test_database_url() == test_url
    assert os.environ["DATABASE_URL"] == test_url


@pytest.mark.parametrize(
    "value",
    [
        "postgresql+psycopg://synthetic:synthetic@localhost/production",
        "mysql+pymysql://synthetic:synthetic@localhost/mbs_test",
    ],
)
def test_configured_test_database_url_rejects_non_test_targets(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("MBS_TEST_DATABASE_URL", value)

    with pytest.raises(RuntimeError, match="must target mbs_test or mbs_migration_test"):
        configured_test_database_url()

    with pytest.raises(RuntimeError, match="must target mbs_test or mbs_migration_test"):
        configure_application_test_database_url()


@pytest.mark.parametrize("value", ["mysql+pymysql://localhost/mbs", "mssql+pyodbc://localhost/mbs"])
def test_database_url_preserves_other_sqlalchemy_backends(value: str) -> None:
    from mbs.database_config import validate_database_url

    assert validate_database_url(value) == value


def test_database_url_selects_psycopg() -> None:
    from mbs.database_config import validate_database_url

    assert validate_database_url("postgresql://localhost/mbs") == (
        "postgresql+psycopg://localhost/mbs"
    )


def test_database_fields_encode_password_and_explicit_url_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.engine import make_url

    from mbs.database_config import database_url

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_HOST", "localhost")
    monkeypatch.setenv("DATABASE_NAME", "mbs_test")
    monkeypatch.setenv("DATABASE_USER", "synthetic_user")
    synthetic_credential = "synthetic:%@/password"
    monkeypatch.setenv("DATABASE_PASSWORD", synthetic_credential)
    assert make_url(database_url()).password == synthetic_credential
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://localhost/other")
    assert database_url() == "mysql+pymysql://localhost/other"


def test_database_configuration_fails_clearly_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mbs.database_config import database_url

    for key in ("DATABASE_URL", "DATABASE_HOST", "DATABASE_NAME"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(RuntimeError, match="Set DATABASE_URL"):
        database_url()


def test_celery_child_discards_inherited_database_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    from mbs import db

    dispose = Mock()
    monkeypatch.setattr(db.engine, "dispose", dispose)
    db.reset_worker_database_connections()
    dispose.assert_called_once_with(close=False)


def _documented_settings_catalog() -> dict[str, str | None]:
    capability = Path(__file__).parents[1] / "plan/capabilities/09-settings-governance.md"
    lines = capability.read_text(encoding="utf-8").splitlines()
    catalog: dict[str, str | None] = {}
    in_catalog = False
    for line in lines:
        if line.startswith("## Feature 9.1"):
            in_catalog = True
            continue
        if in_catalog and line.startswith("## "):
            break
        if in_catalog and line.startswith("| `"):
            key, default = (part.strip() for part in line.strip("| ").split("|", maxsplit=1))
            catalog[key.strip("`")] = None if default.strip("`") == "NULL" else default.strip("`")
    assert catalog
    return catalog


def test_migrated_column_types_and_nullability_match_orm_metadata(tmp_path: Path) -> None:
    url = postgres_test_url(tmp_path / "schema-parity")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        mismatches = []
        for table in Base.metadata.sorted_tables:
            actual = {
                column["name"]: column for column in inspector.get_columns(table.name)
            }
            for column in table.columns:
                expected = column.type.compile(dialect=engine.dialect)
                if actual[column.name]["type"].compile(dialect=engine.dialect) != expected:
                    mismatches.append(f"{table.name}.{column.name}: expected {expected}")
                if actual[column.name]["nullable"] != column.nullable:
                    mismatches.append(f"{table.name}.{column.name}: nullability differs")
        assert mismatches == []
        version_column = inspector.get_columns("alembic_version")[0]
        assert isinstance(version_column["type"], String)
        assert version_column["type"].length is not None
        assert version_column["type"].length >= 128
    finally:
        engine.dispose()


def _assert_settings_match_catalog(
    actual: dict[str, str | None], expected: dict[str, str | None]
) -> None:
    assert set(actual) == set(expected), "settings include missing or undocumented keys"
    assert actual == expected


def test_baseline_migration_creates_seeded_settings_and_logs(tmp_path: Path) -> None:
    database_path = tmp_path / "baseline.db"
    engine = create_engine(postgres_test_url(database_path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(database_path).replace("%", "%%"))

    command.upgrade(config, "head")

    tables = inspect(engine).get_table_names()
    assert {"tbl_settings", "tbl_audit_log", "tbl_error_log"}.issubset(tables)
    with Session(engine) as session:
        settings = session.scalars(select(Setting)).all()

    actual = {setting.key: setting.value for setting in settings}
    catalog = _documented_settings_catalog()
    _assert_settings_match_catalog(actual, catalog)
    assert actual["receipt_source_retention_days"] is None
    assert actual["receipt_raw_retention_days"] is None
    with pytest.raises(AssertionError, match="undocumented"):
        _assert_settings_match_catalog({**actual, "undocumented_test_key": "value"}, catalog)
    with Session(engine) as session:
        assert read_setting(session, "currency") == "USD"
        assert read_setting(session, "receipt_source_retention_days") is None


def test_alembic_uses_database_url_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "database-url.db"
    monkeypatch.setenv("DATABASE_URL", postgres_test_url(database_path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    command.upgrade(config, "head")

    engine = create_engine(postgres_test_url(database_path))
    try:
        assert "tbl_receipts" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_explicit_alembic_url_takes_precedence_over_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured_path = tmp_path / "configured-url.db"
    environment_path = tmp_path / "environment-url.db"
    monkeypatch.setenv("DATABASE_URL", postgres_test_url(environment_path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(configured_path).replace("%", "%%"))

    command.upgrade(config, "head")

    engine = create_engine(postgres_test_url(configured_path))
    try:
        assert "tbl_receipts" in inspect(engine).get_table_names()
        other_engine = create_engine(postgres_test_url(environment_path))
        try:
            assert inspect(other_engine).get_table_names() == []
        finally:
            other_engine.dispose()
    finally:
        engine.dispose()
