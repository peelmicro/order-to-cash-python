"""`otc_contracts` depends on Pydantic and the standard library and on nothing else.

(#8 advisory A4: nothing guarded that package's dependency set there.)

Allow-list, not deny-list: a deny-list of frameworks misses the next one (the `bson` lesson of
feature 7), so every imported top-level module must be named here or be standard library.
"""

import ast
import sys
import tomllib
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PACKAGE_ROOT / "src" / "otc_contracts"
ALLOWED_EXTERNAL = {"pydantic", "otc_contracts"}


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_the_import_scan_sees_the_package_so_the_allow_list_is_not_vacuous() -> None:
    sources = sorted(SOURCE.rglob("*.py"))
    assert len(sources) >= 7
    assert "pydantic" in set().union(*(imported_roots(p) for p in sources))


@pytest.mark.parametrize("path", sorted(SOURCE.rglob("*.py")), ids=lambda p: p.name)
def test_every_module_imports_only_the_standard_library_pydantic_and_itself(path: Path) -> None:
    foreign = {
        root
        for root in imported_roots(path)
        if root not in sys.stdlib_module_names and root not in ALLOWED_EXTERNAL
    }
    assert foreign == set(), f"{path.name} imports {sorted(foreign)}"


def test_the_package_declares_exactly_one_runtime_dependency_pinned() -> None:
    data = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text("utf-8"))
    assert data["project"].get("dependencies") == ["pydantic==2.13.5"]
    assert not data["project"].get("optional-dependencies")
