from __future__ import annotations

from collections.abc import Iterator

from celery.signals import worker_process_init
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from mbs.database_config import database_url as database_url

engine = create_engine(database_url(), pool_pre_ping=True, hide_parameters=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def reset_worker_database_connections(**kwargs: object) -> None:
    engine.dispose(close=False)


worker_process_init.connect(reset_worker_database_connections)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
