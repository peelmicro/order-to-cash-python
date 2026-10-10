"""Fulfillment's and Billing's outbox families are COPIES of Orders', and a copy cannot drift
(design 10.2, L25; `billing_credit/design.md` 10.2, BC17).

#7 and #8 deferred a parity test because their canonical named a service-specific type; in Python
the only differences are the import path and the topic constant's name, so the guard is built now.
Nine modules are copies: `application/ports/clock.py`, `infrastructure/clock.py` and
`infrastructure/outbox/{errors,publisher,kafka_publisher,relay,relay_task,wire,writer}.py`.
For each, the text AFTER the module docstring equals the Orders file's text after its docstring once

1. the service's literal token map (`COPY_SERVICES`: `{"otc_orders": "otc_fulfillment",
   "ORDERS_FACTS_TOPIC": "FULFILLMENT_FACTS_TOPIC"}`, and Billing's likewise) is applied to the
   canonical, and
2. the repository's own formatter (`ruff format`, the root `pyproject.toml`'s configuration) has
   reflowed it.

Step 2 is a deviation from `design.md` 10.2, which names the map alone: `FULFILLMENT_FACTS_TOPIC` is
four characters longer than `ORDERS_FACTS_TOPIC`, so the mapped line in `kafka_publisher.py` is
104 columns wide and `ruff format --check` (a `quality.sh` gate) wants it exploded. The copy is
therefore what the formatter makes of the mapped canonical, byte for byte: comments, strings and
every token included. Only the formatter's reflow is forgiven; any other difference, a
one-character change in code, in a comment or in a string, fails by file name.

The canonical operand gets the same two checks (round-2 fix of review R2-1): its preamble must be
empty and its closing-line tail blank, failing with a message naming `orders` and the module.

Each copy's docstring is its own and must name its canonical's path. The WHOLE file outside the
docstring's own span is compared (round-2 fix of review D2; the round-1 instrument skipped the lines
before the docstring and the rest of its closing line, and a statement hidden there passed):

- the lines BEFORE the docstring must equal an allow-list literal (`PREAMBLE_ALLOWED`, per service
  and file; empty unless listed; today only Billing's `wire.py` and `writer.py` carry the one
  `# ruff: noqa: I001 - ...` line deviation 1 placed there);
- NOTHING may follow the closing quotes on the docstring's last line (`end_col_offset`, which is a
  UTF-8 BYTE offset, so the line is sliced as bytes);
- everything after the docstring equals the mapped, reformatted canonical (above).

The instrument's premises: P1 the docstring is the module's first statement (`ast`), else the copy
fails; P2 the preamble is every line before the docstring's first line, and its first line starts
the file; P3 the docstring statement begins at column 0 (a leading `;`-joined statement would make
it not the first statement, P1); P4 the tail test slices bytes, not characters. Sentinels arm P2 (a
non-listed line, a listed line in an unlisted file, the listed line missing) and P3/P4 (code after
the closing quotes, with non-ASCII text earlier on the line).

A second census (BC17's "required from every service that owns a relational `outbox` table") finds
the services by GLOB, never from the literal, and by what the module DECLARES rather than by one
spelling (round-2 fix of review D3, defeat-list row 11): an AST scan of every `.py` under
`services/*/src/otc_*/infrastructure/` for an `Assign` / `AnnAssign` to `__tablename__` or a
`Table(...)` call whose name resolves to `"outbox"`, where the name is a string literal or a
module-level constant of the same module. The instrument's premises: P5 a table lives under a
service's `infrastructure/` (any module, any depth); P6 its name is a literal or a same-module
constant (an imported constant is NOT resolved; the real-tree test below therefore cross-checks the
scan against what the modules DECLARE once imported - `metadata.tables` - over the scan's own
population, `infrastructure/**/*.py` minus `__init__.py`, so a form the scan cannot read still fails
on the real tree); P7 a mention in a docstring, a comment or any other string is
not a declaration (AST, not text). Owners must belong to `{"orders"}` plus the keys of
`COPY_SERVICES`; a fourth service with an outbox table and no copies fails by name. The seed, which
mirrors the table without owning it, is listed in `MIRRORS_NOT_OWNERS`. The population assertion in
`test_every_service_owning_an_outbox_table_holds_the_family` stays a literal.

Sentinels build temporary trees and prove each form is a difference, not a normalised line
(defeat-list rows 4 - 7 and 11: a comment, a dead `if False:` region, a triple-quoted string, a
dropped optional element, the other spellings of the table name), and that a pristine tree passes,
so the instrument can say yes as well as no.
"""

import ast
import difflib
import functools
import importlib
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORDERS = "services/orders/src/otc_orders"
FULFILLMENT = "services/fulfillment/src/otc_fulfillment"
BILLING = "services/billing/src/otc_billing"
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
# service -> (its package path, the token map applied to the canonical)
COPY_SERVICES: dict[str, tuple[str, dict[str, str]]] = {
    "fulfillment": (
        FULFILLMENT,
        {"otc_orders": "otc_fulfillment", "ORDERS_FACTS_TOPIC": "FULFILLMENT_FACTS_TOPIC"},
    ),
    "billing": (
        BILLING,
        {"otc_orders": "otc_billing", "ORDERS_FACTS_TOPIC": "BILLING_FACTS_TOPIC"},
    ),
}
CANONICAL_OWNER = "orders"
# The lines a copy may carry BEFORE its docstring, per (service, module); anything else fails.
_I001 = (
    "# ruff: noqa: I001 - the copy keeps the canonical's import order; "
    "the parity guard compares it\n"
)
# Services that DECLARE an `outbox` table without owning it. The seed keeps hand-written Core
# mirrors of the tables it writes (`otc_seed/infrastructure/tables.py`, checked against the migrated
# databases by `schema_check`); the owner is the service whose Alembic migration creates the table.
# The real-tree test asserts the seed is still found by the scan, so this entry cannot go stale.
MIRRORS_NOT_OWNERS = {"seed"}
PREAMBLE_ALLOWED: dict[tuple[str, str], str] = {
    ("billing", "infrastructure/outbox/wire.py"): _I001,
    ("billing", "infrastructure/outbox/writer.py"): _I001,
}
PYPROJECT = REPO_ROOT / "pyproject.toml"


class Parts(NamedTuple):
    preamble: str  # every line before the docstring's first line
    docstring: str  # the docstring's own lines, closing line included
    closing_tail: str  # whatever follows the closing quotes on the docstring's last line
    body: str  # every line after the docstring


def split_docstring(text: str) -> Parts | None:
    """The file cut at the module docstring's span, or None when it has no docstring."""
    tree = ast.parse(text)
    first = tree.body[0] if tree.body else None
    if not (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return None
    assert first.end_lineno is not None
    assert first.end_col_offset is not None
    lines = text.splitlines(keepends=True)
    last = lines[first.end_lineno - 1].encode("utf-8")  # end_col_offset counts UTF-8 bytes (P4)
    return Parts(
        "".join(lines[: first.lineno - 1]),
        "".join(lines[first.lineno - 1 : first.end_lineno]),
        last[first.end_col_offset :].decode("utf-8").strip("\r\n"),
        "".join(lines[first.end_lineno :]),
    )


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


def expected_body(canonical_text: str, filename: str, token_map: dict[str, str]) -> str:
    parts = split_docstring(canonical_text)
    assert parts is not None, f"the canonical {filename} has no module docstring"
    mapped = parts.body
    for canonical_token, copy_token in token_map.items():
        mapped = mapped.replace(canonical_token, copy_token)
    return reformatted(mapped.lstrip("\n"), filename).lstrip("\n")


def violations(root: Path, service: str, modules: list[str] | None = None) -> list[str]:
    """Every difference between `service`'s copies under `root` and the canonicals under
    `root/ORDERS`; empty means the family is a faithful copy."""
    package, token_map = COPY_SERVICES[service]
    found: list[str] = []
    for rel in COPIES if modules is None else modules:
        canonical = root / ORDERS / rel
        copy = root / package / rel
        if not copy.is_file():
            found.append(f"{rel}: the copy is missing")
            continue
        if not canonical.is_file():
            found.append(f"{rel}: the canonical is missing")
            continue
        canonical_parts = split_docstring(canonical.read_text(encoding="utf-8"))
        if canonical_parts is not None:  # (a missing docstring is reported by expected_body)
            if canonical_parts.preamble != "":
                found.append(
                    f"{rel}: the canonical ({CANONICAL_OWNER}) has lines before its docstring: "
                    f"{canonical_parts.preamble!r}"
                )
            if canonical_parts.closing_tail.strip():
                found.append(
                    f"{rel}: the canonical ({CANONICAL_OWNER}) has text after its docstring's "
                    f"closing quotes: {canonical_parts.closing_tail!r}"
                )
        copy_parts = split_docstring(copy.read_text(encoding="utf-8"))
        if copy_parts is None:
            found.append(f"{rel}: the copy has no module docstring")
            continue
        allowed_preamble = PREAMBLE_ALLOWED.get((service, rel), "")
        if copy_parts.preamble != allowed_preamble:
            found.append(
                f"{rel}: the lines before the docstring are {copy_parts.preamble!r}, "
                f"the allow-list holds {allowed_preamble!r}"
            )
        if copy_parts.closing_tail.strip():
            found.append(
                f"{rel}: text follows the docstring's closing quotes: {copy_parts.closing_tail!r}"
            )
        if f"{ORDERS}/{rel}" not in copy_parts.docstring:
            found.append(f"{rel}: the copy's docstring does not name its canonical {ORDERS}/{rel}")
        expected = expected_body(canonical.read_text(encoding="utf-8"), copy.as_posix(), token_map)
        actual = copy_parts.body.lstrip("\n")
        if actual != expected:
            diff = list(
                difflib.unified_diff(
                    expected.splitlines(), actual.splitlines(), "canonical (mapped)", "copy", n=0
                )
            )
            found.append(f"{rel}: differs from the canonical after the docstring: {diff[2:6]}")
    return found


def census(root: Path, service: str) -> list[str]:
    outbox = root / COPY_SERVICES[service][0] / "infrastructure" / "outbox"
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


def _string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "text"` / `NAME: str = "text"` (P6)."""
    found: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        else:
            continue
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            found[target.id] = value.value
    return found


def declares_outbox_table(source: str) -> bool:
    """True when the module assigns `__tablename__` or calls `Table(...)` with the name `outbox`."""
    tree = ast.parse(source)
    constants = _string_constants(tree)

    def resolves_to_outbox(node: ast.expr | None) -> bool:
        if isinstance(node, ast.Constant):
            return node.value == "outbox"
        return isinstance(node, ast.Name) and constants.get(node.id) == "outbox"

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "__tablename__" in names and resolves_to_outbox(node.value):
                return True
        elif isinstance(node, ast.AnnAssign):
            if (
                isinstance(node.target, ast.Name)
                and node.target.id == "__tablename__"
                and resolves_to_outbox(node.value)
            ):
                return True
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if called == "Table" and resolves_to_outbox(node.args[0]):
                return True
    return False


def outbox_declarers(root: Path) -> dict[str, Path]:
    """Every service that declares a relational `outbox` table, FOUND BY GLOB (never from a
    literal), the first declaring module recorded per service (P5)."""
    owners: dict[str, Path] = {}
    for path in sorted(root.glob("services/*/src/otc_*/infrastructure/**/*.py")):
        if declares_outbox_table(path.read_text(encoding="utf-8")):
            owners.setdefault(path.relative_to(root).parts[1], path)
    return owners


def outbox_owners(root: Path) -> dict[str, Path]:
    """The declarers minus the listed mirrors (`MIRRORS_NOT_OWNERS`)."""
    return {n: p for n, p in outbox_declarers(root).items() if n not in MIRRORS_NOT_OWNERS}


def table_census(root: Path) -> list[str]:
    """The services owning an outbox table that are neither the canonical nor a listed copier."""
    allowed = {CANONICAL_OWNER, *COPY_SERVICES}
    unlisted = sorted(set(outbox_owners(root)) - allowed)
    if not unlisted:
        return []
    return [
        f"services owning an `outbox` table without the relay family: {unlisted} "
        f"(listed: {sorted(allowed)})"
    ]


SERVICES = sorted(COPY_SERVICES)


@pytest.mark.parametrize("service", SERVICES)
def test_every_listed_module_is_a_faithful_copy_of_its_canonical(service: str) -> None:
    found = violations(REPO_ROOT, service)
    assert found == [], f"{service}'s outbox copies differ from Orders': {found}"
    # the population is real: nine copies, every canonical present
    assert len(COPIES) == 9
    assert all((REPO_ROOT / ORDERS / rel).is_file() for rel in COPIES)
    assert all((REPO_ROOT / COPY_SERVICES[service][0] / rel).is_file() for rel in COPIES)


@pytest.mark.parametrize("service", SERVICES)
def test_the_outbox_directory_holds_exactly_the_listed_modules(service: str) -> None:
    assert census(REPO_ROOT, service) == []


def test_every_service_owning_an_outbox_table_holds_the_family() -> None:
    owners = outbox_owners(REPO_ROOT)
    unlisted = table_census(REPO_ROOT)
    assert unlisted == [], unlisted
    # the population is found by glob and is the three services the plan names
    assert sorted(owners) == ["billing", "fulfillment", "orders"], sorted(owners)
    for service in COPY_SERVICES:
        assert service in owners, f"{service} is listed as a copier but owns no outbox table"


def _declared_table_names(module_name: str) -> set[str]:
    """What the imported module DECLARES: the tables of every `MetaData` it reaches (P6)."""
    from sqlalchemy import MetaData

    module = importlib.import_module(module_name)
    names: set[str] = set()
    for value in vars(module).values():
        metadata = value if isinstance(value, MetaData) else getattr(value, "metadata", None)
        if isinstance(metadata, MetaData):
            names |= set(metadata.tables)
    return names


def test_the_scan_agrees_with_what_the_infrastructure_modules_declare_once_imported() -> None:
    # behaviour, not syntax (defeat row 11): import every `infrastructure` module that exists in the
    # real tree and ask SQLAlchemy which tables it holds; the owners must be the scan's owners.
    owners = set(outbox_owners(REPO_ROOT))
    declared: set[str] = set()
    for path in sorted(REPO_ROOT.glob("services/*/src/otc_*/infrastructure/**/*.py")):
        if path.name == "__init__.py":
            continue
        service_src = REPO_ROOT / "services" / path.relative_to(REPO_ROOT).parts[1] / "src"
        relative = path.relative_to(service_src)
        if "outbox" in _declared_table_names(".".join(relative.with_suffix("").parts)):
            declared.add(path.relative_to(REPO_ROOT).parts[1])
    # the import also reaches the seed's Core mirror, which the listed exclusion removes
    assert declared - MIRRORS_NOT_OWNERS == owners == {"billing", "fulfillment", "orders"}, (
        declared,
        owners,
    )
    assert declared & MIRRORS_NOT_OWNERS == MIRRORS_NOT_OWNERS, declared
    # the mirror exclusion is live: the scan still sees the seed's Core definition of the table
    assert set(outbox_declarers(REPO_ROOT)) - owners == MIRRORS_NOT_OWNERS


def test_the_reflow_the_longer_topic_name_forces_is_real_and_is_what_the_copy_holds() -> None:
    # Without the formatter step the mapped canonical would differ from Fulfillment's copy in
    # `kafka_publisher.py`: this test fails if the premise of step 2 ever goes stale. (Whether
    # Billing's names force a reflow is not claimed: the formatter step forgives it either way.)
    package, token_map = COPY_SERVICES["fulfillment"]
    canonical = (REPO_ROOT / ORDERS / "infrastructure/outbox/kafka_publisher.py").read_text()
    parts = split_docstring(canonical)
    assert parts is not None
    mapped = parts.body
    for canonical_token, copy_token in token_map.items():
        mapped = mapped.replace(canonical_token, copy_token)
    copy = (REPO_ROOT / package / "infrastructure/outbox/kafka_publisher.py").read_text()
    copy_parts = split_docstring(copy)
    assert copy_parts is not None
    assert mapped.lstrip("\n") != copy_parts.body.lstrip("\n"), "no reflow is needed any more"


# ---- sentinels: a temporary tree per case, each form must be seen


def _models_stub(root: Path, service: str) -> None:
    target = root / "services" / service / "src" / f"otc_{service}"
    target = target / "infrastructure" / "persistence" / "models.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('class Outbox:\n    __tablename__ = "outbox"\n', encoding="utf-8")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    for rel in COPIES:
        for package in (ORDERS, *(p for p, _ in COPY_SERVICES.values())):
            target = tmp_path / package / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / package / rel, target)
    for package, _ in COPY_SERVICES.values():
        for rel in [*SERVICE_SPECIFIC, *PACKAGE_MARKER]:
            target = tmp_path / package / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / package / rel, target)
    for service in (CANONICAL_OWNER, *COPY_SERVICES):
        _models_stub(tmp_path, service)
    return tmp_path


def edit(root: Path, service: str, rel: str, old: str, new: str) -> None:
    path = root / COPY_SERVICES[service][0] / rel
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"the sentinel anchor {old!r} is not unique in {rel}"
    path.write_text(text.replace(old, new), encoding="utf-8")


RELAY = "infrastructure/outbox/relay.py"
WRITER = "infrastructure/outbox/writer.py"


@pytest.mark.parametrize("service", SERVICES)
def test_sentinel_a_pristine_tree_passes(tree: Path, service: str) -> None:
    assert violations(tree, service) == []
    assert census(tree, service) == []
    assert table_census(tree) == []


@pytest.mark.parametrize("service", SERVICES)
@pytest.mark.parametrize("rel", COPIES)
def test_sentinel_a_one_character_change_in_each_copy_fails_naming_that_file(
    tree: Path, service: str, rel: str
) -> None:
    path = tree / COPY_SERVICES[service][0] / rel
    path.write_text(path.read_text(encoding="utf-8") + "\nX = 1\n", encoding="utf-8")
    found = violations(tree, service)
    assert [v.split(":")[0] for v in found] == [rel], found
    # the other service's copy of the same module is untouched and still passes
    other = next(name for name in COPY_SERVICES if name != service)
    assert violations(tree, other) == []


@pytest.mark.parametrize("service", SERVICES)
def test_sentinel_a_one_character_change_after_the_docstring_fails(
    tree: Path, service: str
) -> None:
    edit(tree, service, RELAY, "DEADLOCK_ATTEMPTS = 3", "DEADLOCK_ATTEMPTS = 4")
    found = violations(tree, service)
    assert [v.split(":")[0] for v in found] == [RELAY], found


@pytest.mark.parametrize("service", SERVICES)
def test_sentinel_a_change_that_only_a_comment_holds_fails(tree: Path, service: str) -> None:
    # defeat row 4: the difference sits in a comment, which an AST comparison would not see
    edit(tree, service, RELAY, "from error  # rolls back", "from error  # rolls back!")
    assert [v.split(":")[0] for v in violations(tree, service)] == [RELAY]


@pytest.mark.parametrize("service", SERVICES)
def test_sentinel_a_dead_region_that_shadows_the_canonical_fails(tree: Path, service: str) -> None:
    # defeat row 5: the canonical's code is kept, and a dead `if False:` region is added
    edit(
        tree,
        service,
        RELAY,
        "DEADLOCK_ATTEMPTS = 3\n",
        "DEADLOCK_ATTEMPTS = 3\nif False:\n    DEADLOCK_ATTEMPTS = 1\n",
    )
    assert [v.split(":")[0] for v in violations(tree, service)] == [RELAY]


@pytest.mark.parametrize("service", SERVICES)
def test_sentinel_the_canonical_text_hidden_in_a_triple_quoted_string_fails(
    tree: Path, service: str
) -> None:
    # defeat row 6: the copy's body is replaced by a string that CONTAINS the canonical's text
    path = tree / COPY_SERVICES[service][0] / RELAY
    parts = split_docstring(path.read_text(encoding="utf-8"))
    assert parts is not None
    path.write_text(
        parts.preamble + parts.docstring + "HIDDEN = '''\n" + parts.body + "'''\n",
        encoding="utf-8",
    )
    assert [v.split(":")[0] for v in violations(tree, service)] == [RELAY]


@pytest.mark.parametrize("service", SERVICES)
def test_sentinel_a_missing_copy_fails(tree: Path, service: str) -> None:
    (tree / COPY_SERVICES[service][0] / WRITER).unlink()
    assert violations(tree, service) == [f"{WRITER}: the copy is missing"]
    assert census(tree, service)  # and the census names it too


@pytest.mark.parametrize("service", SERVICES)
def test_sentinel_an_unlisted_extra_module_under_outbox_fails(tree: Path, service: str) -> None:
    (tree / COPY_SERVICES[service][0] / "infrastructure/outbox/extra.py").write_text('"""x"""\n')
    [problem] = census(tree, service)
    assert "unlisted: ['extra.py']" in problem


@pytest.mark.parametrize("service", SERVICES)
def test_sentinel_a_token_map_substitution_in_a_string_the_canonical_does_not_hold_fails(
    tree: Path, service: str
) -> None:
    # the canonical logs "outbox relay cycle was a deadlock victim; retrying"; the copy adds the
    # service name in a position the token map would map back onto a different canonical string
    package_token = COPY_SERVICES[service][1]["otc_orders"]
    edit(
        tree,
        service,
        RELAY,
        '"outbox relay cycle was a deadlock victim; retrying"',
        f'"{package_token} outbox relay cycle was a deadlock victim; retrying"',
    )
    assert [v.split(":")[0] for v in violations(tree, service)] == [RELAY]


@pytest.mark.parametrize("service", SERVICES)
def test_sentinel_a_copy_whose_docstring_does_not_name_its_canonical_fails(
    tree: Path, service: str
) -> None:
    path = tree / COPY_SERVICES[service][0] / "infrastructure/clock.py"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(f"{ORDERS}/infrastructure/clock.py", "somewhere/else.py"))
    [problem] = violations(tree, service)
    assert "does not name its canonical" in problem


@pytest.mark.parametrize("service", SERVICES)
def test_sentinel_a_missing_canonical_is_reported_not_skipped(tree: Path, service: str) -> None:
    (tree / ORDERS / WRITER).unlink()
    assert violations(tree, service) == [f"{WRITER}: the canonical is missing"]


def test_sentinel_a_service_with_an_outbox_table_and_no_copies_fails_the_census(
    tree: Path,
) -> None:
    _models_stub(tree, "notifications")
    [problem] = table_census(tree)
    assert "['notifications']" in problem


def test_sentinel_a_service_without_an_outbox_table_is_not_required_to_hold_the_family(
    tree: Path,
) -> None:
    target = tree / "services/gateway/src/otc_gateway/infrastructure/persistence/models.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("class Thing:\n    __tablename__ = 'things'\n", encoding="utf-8")
    assert table_census(tree) == []


# ---- sentinels for the round-2 instrument (review D2, D3)

WIRE = "infrastructure/outbox/wire.py"


def _rewrite(root: Path, service: str, rel: str, transform: Callable[[Parts], str]) -> None:
    path = root / COPY_SERVICES[service][0] / rel
    parts = split_docstring(path.read_text(encoding="utf-8"))
    assert parts is not None
    path.write_text(transform(parts), encoding="utf-8")


@pytest.mark.parametrize("service", SERVICES)
@pytest.mark.parametrize("rel", [RELAY, WIRE])
def test_sentinel_code_after_the_docstrings_closing_quotes_fails_naming_the_file(
    tree: Path, service: str, rel: str
) -> None:
    # review D2 / arm Q1: an executable statement on the docstring's closing line
    hidden = '; HIDDEN = __import__("logging").disable()  # noqa: E702'
    _rewrite(
        tree,
        service,
        rel,
        lambda p: p.preamble + p.docstring.rstrip("\n") + hidden + "\n" + p.body,
    )
    found = violations(tree, service)
    assert [v.split(":")[0] for v in found if "closing quotes" in v] == [rel], found
    assert violations(tree, next(n for n in COPY_SERVICES if n != service)) == []


@pytest.mark.parametrize("service", SERVICES)
def test_sentinel_code_after_the_closing_quotes_is_seen_after_non_ascii_text_on_the_line(
    tree: Path, service: str
) -> None:
    # P4: end_col_offset counts bytes. A docstring whose closing line holds non-ASCII text before
    # the quotes would slice the tail wrongly if the line were cut by characters: the three
    # non-ASCII characters shift the offset by three, and the tail `;0` is two characters long, so
    # a character slice would see an empty tail.
    def transform(p: Parts) -> str:
        head, quotes, _ = p.docstring.rstrip("\n").rpartition('"""')
        return p.preamble + head + " éé ñ" + quotes + ";0\n" + p.body

    _rewrite(tree, service, RELAY, transform)
    found = violations(tree, service)
    assert [v.split(":")[0] for v in found if "closing quotes" in v] == [RELAY], found


@pytest.mark.parametrize("service", SERVICES)
@pytest.mark.parametrize(
    "line", ["# ruff: noqa: E402\n", "# type: ignore\n", "# ruff: noqa: I001\n"]
)
def test_sentinel_a_line_before_the_docstring_that_is_not_allow_listed_fails_naming_the_file(
    tree: Path, service: str, line: str
) -> None:
    _rewrite(tree, service, RELAY, lambda p: line + p.preamble + p.docstring + p.body)
    found = violations(tree, service)
    assert [v.split(":")[0] for v in found if "before the docstring" in v] == [RELAY], found


@pytest.mark.parametrize("service", SERVICES)
def test_sentinel_a_second_line_before_the_docstring_in_an_allow_listed_file_fails(
    tree: Path, service: str
) -> None:
    # the allow-list is the exact literal, not "contains the directive"
    def transform(p: Parts) -> str:
        return p.preamble + "# type: ignore\n" + p.docstring + p.body

    _rewrite(tree, service, WIRE, transform)
    found = violations(tree, service)
    assert [v.split(":")[0] for v in found if "before the docstring" in v] == [WIRE], found


@pytest.mark.parametrize("service", SERVICES)
def test_sentinel_the_allow_listed_directive_in_a_file_that_is_not_listed_fails(
    tree: Path, service: str
) -> None:
    directive = PREAMBLE_ALLOWED[("billing", WIRE)]
    _rewrite(tree, service, RELAY, lambda p: directive + p.docstring + p.body)
    found = violations(tree, service)
    assert [v.split(":")[0] for v in found if "before the docstring" in v] == [RELAY], found


@pytest.mark.parametrize("rel", [WIRE, WRITER])
def test_sentinel_billings_listed_directive_missing_fails(tree: Path, rel: str) -> None:
    _rewrite(tree, "billing", rel, lambda p: p.docstring + p.body)
    found = violations(tree, "billing")
    assert [v.split(":")[0] for v in found if "before the docstring" in v] == [rel], found


@pytest.mark.parametrize(
    ("form", "source"),
    [
        ("literal", 'class O:\n    __tablename__ = "outbox"\n'),
        ("annotated", 'class O:\n    __tablename__: str = "outbox"\n'),
        ("constant", 'OUTBOX = "outbox"\n\n\nclass O:\n    __tablename__ = OUTBOX\n'),
        (
            "annotated constant",
            'OUTBOX: str = "outbox"\n\n\nclass O:\n    __tablename__ = OUTBOX\n',
        ),
        (
            "core table",
            'from sqlalchemy import MetaData, Table\n\nT = Table("outbox", MetaData())\n',
        ),
        (
            "core table, qualified",
            'import sqlalchemy as sa\n\nT = sa.Table("outbox", sa.MetaData())\n',
        ),
    ],
)
@pytest.mark.parametrize("module", ["models.py", "outbox_models.py", "sub/tables.py"])
def test_sentinel_every_spelling_of_the_outbox_table_makes_a_fourth_service_fail_the_census(
    tree: Path, form: str, source: str, module: str
) -> None:
    # review D3: forms (annotated, constant, Core Table, another module) were invisible
    target = tree / "services/notifications/src/otc_notifications/infrastructure/persistence"
    target = target / module
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    [problem] = table_census(tree)
    assert "['notifications']" in problem, (form, module, problem)


@pytest.mark.parametrize(
    "source",
    [
        '"""Owns `__tablename__ = "outbox"` (a docstring, not a declaration)."""\n',
        '# __tablename__ = "outbox"\nX = 1\n',
        "TEXT = '''\n__tablename__ = \"outbox\"\n'''\n",
        'class O:\n    __tablename__ = "outbox_archive"\n',
        'NAME = "outbox"\n\n\nclass O:\n    __tablename__ = "things"\n',
    ],
)
def test_sentinel_a_mention_of_the_outbox_table_that_declares_nothing_is_not_an_owner(
    tree: Path, source: str
) -> None:
    # P7 (defeat rows 4 and 6): a comment, a docstring and a string are not declarations
    target = tree / "services/notifications/src/otc_notifications/infrastructure/persistence"
    target.mkdir(parents=True, exist_ok=True)
    (target / "models.py").write_text(source, encoding="utf-8")
    assert table_census(tree) == []


# ---- sentinels for review round 2 (R2-1, R2-3)


@pytest.mark.parametrize("service", SERVICES)
@pytest.mark.parametrize(
    ("region", "mutate"),
    [
        ("preamble", lambda p: "# ruff: noqa: E402\n" + p.preamble + p.docstring + p.body),
        (
            "tail",
            lambda p: (
                p.preamble
                + p.docstring.rstrip("\n")
                + '; HIDDEN = __import__("logging").disable()\n'
                + p.body
            ),
        ),
    ],
)
def test_sentinel_r2_1_the_canonical_with_a_preamble_or_a_tail_fails_naming_orders_and_the_module(
    tree: Path, service: str, region: str, mutate: Callable[[Parts], str]
) -> None:
    path = tree / ORDERS / RELAY
    parts = split_docstring(path.read_text(encoding="utf-8"))
    assert parts is not None
    path.write_text(mutate(parts), encoding="utf-8")
    found = [v for v in violations(tree, service) if "the canonical (orders)" in v]
    assert [v.split(":")[0] for v in found] == [RELAY], (region, found)


@pytest.mark.parametrize("service", SERVICES)
def test_sentinel_r2_3_a_comment_only_tail_on_the_closing_line_fails_naming_the_file(
    tree: Path, service: str
) -> None:
    # a closing-line comment that ruff reads as a file-level directive (a comment to the tokenizer)
    _rewrite(
        tree,
        service,
        RELAY,
        lambda p: p.preamble + p.docstring.rstrip("\n") + f"  # {'ruff'}: noqa\n" + p.body,
    )
    found = violations(tree, service)
    assert [v.split(":")[0] for v in found if "closing quotes" in v] == [RELAY], found
