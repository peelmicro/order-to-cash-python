"""The domain unit tests touch no store, broker, clock or framework (`design.md` 11.1, task 6.4).

The import set of every `.py` in this directory is a subset of a literal: `pytest`, the standard
library, `otc_shared_kernel` and `otc_orders.domain`. The two checks that need `otc_contracts` live
one directory up, in `test_order_domain_contract_parity.py`.
"""

import ast
import sys
from pathlib import Path

ALLOWED_ROOTS = {"pytest", "otc_shared_kernel", "otc_orders"}
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
        if name == "otc_orders.domain" or name.startswith("otc_orders.domain."):
            continue
        bad.append(name)
    return bad


def test_domain_unit_tests_import_only_pytest_the_standard_library_the_kernel_and_the_orders_domain() -> (  # noqa: E501
    None
):
    files = sorted(HERE.glob("*.py"))
    assert len(files) >= 10, "the purity walk found almost no test files"
    offenders = {
        path.name: bad for path in files if (bad := _violations(path.read_text(encoding="utf-8")))
    }
    assert not offenders, f"domain unit tests may not import: {offenders}"


def test_the_purity_scan_sees_each_kind_of_forbidden_import() -> None:
    assert _violations("import otc_contracts\n") == ["otc_contracts"]
    assert _violations("from otc_orders.infrastructure import settings\n")
    assert _violations("from otc_orders import presentation\n") == ["otc_orders"]
    assert _violations("import sqlalchemy.orm\n")
    assert _violations("from fastapi import FastAPI\n")
    assert not _violations(
        "import dataclasses\nimport pytest\nfrom otc_orders.domain.order import Order\n"
        "from otc_shared_kernel import Money\n"
    )
