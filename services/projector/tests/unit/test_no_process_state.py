"""K7 (PR51): the projector holds no process-wide state.

Deduplication and projection state live in MongoDB and nowhere else. A runtime rebuilt in ONE
process (new clients, new consumer) cannot see a process-wide cache (design 11.2: the gap between
an in-process rebuild and a real process restart), so this guard closes it STRUCTURALLY: an AST scan
of `src` finds no module-level mutable container, and the two writer classes assign only their
collection handle and their collaborator in `__init__`.

Module-level constants that ARE containers are declared below, each classified; the list is EMPTY
today (every constant is a str, an int, a tuple, a frozen dataclass, a `MappingProxyType` or a
`type` alias).
"""

import ast
from pathlib import Path

import pytest

import otc_projector

SRC = Path(otc_projector.__file__).resolve().parent
MUTABLE_CONSTRUCTORS = {
    "list",
    "dict",
    "set",
    "defaultdict",
    "OrderedDict",
    "deque",
    "Counter",
    "bytearray",
}
# (file, name) -> classification. Empty: nothing at module level is a mutable container.
DECLARED_CONSTANTS: dict[tuple[str, str], str] = {}
# class -> the only attributes its __init__ may assign
INIT_ATTRIBUTES = {
    ("infrastructure/messaging/idempotent_consumer.py", "IdempotentConsumer"): {"_collection"},
    (
        "infrastructure/persistence/mongo_read_model_writer.py",
        "MongoReadModelWriter",
    ): {"_collection", "_consumer"},
}


def is_mutable_container(value: ast.expr | None) -> bool:
    if isinstance(value, ast.List | ast.Dict | ast.Set | ast.ListComp | ast.DictComp | ast.SetComp):
        return True
    if isinstance(value, ast.Call):
        func = value.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        return name in MUTABLE_CONSTRUCTORS
    return False


def module_level_containers(source: str) -> list[str]:
    """Names assigned a mutable container at module level, in any module-level region (an `if`,
    a `try`, a `with`), but not inside a function or a class body."""
    found: list[str] = []

    def visit(statements: list[ast.stmt]) -> None:
        for statement in statements:
            if isinstance(statement, ast.Assign) and is_mutable_container(statement.value):
                found.extend(t.id for t in statement.targets if isinstance(t, ast.Name))
            elif isinstance(statement, ast.AnnAssign) and is_mutable_container(statement.value):
                if isinstance(statement.target, ast.Name):
                    found.append(statement.target.id)
            elif isinstance(statement, ast.If | ast.Try | ast.With | ast.For | ast.While):
                visit(list(statement.body))
                visit(list(getattr(statement, "orelse", [])))
                for handler in getattr(statement, "handlers", []):
                    visit(list(handler.body))
                visit(list(getattr(statement, "finalbody", [])))

    visit(ast.parse(source).body)
    return found


def init_assignments(source: str, class_name: str) -> set[str]:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for member in node.body:
                if isinstance(member, ast.FunctionDef) and member.name == "__init__":
                    return {
                        target.attr
                        for statement in ast.walk(member)
                        if isinstance(statement, ast.Assign | ast.AnnAssign)
                        for target in (
                            statement.targets
                            if isinstance(statement, ast.Assign)
                            else [statement.target]
                        )
                        if isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    }
    raise AssertionError(f"{class_name} has no __init__")


def test_pr51_no_module_level_mutable_state_and_no_writer_state_beyond_the_collection() -> None:
    files = sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)
    assert len(files) > 25, f"the scan covered {len(files)} files"
    found = {
        (str(p.relative_to(SRC)), name)
        for p in files
        for name in module_level_containers(p.read_text(encoding="utf-8"))
    }
    assert found == set(DECLARED_CONSTANTS), (
        f"module-level mutable containers outside the declared set: "
        f"{sorted(found - set(DECLARED_CONSTANTS))}"
    )
    for (relative, class_name), allowed in INIT_ATTRIBUTES.items():
        assigned = init_assignments((SRC / relative).read_text(encoding="utf-8"), class_name)
        assert assigned == allowed, f"{class_name}.__init__ assigns {sorted(assigned)}"


@pytest.mark.parametrize(
    "source",
    [
        "CACHE = {}\n",
        "SEEN: set[str] = set()\n",
        "ITEMS = []\n",
        "from collections import defaultdict\nBY = defaultdict(list)\n",
        "import collections\nQ = collections.deque()\n",
        "SQUARES = [n * n for n in range(3)]\n",
        "if True:\n    CACHE = {}\n",
        "try:\n    CACHE = dict()\nexcept ImportError:\n    pass\n",
    ],
)
def test_pr51_sentinel_every_form_of_module_level_container_is_seen(source: str) -> None:
    assert module_level_containers(source), source


def test_pr51_sentinel_immutable_constants_and_function_locals_are_not_state() -> None:
    quiet = (
        "from types import MappingProxyType\nT = (1, 2)\nS = 'x'\nM = MappingProxyType({'a': 1})\n"
        "def f():\n    cache = {}\n    return cache\nclass C:\n    items = []\n"
    )
    assert module_level_containers(quiet) == []


def test_pr51_sentinel_an_extra_init_attribute_is_seen() -> None:
    source = (
        "class W:\n    def __init__(self, c):\n        self._collection = c\n"
        "        self._seen = set()\n"
    )
    assert init_assignments(source, "W") == {"_collection", "_seen"}
