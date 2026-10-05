"""The per-service copies of the persistence helpers are identical (feature 10's ruling).

`range_guards.py` (the write-boundary range guard) and `types.py` (`RawJson`) are COPIED into each
service that has a database: the guard is bound to SQLAlchemy so it cannot live in `shared_kernel`
(`dependencies = []`), and CLAUDE.md allows no other shared runtime package. Copies drift, so this
guard replaces sharing: every copy must equal the first member's, line for line, except the lines
named in `ALLOWED_DIFFERENCES` (a service-specific module path, if one ever has to differ; today
none does, because the service-specific part, which columns carry the quantity code, is a parameter
of `install_range_guards` passed by each service's `models.py`).

`MEMBERS` is a closed literal, not a glob result: a copy that is deleted or never made fails, and a
new member that is NOT added fails the census tests below, so it cannot be skipped silently. Feature
11 added `billing`. `notifications` is deliberately NOT a member: it has no integer column and no
payload column, so it carries neither module (review_db_fulfillment N5 closed in feature 11: the
census reaches every path under `services/*/src`, covers `types.py` as well, and a CRLF copy fails).
"""

import difflib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MEMBERS = ("orders", "fulfillment", "billing")  # the reference is the first member
COPIED_MODULES = ("range_guards.py", "types.py")

# (module, normalised line in the NON-reference copy) that may differ. Empty on purpose.
ALLOWED_DIFFERENCES: frozenset[tuple[str, str]] = frozenset()


def _copy(service: str, module: str) -> Path:
    return (
        REPO_ROOT
        / "services"
        / service
        / "src"
        / f"otc_{service}"
        / "infrastructure"
        / "persistence"
        / module
    )


def _differences(module: str, reference: str, other: str) -> list[str]:
    diff = difflib.unified_diff(
        _copy(reference, module).read_text().splitlines(),
        _copy(other, module).read_text().splitlines(),
        lineterm="",
        n=0,
    )
    changed = [line for line in diff if line[:1] in "+-" and line[:3] not in ("+++", "---")]
    return [line for line in changed if (module, line[1:]) not in ALLOWED_DIFFERENCES]


@pytest.mark.parametrize("module", COPIED_MODULES)
@pytest.mark.parametrize("other", MEMBERS[1:])
def test_the_copy_is_identical_to_the_reference(module: str, other: str) -> None:
    assert _differences(module, MEMBERS[0], other) == [], (
        f"services/{other}/.../persistence/{module} drifted from services/{MEMBERS[0]}'s copy: "
        "edit both (or promote the module), and list any deliberate difference in "
        "ALLOWED_DIFFERENCES"
    )


def _every_file_named_like_a_copy() -> set[Path]:
    """Every file under `services/*/src`, at ANY depth, that carries a copied module's name."""
    return {
        path
        for module in COPIED_MODULES
        for path in (REPO_ROOT / "services").glob(f"*/src/**/{module}")
    }


@pytest.mark.parametrize("module", COPIED_MODULES)
def test_every_file_named_like_a_copy_is_a_listed_member_at_the_listed_path(module: str) -> None:
    """N5: a copy at another path (e.g. `infrastructure/range_guards.py`), or one in an unlisted
    service, escapes the census of one glob. Here the expected set is a literal of paths, derived by
    construction from MEMBERS, and the live population is every file of that name."""
    expected = {_copy(member, module) for member in MEMBERS}
    found = {path for path in _every_file_named_like_a_copy() if path.name == module}
    assert found == expected, (
        f"{module}: found {sorted(p.relative_to(REPO_ROOT).as_posix() for p in found)}, "
        f"listed {sorted(p.relative_to(REPO_ROOT).as_posix() for p in expected)}"
    )
    assert len(expected) == 3  # a literal: orders, fulfillment, billing


@pytest.mark.parametrize("module", COPIED_MODULES)
@pytest.mark.parametrize("member", MEMBERS)
def test_a_copy_has_unix_line_endings(module: str, member: str) -> None:
    """The line comparison above splits on any line ending, so CRLF would pass it (P1)."""
    assert b"\r" not in _copy(member, module).read_bytes(), f"{member}/{module} contains CR"
