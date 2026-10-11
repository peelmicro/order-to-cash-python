"""NS9: this service only consumes. It answers no RPC (no NATS), emits no fact (no outbox, no Kafka
producer) and owns exactly one table, the `processed_events` ledger.

Ported from #7's `notifications-consumes-only.spec.ts` (a text scan, one allow-listed exception).
#8 has the equivalent only for the Projector (`ProjectorConsumesOnlyTests.cs`); the claim is the
spec's (`domain-model.md` 6: "Owns no aggregate"; `asyncapi.yaml`: Notifications has `receive`
operations only), so #9 guards it here, on the AST so a comment or a string cannot satisfy it.

The Kafka PRODUCER half is also `tests/architecture/test_kafka_client_confinement.py` (the
subscriber names no producer-side name); this adds NATS, the outbox, and the table census.
"""

import ast
from pathlib import Path

import pytest

import otc_notifications
from otc_notifications.infrastructure.persistence.models import Base

SRC = Path(otc_notifications.__file__).resolve().parent
FORBIDDEN_ROOTS = {"nats"}
FORBIDDEN_NAMES = {"AIOKafkaProducer"}


def python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def violations(files: dict[str, str]) -> list[str]:
    found = []
    for name, source in files.items():
        for node in ast.walk(ast.parse(source)):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules = [node.module]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            for module in modules:
                if module.split(".")[0] in FORBIDDEN_ROOTS:
                    found.append(f"{name}: imports {module}")
                if "outbox" in module.lower():
                    found.append(f"{name}: imports an outbox module ({module})")
            if isinstance(node, ast.ImportFrom):
                found.extend(
                    f"{name}: imports {alias.name}"
                    for alias in node.names
                    if alias.name in FORBIDDEN_NAMES
                )
            if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
                found.append(f"{name}: reaches {node.attr}")
    return found


def test_no_module_of_the_service_imports_nats_an_outbox_or_a_kafka_producer() -> None:
    files = {str(p.relative_to(SRC)): p.read_text(encoding="utf-8") for p in python_files(SRC)}
    assert len(files) > 25, f"the scan covered {len(files)} files"
    assert violations(files) == []


def test_no_file_of_the_service_is_named_for_an_outbox_a_relay_or_a_responder() -> None:
    names = [
        p.name
        for p in python_files(SRC)
        if any(w in p.stem for w in ("outbox", "relay", "responder"))
    ]
    assert names == []


def test_the_only_table_is_the_processed_events_ledger() -> None:
    assert set(Base.metadata.tables) == {"processed_events"}


@pytest.mark.parametrize(
    "source",
    [
        "import nats\n",
        "from nats.aio.client import Client\n",
        "from aiokafka import AIOKafkaProducer\n",
        "import aiokafka\nx = aiokafka.AIOKafkaProducer\n",
        "from otc_notifications.infrastructure.outbox.writer import OutboxWriter\n",
        "from .outbox import relay\n",
    ],
)
def test_sentinel_each_forbidden_form_is_seen(source: str) -> None:
    assert violations({"x.py": source}), source


def test_sentinel_text_that_only_names_them_is_not_a_violation() -> None:
    quiet = '# import nats\nDOC = """from aiokafka import AIOKafkaProducer"""\nNAME = "outbox"\n'
    assert violations({"x.py": quiet}) == []
