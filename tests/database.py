from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

_databases: ContextVar[dict[Path, URL]] = ContextVar("test_databases")


def postgres_test_url(path: Path) -> str:
    databases = _databases.get()
    if path not in databases:
        configured = os.environ.get("MBS_TEST_DATABASE_URL")
        if not configured:
            raise RuntimeError("Run docker compose run --rm test, or set MBS_TEST_DATABASE_URL")
        base = make_url(configured)
        if base.get_backend_name() != "postgresql" or base.database not in {
            "mbs_migration_test",
            "mbs_test",
        }:
            raise RuntimeError("MBS_TEST_DATABASE_URL must target mbs_test or mbs_migration_test")
        base = base.set(drivername="postgresql+psycopg")
        name = f"mbs_test_{uuid4().hex}"
        engine = create_engine(base, isolation_level="AUTOCOMMIT")
        try:
            with engine.connect() as connection:
                connection.execute(text(f'CREATE DATABASE "{name}"'))
        finally:
            engine.dispose()
        databases[path] = base.set(database=name)
    return databases[path].render_as_string(hide_password=False)


@contextmanager
def isolated_test_databases() -> Iterator[None]:
    databases: dict[Path, URL] = {}
    token = _databases.set(databases)
    try:
        yield
    finally:
        _databases.reset(token)
        for url in databases.values():
            engine = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
            try:
                with engine.connect() as connection:
                    connection.execute(text(f'DROP DATABASE "{url.database}" WITH (FORCE)'))
            finally:
                engine.dispose()
