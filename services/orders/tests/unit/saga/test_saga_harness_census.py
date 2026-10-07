"""Only the harness starts the consumer (task 10.1).

In spirit, #8 id 74's `KafkaGroupHostWrappingTests`.

A test that built `SagaFactsConsumerTask` or `KafkaFactSubscriber` itself would join the
`orders.saga` group without the harness's offset baseline and without deleting the group afterwards,
so the next test would inherit its committed offsets. The census reads the AST of every
`integration/saga/ test_*.py`: none may import or name either class (the harness fixture in
`conftest.py` drives the real lifespan, which is the only way the consumer is started).

A sentinel module that does is reported, in each form the population could take (an import, an
alias, an attribute reach, a use inside `if TYPE_CHECKING:`), and text that only mentions the names
is not.
"""

import ast
from pathlib import Path

SAGA_TESTS = Path(__file__).resolve().parents[2] / "integration" / "saga"
FORBIDDEN = {"SagaFactsConsumerTask", "KafkaFactSubscriber"}


def references(source: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom | ast.Import):
            found.update(alias.name.split(".")[-1] for alias in node.names)
        elif isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
    return found & FORBIDDEN


def offenders(directory: Path) -> dict[str, set[str]]:
    return {
        path.name: hits
        for path in sorted(directory.glob("test_*.py"))
        if (hits := references(path.read_text(encoding="utf-8")))
    }


def test_no_saga_test_module_starts_the_consumer_except_through_the_harness() -> None:
    modules = sorted(SAGA_TESTS.glob("test_*.py"))
    assert len(modules) >= 8, f"the census must range over the real population: {modules}"
    assert offenders(SAGA_TESTS) == {}


def test_sentinel_a_module_that_starts_the_consumer_itself_is_reported(tmp_path: Path) -> None:
    (tmp_path / "test_clean.py").write_text("from x import SagaFactHandler\n")
    (tmp_path / "test_import.py").write_text("from a import SagaFactsConsumerTask\n")
    (tmp_path / "test_alias.py").write_text("from a import KafkaFactSubscriber as K\n")
    (tmp_path / "test_attribute.py").write_text("import a\nx = a.KafkaFactSubscriber\n")
    (tmp_path / "test_hidden.py").write_text(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n    from a import SagaFactsConsumerTask\n"
    )
    (tmp_path / "test_mention.py").write_text(
        '# SagaFactsConsumerTask\nDOC = "KafkaFactSubscriber"\n"""SagaFactsConsumerTask"""\n'
    )

    assert offenders(tmp_path) == {
        "test_import.py": {"SagaFactsConsumerTask"},
        "test_alias.py": {"KafkaFactSubscriber"},
        "test_attribute.py": {"KafkaFactSubscriber"},
        "test_hidden.py": {"SagaFactsConsumerTask"},
    }
