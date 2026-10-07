"""Nothing on the saga path parses an inbound `orderReference` (SO12; `design.md` 5.5).

`^ORD-[0-9]{6,}$` admits `ORD-000000`, which the kernel's canonical parse refuses
(review_shared_kernel Q2). The behavioural half is `integration/saga/test_saga_preconditions.py`
(`test_so8_...`, `test_so12_...`); this is the structural half: no module of the saga path imports,
or names, `OrderNumber`, `BusinessReference` or `parse_order_reference`.

The population is every module under `application/saga/`, `infrastructure/saga/` and the
presentation consumer. An AST is read: a mention in a comment or a string is not counted, a use
inside `if TYPE_CHECKING:` is. Sentinels prove each form is seen (defeat-list rows 4-6, 11).
"""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[3] / "src" / "otc_orders"
FORBIDDEN = {"OrderNumber", "BusinessReference", "parse_order_reference"}


def population() -> list[Path]:
    return sorted(
        [
            *PACKAGE.joinpath("application", "saga").rglob("*.py"),
            *PACKAGE.joinpath("infrastructure", "saga").rglob("*.py"),
            PACKAGE / "presentation" / "saga_facts_consumer.py",
        ]
    )


def reference_names(source: str) -> set[str]:
    """Every forbidden name the module imports (aliased or not) or uses, in any region."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom | ast.Import):
            found.update(alias.name.split(".")[-1] for alias in node.names)
        elif isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
    return found & FORBIDDEN


def test_no_module_on_the_saga_path_imports_or_names_a_reference_parser() -> None:
    files = population()
    names = {path.name for path in files}
    assert {
        "fact_handler.py",
        "command_payloads.py",
        "saga_facts_consumer.py",
        "fast_path.py",
    } <= names
    offenders = {
        str(path.relative_to(PACKAGE)): hits
        for path in files
        if (hits := reference_names(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}, f"these modules name a reference parser on the saga path: {offenders}"


def test_sentinel_an_import_a_use_and_an_alias_are_seen() -> None:
    assert reference_names("from otc_shared_kernel import OrderNumber\n") == {"OrderNumber"}
    assert reference_names("x = OrderNumber.parse(reference)\n") == {"OrderNumber"}
    assert reference_names("from otc_shared_kernel import BusinessReference as B\n") == {
        "BusinessReference"
    }
    assert reference_names("import otc_shared_kernel as k\ny = k.OrderNumber\n") == {"OrderNumber"}
    assert reference_names("from a.b import parse_order_reference\n") == {"parse_order_reference"}


def test_sentinel_a_use_inside_type_checking_is_counted() -> None:
    source = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from k import OrderNumber\n"
    assert reference_names(source) == {"OrderNumber"}


def test_sentinel_a_mention_in_a_comment_or_a_string_is_not_counted() -> None:
    source = '# OrderNumber.parse(x)\nDOC = "BusinessReference"\n"""parse_order_reference"""\n'
    assert reference_names(source) == set()
