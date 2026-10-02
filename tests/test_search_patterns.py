from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from mbs.auth import Role, create_session, create_user
from mbs.db import get_session
from mbs.items import register_store_item
from mbs.main import app
from mbs.models import Item, Store
from mbs.routers.query import contains_pattern
from tests.database import postgres_test_url


def test_contains_pattern_makes_user_wildcards_literal() -> None:
    assert contains_pattern("  50%_off\\ ") == "%50\\%\\_off\\\\%"


def test_item_search_treats_percent_and_underscore_literally_and_counts_store_items(
    tmp_path: Path,
) -> None:
    path = tmp_path / "item-search.db"
    engine = create_engine(postgres_test_url(path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(path).replace("%", "%%"))
    command.upgrade(config, "head")
    with Session(engine) as session:
        manager = create_user(session, "search-manager", "synthetic password", Role.MANAGER)
        token, _ = create_session(session, manager)
        store = Store(display_name="Synthetic Search Store")
        session.add_all([store, Item(common_name="100% juice"), Item(common_name="1000 juice")])
        session.flush()
        observed = register_store_item(
            session, store.store_id, "SEARCH-1", "Synthetic cups", actor_id=manager.id
        )
        observed_item_id = observed.item_id
        session.commit()

    def override_session() -> Iterator[Session]:
        with Session(engine) as active_session:
            yield active_session

    app.dependency_overrides[get_session] = override_session
    headers = {"Cookie": f"mbs_session={token}"}
    try:
        client = TestClient(app)
        literal = client.get("/api/v1/items", params={"query": "100%"}, headers=headers).json()
        assert [item["common_name"] for item in literal] == ["100% juice"]
        assert client.get("/api/v1/items", params={"query": "_"}, headers=headers).json() == []

        counts = {
            item["item_id"]: item["store_item_count"]
            for item in client.get("/api/v1/items", headers=headers).json()
        }
        assert counts[observed_item_id] == 1
        assert sorted(counts.values()) == [0, 0, 1]

        stores = client.get("/api/v1/stores", params={"query": "%"}, headers=headers).json()
        assert stores == []
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
