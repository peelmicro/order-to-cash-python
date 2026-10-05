"""`packages/shared_kernel` and `packages/cqrs` carry `dependencies = []` (CLAUDE.md, binding)."""

import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("package", ["shared_kernel", "cqrs"])
def test_package_declares_dependencies_as_an_empty_list(package: str) -> None:
    data = tomllib.loads((REPO_ROOT / "packages" / package / "pyproject.toml").read_text())
    project = data["project"]
    # `.get` on purpose: a deleted `dependencies` key must fail too (it would read as None, not []).
    assert project.get("dependencies") == [], (
        f"packages/{package} must declare `dependencies = []` (zero runtime dependencies)"
    )
    assert not project.get("optional-dependencies"), (
        f"packages/{package} must not declare optional-dependencies either"
    )
