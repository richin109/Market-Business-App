from __future__ import annotations

import os

from sqlalchemy.engine import URL, make_url


def validate_database_url(value: str) -> str:
    url = make_url(value)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


def database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if value:
        return validate_database_url(value)
    host = os.environ.get("DATABASE_HOST")
    name = os.environ.get("DATABASE_NAME")
    if not host or not name:
        raise RuntimeError("Set DATABASE_URL or DATABASE_HOST and DATABASE_NAME")
    port = os.environ.get("DATABASE_PORT")
    url = URL.create(
        drivername=os.environ.get("DATABASE_DRIVER", "postgresql+psycopg"),
        username=os.environ.get("DATABASE_USER"),
        password=os.environ.get("DATABASE_PASSWORD"),
        host=host,
        port=int(port) if port else None,
        database=name,
    )
    return validate_database_url(url.render_as_string(hide_password=False))
