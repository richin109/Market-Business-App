from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from mbs.models import Setting


def test_baseline_migration_creates_seeded_settings_and_logs(tmp_path: Path) -> None:
    database_path = tmp_path / "baseline.db"
    engine = create_engine(f"sqlite:///{database_path}")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.upgrade(config, "head")

    tables = inspect(engine).get_table_names()
    assert {"tbl_settings", "tbl_audit_log", "tbl_error_log"}.issubset(tables)
    with Session(engine) as session:
        settings = session.scalars(select(Setting)).all()

    assert len(settings) == 6
    assert next(setting for setting in settings if setting.key == "currency").value == "USD"
