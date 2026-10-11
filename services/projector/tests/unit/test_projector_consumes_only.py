"""K2 (PR1, PR21): this service consumes ONE Kafka stream, subscribes to NOTHING on NATS, answers no
request, owns no write model, and serves exactly two routes.

AST, so a comment or a string cannot satisfy a claim and a form that IS code cannot hide: exactly
one module imports `AIOKafkaConsumer`; no `subscribe` / `request` / `request_many` call exists
anywhere (NATS is used to PUBLISH only: the update signal); the task dict `start_runtime` builds
has exactly one key; no module is named for a ledger, an outbox or a responder; no write-model
package is imported. The Kafka PRODUCER half is
`tests/architecture/test_kafka_client_confinement.py`.
"""

import ast
from pathlib import Path

import pytest

import otc_projector
from otc_projector.presentation.app import create_app

SRC = Path(otc_projector.__file__).resolve().parent
NATS_SUBSCRIBING = {"subscribe", "request", "request_many"}
WRITE_MODEL_ROOTS = {"sqlalchemy", "asyncpg", "alembic"}
DOCS_ROUTES = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}  # FastAPI's own
SERVED = {"/health/live", "/health/ready"}


def python_files(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*.py"))
        if "__pycache__" not in p.parts
    }


def consumer_importers(files: dict[str, str]) -> list[str]:
    found = []
    for name, source in files.items():
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.ImportFrom)
                and any(alias.name == "AIOKafkaConsumer" for alias in node.names)
            ) or (isinstance(node, ast.Attribute) and node.attr == "AIOKafkaConsumer"):
                found.append(name)
    return sorted(set(found))


def nats_subscriptions(files: dict[str, str]) -> list[str]:
    return [
        f"{name}:{node.lineno} {node.func.attr}"
        for name, source in files.items()
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in NATS_SUBSCRIBING
    ]


def task_keys(source: str) -> set[str]:
    """Every string key assigned into a `tasks[...]` mapping."""
    keys = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "tasks"
                    and isinstance(target.slice, ast.Constant)
                ):
                    keys.add(str(target.slice.value))
    return keys


def ledger_table_uses(files: dict[str, str]) -> list[str]:
    """A `__tablename__` declaration, or the string `processed_events` outside a docstring (the
    variant's banner explains that it has NO such table; explaining is not declaring)."""
    found = []
    for name, source in files.items():
        tree = ast.parse(source)
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__tablename__" for t in node.targets
            ):
                found.append(f"{name}:{node.lineno} __tablename__")
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and "processed_events" in node.value
            ):
                found.append(f"{name}:{node.lineno} 'processed_events'")
    return found


def write_model_imports(files: dict[str, str]) -> list[str]:
    found: list[str] = []
    for name, source in files.items():
        for node in ast.walk(ast.parse(source)):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            found.extend(
                f"{name}: imports {m}" for m in modules if m.split(".")[0] in WRITE_MODEL_ROOTS
            )
    return found


def test_pr1_one_kafka_consumer_task_over_the_three_fact_topics_and_no_nats_subscription_of_any_kind() -> (  # noqa: E501
    None
):
    files = python_files(SRC)
    assert len(files) > 25, f"the scan covered {len(files)} files"
    assert consumer_importers(files) == ["infrastructure/messaging/kafka_fact_subscriber.py"]
    assert nats_subscriptions(files) == [], "the projector subscribes to or requests on NATS"
    assert task_keys(files["composition.py"]) == {"fact-consumer"}, (
        "start_runtime must build exactly one task"
    )


def test_pr21_no_write_model_dependency_no_ledger_table_no_nats_request_and_only_the_two_health_routes() -> (  # noqa: E501
    None
):
    files = python_files(SRC)
    assert write_model_imports(files) == []
    names = [
        name
        for name in files
        if any(word in Path(name).stem for word in ("outbox", "relay", "responder", "models"))
    ]
    assert names == [], f"a module named for a write-model concern exists: {names}"
    assert ledger_table_uses(files) == [], "a processed_events ledger table is declared or named"
    routes = {getattr(route, "path", "") for route in create_app().routes}
    assert routes - DOCS_ROUTES == SERVED, f"the app serves {sorted(routes - DOCS_ROUTES)}"


@pytest.mark.parametrize(
    "source",
    [
        "async def f(nc):\n    await nc.subscribe('readmodel.>')\n",
        "async def f(nc):\n    await nc.request('x', b'')\n",
        "async def f(nc):\n    async for r in nc.request_many('x', b''):\n        pass\n",
        "def f(nc):\n    if False:\n        nc.subscribe('x')\n",
    ],
)
def test_pr1_sentinel_every_form_of_nats_subscription_is_seen(source: str) -> None:
    assert nats_subscriptions({"x.py": source})


@pytest.mark.parametrize(
    "source",
    [
        'class P:\n    __tablename__ = "processed_events"\n',
        'TABLE = "processed_events"\n',
        'if False:\n    NAME = "processed_events"\n',
    ],
)
def test_pr21_sentinel_a_ledger_table_in_any_region_is_seen(source: str) -> None:
    assert ledger_table_uses({"x.py": source})
    assert ledger_table_uses({"x.py": '"""There is no processed_events table here."""\n'}) == []


def test_pr1_sentinel_a_second_consumer_importer_and_a_second_task_key_are_seen() -> None:
    assert consumer_importers(
        {
            "a.py": "from aiokafka import AIOKafkaConsumer\n",
            "b.py": "import aiokafka\nx = aiokafka.AIOKafkaConsumer\n",
        }
    ) == ["a.py", "b.py"]
    assert task_keys('tasks["a"] = 1\ntasks["b"] = 2\n') == {"a", "b"}
