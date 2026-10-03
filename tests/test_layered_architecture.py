from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mbs.domain.item_images import (
    GalleryOrder,
    ImageGalleryConflictError,
    parse_image_upload_limit,
    replacement_required,
)
from mbs.domain.items import MappingCandidate, rank_mapping_candidates
from mbs.domain.settings import validate_retention_update

SOURCE = Path(__file__).parents[1] / "src" / "mbs"
PERSISTENCE_METHODS = {
    "add",
    "add_all",
    "begin",
    "begin_nested",
    "commit",
    "delete",
    "execute",
    "flush",
    "get",
    "merge",
    "rollback",
    "scalar",
    "scalars",
}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def test_domain_has_no_framework_or_persistence_dependencies() -> None:
    forbidden = (
        "fastapi",
        "sqlalchemy",
        "mbs.models",
        "mbs.repositories",
        "mbs.services",
        "mbs.routers",
        "mbs.infrastructure",
        "PIL",
        "pymupdf",
        "pytesseract",
        "cv2",
        "numpy",
    )
    for path in (SOURCE / "domain").glob("*.py"):
        assert not [name for name in _imports(path) if name.startswith(forbidden)], path.name


def test_repositories_do_not_depend_on_routes_or_services() -> None:
    for path in (SOURCE / "repositories").glob("*.py"):
        assert not [
            name
            for name in _imports(path)
            if name.startswith(("mbs.routers", "mbs.services", "fastapi"))
        ], path.name


def test_services_do_not_depend_on_http_frameworks() -> None:
    for path in (SOURCE / "services").glob("*.py"):
        assert not [
            name
            for name in _imports(path)
            if name.startswith(("fastapi", "starlette", "mbs.routers"))
        ], path.name


def test_production_sql_queries_are_owned_by_repositories() -> None:
    for path in SOURCE.rglob("*.py"):
        if path.relative_to(SOURCE).parts[0] in {"models", "repositories"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "sqlalchemy":
                assert not {alias.name for alias in node.names} & {
                    "select",
                    "insert",
                    "update",
                    "delete",
                    "text",
                    "func",
                }, path.name
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                receiver = node.func.value
                if isinstance(receiver, ast.Name) and receiver.id in {
                    "session",
                    "settings_session",
                }:
                    assert node.func.attr not in PERSISTENCE_METHODS, f"{path.name}:{node.lineno}"


def test_layered_services_and_routes_do_not_execute_sql() -> None:
    paths = [
        *(SOURCE / "services").glob("*.py"),
        SOURCE / "routers" / "items.py",
        SOURCE / "routers" / "settings.py",
        SOURCE / "routers" / "stores.py",
        SOURCE / "routers" / "auth.py",
        SOURCE / "routers" / "dependencies.py",
        SOURCE / "routers" / "remembered_rules.py",
        SOURCE / "routers" / "receipts.py",
    ]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                assert node.func.id not in {"select", "insert", "update", "delete", "text"}, (
                    path.name
                )
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                assert not (
                    node.func.value.id == "session" and node.func.attr in PERSISTENCE_METHODS
                ), f"{path.name}:{node.lineno}"


def test_models_remain_declarative_without_business_methods() -> None:
    for path in (SOURCE / "models").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ], path.name


@pytest.mark.parametrize("link_ids", [(1, 1), (1,), (1, 2, 3), (1, 3)])
def test_gallery_order_rejects_duplicate_missing_and_foreign_links(
    link_ids: tuple[int, ...],
) -> None:
    with pytest.raises(ImageGalleryConflictError, match="every active gallery image once"):
        GalleryOrder(link_ids).validate({1, 2})


def test_gallery_order_accepts_exact_permutation_and_empty_gallery() -> None:
    GalleryOrder((2, 1)).validate({1, 2})
    GalleryOrder(()).validate(set())


@pytest.mark.parametrize(
    ("primary_id", "link_id", "confirmed", "expected"),
    [(None, 1, False, False), (1, 1, False, False), (1, 2, False, True), (1, 2, True, False)],
)
def test_primary_replacement_requires_explicit_confirmation(
    primary_id: int | None, link_id: int, confirmed: bool, expected: bool
) -> None:
    assert replacement_required(primary_id, link_id, confirmed) is expected


@pytest.mark.parametrize("value", [None, "", "invalid", "0", "-1"])
def test_image_limit_rejects_invalid_configuration(value: str | None) -> None:
    with pytest.raises(ValueError, match="Image size setting is invalid"):
        parse_image_upload_limit(value)


def test_retention_rules_are_database_independent() -> None:
    assert (
        validate_retention_update({"receipt_source_retention_days": None}, " reason ") == "reason"
    )
    with pytest.raises(ValueError, match="between"):
        validate_retention_update({"receipt_source_retention_days": 0}, "reason")
    with pytest.raises(ValueError, match="Unsupported"):
        validate_retention_update({"unknown": 1}, "reason")


def test_mapping_ranking_preserves_weights_ties_and_limit() -> None:
    candidates = [
        MappingCandidate("item-b", "SYNTHETIC CUP", ("synthetic cup",), frozenset({"123"})),
        MappingCandidate("item-a", "synthetic cup", ("Synthetic Cup",), frozenset({"123"})),
        MappingCandidate("item-c", None, ("synthetic cups",), frozenset()),
        MappingCandidate("item-d", None, (), frozenset()),
    ]
    suggestions = rank_mapping_candidates("  Synthetic   Cup ", "123", candidates, 2)
    assert [suggestion["item_id"] for suggestion in suggestions] == ["item-a", "item-b"]
    assert [suggestion["score"] for suggestion in suggestions] == [270.0, 270.0]
    assert suggestions[0]["reasons"] == [
        "Common name matches printed description",
        "Previously confirmed description",
        "Shared UPC",
    ]
    similar = rank_mapping_candidates("synthetic cup", None, candidates[2:], 10)
    assert [suggestion["item_id"] for suggestion in similar] == ["item-c"]
    assert similar[0]["reasons"] == ["Similar confirmed description"]


def test_compatibility_paths_reexport_one_implementation() -> None:
    from mbs.item_images import ItemImageGalleryService
    from mbs.items import register_store_item
    from mbs.services.item_identity import register_store_item as layered_register
    from mbs.services.item_images import ItemImageGalleryService as LayeredGallery
    from mbs.services.settings import read_setting as layered_read
    from mbs.settings import read_setting

    assert ItemImageGalleryService is LayeredGallery
    assert register_store_item is layered_register
    assert read_setting is layered_read
