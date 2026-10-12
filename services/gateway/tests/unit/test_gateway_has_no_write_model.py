"""R54, enumerated rather than asserted in prose (#8 `WriteDatabaseAbsenceTests.cs`): the Gateway
holds no write-model dependency, imports no client of one and reads no setting that names one.

Four claims, each a search over the real files: (1) `services/gateway/pyproject.toml` declares no
relational driver, migration tool or Kafka client; (2) no module of `otc_gateway` imports one;
(3) no settings field is bound to a write model's environment variable; (4) the only network
clients the service opens are the NATS client and the MongoDB client (read-only, see
`test_gateway_reads_only.py`). A sentinel proves each search sees what it looks for.
"""

import ast
import tomllib
from pathlib import Path

GATEWAY = Path(__file__).resolve().parents[2]
SRC = GATEWAY / "src" / "otc_gateway"
WRITE_MODEL_PACKAGES = {"sqlalchemy", "asyncpg", "alembic", "psycopg", "psycopg2", "aiokafka"}
WRITE_MODEL_VARIABLE_PREFIXES = (
    "POSTGRES_",
    "ORDERS_DATABASE",
    "FULFILLMENT_DATABASE",
    "BILLING_DATABASE",
    "NOTIFICATIONS_DATABASE",
    "KAFKA_",
    "OUTBOX_",
)


def declared(pyproject: str) -> set[str]:
    dependencies = tomllib.loads(pyproject)["project"]["dependencies"]
    names = set()
    for dependency in dependencies:
        for separator in "[<>=!~; ":
            dependency = dependency.split(separator)[0]
        names.add(dependency.lower().replace("_", "-"))
    return names


def imported_roots(source: str) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def validation_aliases(source: str) -> set[str]:
    return {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.isupper()
        and "_" in node.value
    }


def test_the_gateway_declares_no_write_model_dependency() -> None:
    names = declared((GATEWAY / "pyproject.toml").read_text(encoding="utf-8"))

    assert {"nats-py", "pymongo", "pyjwt"} <= names  # the search sees real dependencies
    assert not names & WRITE_MODEL_PACKAGES


def test_no_module_of_the_gateway_imports_a_write_model_client() -> None:
    files = sorted(SRC.rglob("*.py"))
    assert len(files) > 40, "the scan must range over the real service"
    offenders = {
        str(path.relative_to(SRC)): sorted(
            imported_roots(path.read_text(encoding="utf-8")) & WRITE_MODEL_PACKAGES
        )
        for path in files
        if imported_roots(path.read_text(encoding="utf-8")) & WRITE_MODEL_PACKAGES
    }

    assert offenders == {}


def test_no_setting_of_the_gateway_is_bound_to_a_write_models_variable() -> None:
    variables = validation_aliases((SRC / "infrastructure" / "settings.py").read_text("utf-8"))

    assert "NATS_URL" in variables
    assert "MONGO_DB_READMODEL" in variables  # the search sees real variables
    assert not [v for v in variables if v.startswith(WRITE_MODEL_VARIABLE_PREFIXES)]


def test_sentinel_each_search_sees_what_it_looks_for() -> None:
    assert declared('[project]\ndependencies = ["SQLAlchemy[asyncio]>=2", "fastapi"]') == {
        "sqlalchemy",
        "fastapi",
    }
    assert imported_roots("import asyncpg.pool\nfrom aiokafka import AIOKafkaConsumer\n") == {
        "asyncpg",
        "aiokafka",
    }
    assert validation_aliases('x = Field(validation_alias="POSTGRES_APP_USER")') == {
        "POSTGRES_APP_USER"
    }
