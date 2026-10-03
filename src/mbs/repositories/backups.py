from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from mbs.errors import BackupError
from mbs.models import MediaAsset, Receipt, ReceiptItem, ReceiptSource, ReceiptUpload

COUNTED_MODELS = {
    "receipts": Receipt,
    "receipt_items": ReceiptItem,
    "receipt_sources": ReceiptSource,
    "receipt_uploads": ReceiptUpload,
    "media_assets": MediaAsset,
}


class BackupRepository:
    def row_counts(self, session: Session) -> dict[str, int]:
        return {
            name: int(session.scalar(select(func.count()).select_from(model)) or 0)
            for name, model in COUNTED_MODELS.items()
        }

    def uploads(self, session: Session) -> list[ReceiptUpload]:
        return list(session.scalars(select(ReceiptUpload)))

    def assets(self, session: Session) -> list[MediaAsset]:
        return list(session.scalars(select(MediaAsset)))

    @contextmanager
    def verification_session(self, url: URL) -> Iterator[Session]:
        engine = create_engine(url)
        try:
            with Session(engine) as session:
                yield session
        finally:
            engine.dispose()

    def dump_postgres(
        self, url: URL, destination: Path, run_tool: Callable[[list[str], URL], None]
    ) -> tuple[str, dict[str, int]]:
        target = destination / "database.pgdump"
        engine = create_engine(url)
        try:
            with engine.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as connection:
                snapshot = connection.scalar(text("SELECT pg_export_snapshot()"))
                run_tool(
                    [
                        "pg_dump",
                        "--format=custom",
                        "--no-owner",
                        f"--snapshot={snapshot}",
                        "--file",
                        str(target),
                    ],
                    url,
                )
                with Session(bind=connection) as session:
                    return target.name, self.row_counts(session)
        finally:
            engine.dispose()

    def ensure_empty_database(self, url: URL) -> None:
        engine = create_engine(url, hide_parameters=True)
        try:
            inspector = inspect(engine)
            schemas = [
                schema
                for schema in inspector.get_schema_names()
                if schema != "information_schema" and not schema.startswith("pg_")
            ]
            if any(
                inspector.get_table_names(schema=schema)
                or inspector.get_view_names(schema=schema)
                or inspector.get_sequence_names(schema=schema)
                or inspector.get_materialized_view_names(schema=schema)
                for schema in schemas
            ):
                raise BackupError("Restore target database already exists with user objects")
        finally:
            engine.dispose()
