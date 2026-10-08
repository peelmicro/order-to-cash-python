"""Every environment read reachable from a composition root goes through a settings class that the
root constructs (#8 id 56, feature 15; chosen ONCE, inherited by every later composition root).

#8's defect: 102 environment reads across 18 files and no test could notice one being deleted,
because no test compiled a composition root. The mechanism here has three halves, each its own
guard:

1. NOTHING ELSE reads the environment (this file): no `os.environ`, `os.getenv`, `os.getenvb`,
   `environ` / `getenv` imported from `os`, and no `dotenv` loader, anywhere in the service's
   source. So the population of reads IS the population of settings fields. AST, any region.
2. THE ROOT constructs every settings class (this file): each `BaseSettings` subclass defined in
   the service is called by name inside `composition.load_settings`, so a class cannot be written
   and forgotten.
3. EACH FIELD is read, and reaches the thing it configures (per service, behavioural):
   `services/orders/tests/unit/test_orders_settings_env.py` (every variable sets exactly its field;
   the population of variables is a literal) and
   `services/orders/tests/integration/test_orders_host_lifespan.py` (the values reach the adapters
   through the real lifespan); Fulfillment's are `test_fulfillment_settings_env.py` and
   `test_fulfillment_host_lifespan.py`.

The composition roots are found by glob, and their names are a literal so a new root (feature 17
added `fulfillment`) is a deliberate edit here, with its own halves 3. Loses, stated: a read through
`importlib`/`getattr(os, ...)`, a subprocess's environment, and a literal path to a `.env` read by
`open()`; none exists, and the census below would show a new `open(` of a `.env`.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOTS = sorted(REPO_ROOT.glob("services/*/src/otc_*/composition.py"))
EXPECTED_ROOTS = ["fulfillment", "orders", "seed"]
# Roots whose settings classes are all built by `composition.load_settings` (half 2). The seed's
# root (feature 12, a one-shot CLI) receives its `SeedSettings` from the entry point instead, so it
# is held to half 1 (nothing reads the environment directly) and to the class literal only.
LOAD_SETTINGS_ROOTS = ["fulfillment", "orders"]
EXPECTED_SETTINGS = {
    "fulfillment": {
        "FulfillmentDatabaseSettings",
        "KafkaSettings",
        "NatsSettings",
        "OutboxRelaySettings",
        "ResponderSettings",
        "ServerSettings",
    },
    "orders": {
        "KafkaSettings",
        "NatsSettings",
        "OrdersDatabaseSettings",
        "OutboxRelaySettings",
        "SagaSettings",
        "ServerSettings",
    },
    "seed": {"SeedSettings"},
}
ENV_ATTRIBUTES = {"environ", "environb", "getenv", "getenvb", "putenv"}


def service_of(root: Path) -> str:
    return root.parent.name.removeprefix("otc_")


def sources(root: Path) -> list[Path]:
    return sorted(p for p in root.parent.rglob("*.py") if "__pycache__" not in p.parts)


def environment_reads(source: str) -> list[str]:
    """Every reference to the process environment, in any region of the module."""
    tree = ast.parse(source)
    os_names = {"os"}
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "os":
                    os_names.add(alias.asname or "os")
                if alias.name.split(".")[0] in {"dotenv", "environs", "decouple"}:
                    found.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in {"dotenv", "environs", "decouple"}:
                found.append(f"line {node.lineno}: from {node.module} import ...")
            if node.module == "os":
                for alias in node.names:
                    if alias.name in ENV_ATTRIBUTES or alias.name == "*":
                        found.append(f"line {node.lineno}: from os import {alias.name}")
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in ENV_ATTRIBUTES
            and isinstance(node.value, ast.Name)
            and node.value.id in os_names
        ):
            found.append(f"line {node.lineno}: {node.value.id}.{node.attr}")
    return found


def settings_classes(source: str) -> set[str]:
    return {
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ClassDef)
        and any(ast.unparse(base).split(".")[-1] == "BaseSettings" for base in node.bases)
    }


def constructed_in_load_settings(root_source: str) -> set[str]:
    tree = ast.parse(root_source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "load_settings":
            return {
                call.func.id
                for call in ast.walk(node)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            }
    return set()


def test_the_composition_roots_are_exactly_the_literal() -> None:
    assert [service_of(r) for r in ROOTS] == EXPECTED_ROOTS
    with_load_settings = [
        service_of(r) for r in ROOTS if "def load_settings" in r.read_text(encoding="utf-8")
    ]
    assert with_load_settings == LOAD_SETTINGS_ROOTS


def test_nothing_in_a_service_with_a_root_reads_the_environment_directly() -> None:
    offenders = {
        f"{p.relative_to(REPO_ROOT).as_posix()} {hit}"
        for root in ROOTS
        for p in sources(root)
        for hit in environment_reads(p.read_text(encoding="utf-8"))
    }
    assert not offenders, f"read the environment through a settings class instead: {offenders}"


def test_every_settings_class_of_the_service_is_the_literal_and_is_built_by_load_settings() -> None:
    for root in ROOTS:
        defined: set[str] = set()
        for p in sources(root):
            defined |= settings_classes(p.read_text(encoding="utf-8"))
        assert defined == EXPECTED_SETTINGS[service_of(root)], defined
        if service_of(root) in LOAD_SETTINGS_ROOTS:
            built = constructed_in_load_settings(root.read_text(encoding="utf-8"))
            assert defined <= built, f"load_settings never builds {sorted(defined - built)}"


# ---- sentinels: each half MUST be able to fail


def test_sentinel_every_form_of_environment_read_is_seen() -> None:
    forms = {
        "os.environ[...]": "import os\nx = os.environ['A']\n",
        "os.environ.get": "import os\nx = os.environ.get('A')\n",
        "os.getenv": "import os\nx = os.getenv('A')\n",
        "aliased os": "import os as o\nx = o.getenv('A')\n",
        "from os import environ": "from os import environ\nx = environ['A']\n",
        "from os import getenv as g": "from os import getenv as g\n",
        "dotenv loader": "from dotenv import load_dotenv\n",
        "import dotenv": "import dotenv\n",
        "in a dead region": "import os\nif False:\n    x = os.getenv('A')\n",
        "in a function": "import os\ndef f():\n    return os.environ\n",
    }
    for name, source in forms.items():
        assert environment_reads(source), name


def test_sentinel_text_that_only_names_the_environment_is_not_a_read() -> None:
    quiet = '# os.environ["A"]\ns = """\nos.getenv("A")\n"""\nimport os\nx = os.path.join("a")\n'
    assert not environment_reads(quiet)


def test_sentinel_a_settings_class_the_root_forgets_is_detected() -> None:
    settings = (
        "from pydantic_settings import BaseSettings\nclass A(BaseSettings): ...\n"
        "class B(BaseSettings): ...\n"
    )
    root = "def load_settings():\n    return Bundle(a=A())\n"
    assert settings_classes(settings) == {"A", "B"}
    assert constructed_in_load_settings(root) == {"Bundle", "A"}
    assert not settings_classes(settings) <= constructed_in_load_settings(root)
    assert constructed_in_load_settings("def other():\n    return A()\n") == set()
