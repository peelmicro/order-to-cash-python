"""Every write path of the seed, enumerated and classified (backlog 204(a) applied to the seed).

R-map (feature_list.json id 12): the claim "every integer the seed writes into a guarded column is
range-checked" is a claim about the POPULATION of write paths, so the population is a search
result. The scan is an AST walk (not a grep: a hit in a comment, a docstring, a raw string or a
dead branch is classified by what the instrument sees, and the sentinels below prove it sees code in
every one of those hiding places). The expected set is a literal; the failure message names the
unexpected call.

LIMIT (round 2, N1): the scan matches call names, so an aliased import or a bound method hides a
write from it. The behaviour guard `integration/test_seed_write_path_behaviour.py` counts the rows
the engines really INSERT and compares them with the rows the range guard saw.

Classification of the literal set:
* `postgres.py :: insert_missing :: pg_insert` is THE insert path of the three relational targets:
  it calls `ensure_row_in_range` for every row first (`test_range_check.py` proves the order).
* `mongo.py :: seed :: update_one` writes BSON documents: there is no integer column width to
  exceed (MongoDB stores int64; money in the document is the same `int` the relational rows hold).
* `mongo.py :: seed :: create_index` writes no data.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "otc_seed"

# Names whose call is a write path: SQLAlchemy DML constructors and raw SQL, bulk helpers, and the
# PyMongo write methods.
WRITE_NAMES = {
    "insert",
    "pg_insert",
    "update",
    "delete",
    "text",
    "execute",
    "executemany",
    "insert_one",
    "insert_many",
    "update_one",
    "update_many",
    "replace_one",
    "bulk_write",
    "create_index",
    "create_indexes",
    "drop_database",
    "drop_collection",
}


def _called_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def write_calls(source: str) -> set[tuple[str, str]]:
    """`(enclosing function, called name)` for every write call in `source`, in any region
    (`if False:` and `if TYPE_CHECKING:` included: they are walked like any other code)."""
    tree = ast.parse(source)
    found: set[tuple[str, str]] = set()

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = scope
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                inner = child.name
            if isinstance(child, ast.Call):
                name = _called_name(child)
                if name is not None and (name in WRITE_NAMES or name.startswith("bulk_")):
                    found.add((inner, name))
            visit(child, inner)

    visit(tree, "<module>")
    return found


EXPECTED: dict[str, set[tuple[str, str]]] = {
    "infrastructure/postgres.py": {
        ("insert_missing", "execute"),  # the existing-id SELECT and the one INSERT
        ("insert_missing", "pg_insert"),
    },
    "infrastructure/mongo.py": {("seed", "create_index"), ("seed", "update_one")},
}


def _source_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def test_the_population_of_write_paths_is_the_expected_literal() -> None:
    found = {
        str(path.relative_to(SRC)): write_calls(path.read_text(encoding="utf-8"))
        for path in _source_files()
    }
    found = {name: calls for name, calls in found.items() if calls}
    assert found == EXPECTED
    assert len(_source_files()) > 20  # the scan covered the package, not an empty directory


def test_exactly_one_insert_statement_exists_in_the_seed() -> None:
    inserts = [
        (str(path.relative_to(SRC)), scope)
        for path in _source_files()
        for scope, name in write_calls(path.read_text(encoding="utf-8"))
        if name in {"insert", "pg_insert"}
    ]
    assert inserts == [("infrastructure/postgres.py", "insert_missing")]


@pytest.mark.parametrize(
    ("hiding_place", "source"),
    [
        ("plain", "def f(c):\n    c.execute(text('DELETE FROM t'))\n"),
        ("dead region", "def f():\n    if False:\n        insert(T)\n"),
        ("TYPE_CHECKING", "def f():\n    if TYPE_CHECKING:\n        update(T)\n"),
        ("bulk helper", "def f(s):\n    s.bulk_insert_mappings(T, [])\n"),
        ("attribute call", "def f(m):\n    sqlalchemy.insert(T)\n"),
        ("nested function", "def f():\n    def g(c):\n        c.replace_one({}, {})\n"),
    ],
)
def test_the_scanner_sees_a_write_hidden_in_every_region(hiding_place: str, source: str) -> None:
    """Sweep sentinels: each of these MUST be detected, or an 'all clear' above means nothing."""
    assert write_calls(source), hiding_place


@pytest.mark.parametrize(
    "source",
    [
        "# insert(T)\n",
        "'''insert(T)'''\n",
        "S = 'c.execute(text(1))'\n",
    ],
)
def test_a_write_named_only_in_a_comment_or_a_string_is_not_a_write(source: str) -> None:
    assert write_calls(source) == set()
