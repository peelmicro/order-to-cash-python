"""K1 (R54, PR20, PR21): the projector is the only RUNTIME writer of `order_timeline`.

An AST scan of `services/*/src/**/*.py` for calls of a pymongo WRITE-shaped method. Only `projector`
and `seed` may make one, each allow-listed BY NAME with its reason inside the guard (the seed is an
offline fixture loader run before the system runs); a read (`find`, `find_one`, `aggregate`,
`count_documents`...) is permitted anywhere; and the projector declares no write-model dependency.

LIMITATIONS, stated (PR20): (1) a same-named unrelated method is a FALSE POSITIVE (a service that
defines its own `update_one` is flagged); (2) `$out` / `$merge` inside an `aggregate` pipeline is a
FALSE NEGATIVE (a write that no method name shows). `drop` and `rename` are counted only in modules
that import `pymongo`, because other libraries have methods of those names.

Non-vacuity: the allow-list is asserted to be hit by BOTH allow-listed services (an allow-list entry
nothing matches would permit anything), and a scratch tree proves a third service is caught.
"""

import ast
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]

WRITE_NAMES = frozenset(
    {
        "insert_one",
        "insert_many",
        "update_one",
        "update_many",
        "replace_one",
        "find_one_and_update",
        "find_one_and_replace",
        "find_one_and_delete",
        "delete_one",
        "delete_many",
        "bulk_write",
        "create_index",
        "create_indexes",
        "drop_index",
        "drop_indexes",
        "drop_collection",
        "create_collection",
    }
)
PYMONGO_ONLY_NAMES = frozenset({"drop", "rename"})

ALLOWED_WRITERS: dict[str, str] = {
    "projector": "the one runtime writer of order_timeline (R54)",
    "seed": "an offline fixture loader, run before the system runs (feature 12)",
}


def imports_pymongo(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            a.name.split(".")[0] == "pymongo" for a in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "pymongo":
            return True
    return False


def write_calls(root: Path) -> dict[str, list[str]]:
    """service -> `file:line name` of every write-shaped call in its production source."""
    found: dict[str, list[str]] = {}
    for path in sorted((root / "services").glob("*/src/**/*.py")):
        if "__pycache__" in path.parts:
            continue
        service = path.relative_to(root / "services").parts[0]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = WRITE_NAMES | (PYMONGO_ONLY_NAMES if imports_pymongo(tree) else frozenset())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in names
            ):
                found.setdefault(service, []).append(
                    f"{path.relative_to(root).as_posix()}:{node.lineno} {node.func.attr}"
                )
    return found


def unauthorised(found: dict[str, list[str]], allowed: dict[str, str]) -> dict[str, list[str]]:
    return {service: hits for service, hits in found.items() if service not in allowed}


def test_r54_permits_a_read_model_write_only_in_the_projector_and_the_allow_listed_offline_fixture_loader_while_permitting_a_read_anywhere_and_declares_no_write_model_dependency_of_its_own() -> (  # noqa: E501
    None
):
    found = write_calls(REPO_ROOT)
    assert unauthorised(found, ALLOWED_WRITERS) == {}, "a service other than the projector writes"
    # non-vacuity: BOTH allow-listed services really make a write-shaped call
    assert set(found) == set(ALLOWED_WRITERS), sorted(found)
    assert len(found["projector"]) >= 1
    assert len(found["seed"]) >= 1
    # a read is permitted anywhere: the scan has no read name in it
    assert not WRITE_NAMES & {"find", "find_one", "aggregate", "count_documents", "list_indexes"}
    # the projector declares no write-model dependency of its own (PR21)
    pyproject = tomllib.loads(
        (REPO_ROOT / "services/projector/pyproject.toml").read_text(encoding="utf-8")
    )
    declared = {
        dependency.split("[")[0].split(">")[0].split("=")[0].strip().lower()
        for dependency in pyproject["project"]["dependencies"]
    }
    assert not declared & {"sqlalchemy", "asyncpg", "alembic"}, sorted(declared)


def test_pr20_a_third_service_acquiring_a_write_shaped_call_fails_proved_on_a_scratch_tree(
    tmp_path: Path,
) -> None:
    def plant(service: str, source: str) -> None:
        target = tmp_path / "services" / service / "src" / f"otc_{service}" / "x.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")

    plant("projector", "async def f(c):\n    await c.update_one({}, {})\n")
    plant("seed", "async def f(c):\n    await c.find_one_and_update({}, [])\n")
    assert unauthorised(write_calls(tmp_path), ALLOWED_WRITERS) == {}, "the control tree must pass"
    plant("billing", "async def f(collection):\n    await collection.update_one({}, {})\n")
    assert list(unauthorised(write_calls(tmp_path), ALLOWED_WRITERS)) == ["billing"]
    # `drop` is a write only where pymongo is imported
    plant("gateway", "def f(x):\n    x.drop()\n")
    assert "gateway" not in write_calls(tmp_path)
    plant("gateway", "import pymongo\n\ndef f(x):\n    x.drop()\n")
    assert "gateway" in unauthorised(write_calls(tmp_path), ALLOWED_WRITERS)
    # a read is permitted anywhere
    plant("fulfillment", "async def f(c):\n    return await c.find_one({})\n")
    assert "fulfillment" not in write_calls(tmp_path)
