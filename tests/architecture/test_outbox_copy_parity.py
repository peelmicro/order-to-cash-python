"""Fulfillment's outbox family is a COPY of Orders', and the copy cannot drift (design 10.2, L25).

#7 and #8 deferred a parity test because their canonical named a service-specific type; in Python
the only differences are the import path and the topic constant's name, so the guard is built now.
Nine modules are copies: `application/ports/clock.py`, `infrastructure/clock.py` and
`infrastructure/outbox/{errors,publisher,kafka_publisher,relay,relay_task,wire,writer}.py`.
For each, the text AFTER the module docstring equals the Orders file's text after its docstring once

1. the literal token map `{"otc_orders": "otc_fulfillment", "ORDERS_FACTS_TOPIC":
   "FULFILLMENT_FACTS_TOPIC"}` is applied to the canonical, and
2. the repository's own formatter (`ruff format`, the root `pyproject.toml`'s configuration) has
   reflowed it.

Step 2 is a deviation from `design.md` 10.2, which names the map alone: `FULFILLMENT_FACTS_TOPIC` is
four characters longer than `ORDERS_FACTS_TOPIC`, so the mapped line in `kafka_publisher.py` is
104 columns wide and `ruff format --check` (a `quality.sh` gate) wants it exploded. The copy is
therefore what the formatter makes of the mapped canonical, byte for byte: comments, strings and
every token included. Only the formatter's reflow is forgiven; any other difference, a
one-character change in code, in a comment or in a string, fails by file name.

Each copy's docstring is its own and must name its canonical's path. The member list and the module
list are literals; a census asserts every file under `otc_fulfillment/infrastructure/outbox/` is a
listed copy, one of the two listed service-specific modules, or the package marker.

Sentinels build temporary trees and prove each form is a difference, not a normalised line
(defeat-list rows 4 - 6: a comment, a dead `if False:` region, a triple-quoted string), and that
a pristine tree passes, so the instrument can say yes as well as no.
"""

import ast
import difflib
import functools
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORDERS = "services/orders/src/otc_orders"
FULFILLMENT = "services/fulfillment/src/otc_fulfillment"
COPIES = [
    "application/ports/clock.py",
    "infrastructure/clock.py",
    "infrastructure/outbox/errors.py",
    "infrastructure/outbox/publisher.py",
    "infrastructure/outbox/kafka_publisher.py",
    "infrastructure/outbox/relay.py",
    "infrastructure/outbox/relay_task.py",
    "infrastructure/outbox/wire.py",
    "infrastructure/outbox/writer.py",
]
SERVICE_SPECIFIC = ["infrastructure/outbox/topic.py", "infrastructure/outbox/payloads.py"]
PACKAGE_MARKER = ["infrastructure/outbox/__init__.py"]
TOKEN_MAP = {"otc_orders": "otc_fulfillment", "ORDERS_FACTS_TOPIC": "FULFILLMENT_FACTS_TOPIC"}
PYPROJECT = REPO_ROOT / "pyproject.toml"


def split_docstring(text: str) -> tuple[str, str] | None:
    """(docstring source, the rest) or None when the module has no docstring."""
    tree = ast.parse(text)
    first = tree.body[0] if tree.body else None
    if not (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return None
    lines = text.splitlines(keepends=True)
    return "".join(lines[: first.end_lineno]), "".join(lines[first.end_lineno :])


@functools.cache
def reformatted(text: str, filename: str) -> str:
    done = subprocess.run(  # noqa: S603 - the interpreter running this test and a fixed module
        [
            sys.executable,
            "-m",
            "ruff",
            "format",
            "--config",
            str(PYPROJECT),
            "--stdin-filename",
            filename,
            "-",
        ],
        input=text,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, f"ruff format could not read the mapped canonical:\n{done.stderr}"
    return done.stdout


def expected_body(canonical_text: str, filename: str) -> str:
    parts = split_docstring(canonical_text)
    assert parts is not None, f"the canonical {filename} has no module docstring"
    mapped = parts[1]
    for canonical_token, copy_token in TOKEN_MAP.items():
        mapped = mapped.replace(canonical_token, copy_token)
    return reformatted(mapped.lstrip("\n"), filename).lstrip("\n")


def violations(root: Path, modules: list[str] | None = None) -> list[str]:
    """Every difference between the copies under `root/FULFILLMENT` and the canonicals under
    `root/ORDERS`; empty means the family is a faithful copy."""
    found: list[str] = []
    for rel in COPIES if modules is None else modules:
        canonical = root / ORDERS / rel
        copy = root / FULFILLMENT / rel
        if not copy.is_file():
            found.append(f"{rel}: the copy is missing")
            continue
        if not canonical.is_file():
            found.append(f"{rel}: the canonical is missing")
            continue
        copy_parts = split_docstring(copy.read_text(encoding="utf-8"))
        if copy_parts is None:
            found.append(f"{rel}: the copy has no module docstring")
            continue
        if f"{ORDERS}/{rel}" not in copy_parts[0]:
            found.append(f"{rel}: the copy's docstring does not name its canonical {ORDERS}/{rel}")
        expected = expected_body(canonical.read_text(encoding="utf-8"), copy.as_posix())
        actual = copy_parts[1].lstrip("\n")
        if actual != expected:
            diff = list(
                difflib.unified_diff(
                    expected.splitlines(), actual.splitlines(), "canonical (mapped)", "copy", n=0
                )
            )
            found.append(f"{rel}: differs from the canonical after the docstring: {diff[2:6]}")
    return found


def census(root: Path) -> list[str]:
    outbox = root / FULFILLMENT / "infrastructure" / "outbox"
    on_disk = sorted(p.name for p in outbox.glob("*.py")) if outbox.is_dir() else []
    allowed = sorted(
        Path(rel).name for rel in [*COPIES, *SERVICE_SPECIFIC, *PACKAGE_MARKER] if "/outbox/" in rel
    )
    if on_disk != allowed:
        return [
            f"outbox/ holds {on_disk}, expected exactly {allowed} "
            f"(unlisted: {sorted(set(on_disk) - set(allowed))}, "
            f"missing: {sorted(set(allowed) - set(on_disk))})"
        ]
    return []


def test_every_listed_module_is_a_faithful_copy_of_its_canonical() -> None:
    assert violations(REPO_ROOT) == []
    # the population is real: nine copies, every canonical present
    assert len(COPIES) == 9
    assert all((REPO_ROOT / ORDERS / rel).is_file() for rel in COPIES)


def test_the_outbox_directory_holds_exactly_the_listed_modules() -> None:
    assert census(REPO_ROOT) == []


def test_the_reflow_the_longer_topic_name_forces_is_real_and_is_what_the_copy_holds() -> None:
    # Without the formatter step the mapped canonical would differ from the copy in
    # `kafka_publisher.py`: this test fails if the premise of step 2 ever goes stale.
    canonical = (REPO_ROOT / ORDERS / "infrastructure/outbox/kafka_publisher.py").read_text()
    parts = split_docstring(canonical)
    assert parts is not None
    mapped = parts[1]
    for canonical_token, copy_token in TOKEN_MAP.items():
        mapped = mapped.replace(canonical_token, copy_token)
    copy = (REPO_ROOT / FULFILLMENT / "infrastructure/outbox/kafka_publisher.py").read_text()
    copy_parts = split_docstring(copy)
    assert copy_parts is not None
    assert mapped.lstrip("\n") != copy_parts[1].lstrip("\n"), "no reflow is needed any more"


# ---- sentinels: a temporary tree per case, each form must be seen


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    for rel in COPIES:
        for package in (ORDERS, FULFILLMENT):
            target = tmp_path / package / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / package / rel, target)
    for rel in [*SERVICE_SPECIFIC, *PACKAGE_MARKER]:
        target = tmp_path / FULFILLMENT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / FULFILLMENT / rel, target)
    return tmp_path


def edit(root: Path, rel: str, old: str, new: str) -> None:
    path = root / FULFILLMENT / rel
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"the sentinel anchor {old!r} is not unique in {rel}"
    path.write_text(text.replace(old, new), encoding="utf-8")


RELAY = "infrastructure/outbox/relay.py"
WRITER = "infrastructure/outbox/writer.py"


def test_sentinel_a_pristine_tree_passes(tree: Path) -> None:
    assert violations(tree) == []
    assert census(tree) == []


def test_sentinel_a_one_character_change_after_the_docstring_fails(tree: Path) -> None:
    edit(tree, RELAY, "DEADLOCK_ATTEMPTS = 3", "DEADLOCK_ATTEMPTS = 4")
    found = violations(tree)
    assert [v.split(":")[0] for v in found] == [RELAY], found


def test_sentinel_a_change_that_only_a_comment_holds_fails(tree: Path) -> None:
    # defeat row 4: the difference sits in a comment, which an AST comparison would not see
    edit(tree, RELAY, "from error  # rolls back", "from error  # rolls back!")
    assert [v.split(":")[0] for v in violations(tree)] == [RELAY]


def test_sentinel_a_dead_region_that_shadows_the_canonical_fails(tree: Path) -> None:
    # defeat row 5: the canonical's code is kept, and a dead `if False:` region is added
    edit(
        tree,
        RELAY,
        "DEADLOCK_ATTEMPTS = 3\n",
        "DEADLOCK_ATTEMPTS = 3\nif False:\n    DEADLOCK_ATTEMPTS = 1\n",
    )
    assert [v.split(":")[0] for v in violations(tree)] == [RELAY]


def test_sentinel_the_canonical_text_hidden_in_a_triple_quoted_string_fails(tree: Path) -> None:
    # defeat row 6: the copy's body is replaced by a string that CONTAINS the canonical's text
    path = tree / FULFILLMENT / RELAY
    parts = split_docstring(path.read_text(encoding="utf-8"))
    assert parts is not None
    path.write_text(parts[0] + "HIDDEN = '''\n" + parts[1] + "'''\n", encoding="utf-8")
    assert [v.split(":")[0] for v in violations(tree)] == [RELAY]


def test_sentinel_a_missing_copy_fails(tree: Path) -> None:
    (tree / FULFILLMENT / WRITER).unlink()
    assert violations(tree) == [f"{WRITER}: the copy is missing"]
    assert census(tree)  # and the census names it too


def test_sentinel_an_unlisted_extra_module_under_outbox_fails(tree: Path) -> None:
    (tree / FULFILLMENT / "infrastructure/outbox/extra.py").write_text('"""x"""\n')
    [problem] = census(tree)
    assert "unlisted: ['extra.py']" in problem


def test_sentinel_a_token_map_substitution_in_a_string_the_canonical_does_not_hold_fails(
    tree: Path,
) -> None:
    # the canonical logs "outbox relay cycle was a deadlock victim; retrying"; the copy adds the
    # service name in a position the token map would map back onto a different canonical string
    edit(
        tree,
        RELAY,
        '"outbox relay cycle was a deadlock victim; retrying"',
        '"otc_fulfillment outbox relay cycle was a deadlock victim; retrying"',
    )
    assert [v.split(":")[0] for v in violations(tree)] == [RELAY]


def test_sentinel_a_copy_whose_docstring_does_not_name_its_canonical_fails(tree: Path) -> None:
    path = tree / FULFILLMENT / "infrastructure/clock.py"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(f"{ORDERS}/infrastructure/clock.py", "somewhere/else.py"))
    [problem] = violations(tree)
    assert "does not name its canonical" in problem


def test_sentinel_a_missing_canonical_is_reported_not_skipped(tree: Path) -> None:
    (tree / ORDERS / WRITER).unlink()
    assert violations(tree) == [f"{WRITER}: the canonical is missing"]
