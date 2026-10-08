"""The domain unit tests touch no store, broker, clock or framework (`design.md` 13.1, task B9).

The import set of every `.py` in this directory is a subset of a literal: `pytest`, the standard
library, `otc_shared_kernel` and `otc_fulfillment.domain`. Ported from
`services/orders/tests/unit/domain/test_domain_tests_are_pure.py`.
"""

import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _import_names(source: str) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


def _violations(source: str) -> list[str]:
    bad: list[str] = []
    for name in _import_names(source):
        root = name.split(".")[0]
        if root in sys.stdlib_module_names or root in {"pytest", "otc_shared_kernel"}:
            continue
        if name == "otc_fulfillment.domain" or name.startswith("otc_fulfillment.domain."):
            continue
        bad.append(name)
    return bad


def test_domain_unit_tests_import_only_pytest_the_standard_library_the_kernel_and_the_fulfillment_domain() -> (  # noqa: E501
    None
):
    files = sorted(HERE.glob("*.py"))
    assert len(files) >= 6, "the purity walk found almost no test files"
    offenders = {
        path.name: bad for path in files if (bad := _violations(path.read_text(encoding="utf-8")))
    }
    assert not offenders, f"domain unit tests may not import: {offenders}"


def test_the_purity_scan_sees_each_kind_of_forbidden_import() -> None:
    assert _violations("import otc_contracts\n") == ["otc_contracts"]
    assert _violations("from otc_fulfillment.infrastructure import settings\n")
    assert _violations("from otc_fulfillment import presentation\n") == ["otc_fulfillment"]
    assert _violations("import sqlalchemy.orm\n")
    assert _violations("from fastapi import FastAPI\n")
    assert not _violations(
        "import dataclasses\nimport pytest\n"
        "from otc_fulfillment.domain.stock_item import StockItem\n"
        "from otc_shared_kernel import Quantity\n"
    )
