"""mypy policy (CLAUDE.md "Typing"): strict, no global ignore_missing_imports, one override."""

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _mypy() -> dict[str, object]:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    mypy: dict[str, object] = data["tool"]["mypy"]
    return mypy


def test_mypy_is_strict_without_a_global_ignore_missing_imports() -> None:
    mypy = _mypy()
    assert mypy.get("strict") is True, "mypy must run with strict = true"
    assert "ignore_missing_imports" not in mypy, "no GLOBAL ignore_missing_imports is allowed"


def test_the_only_mypy_override_is_aiokafka() -> None:
    overrides = _mypy().get("overrides")
    assert overrides == [{"module": ["aiokafka.*"], "ignore_missing_imports": True}], (
        "the only [[tool.mypy.overrides]] allowed is aiokafka.* (no stubs exist for it)"
    )
