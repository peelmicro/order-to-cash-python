"""The kernel's whole name surface is a literal allowlist, read from the SOURCE (AST).

`vars(Money)` (test_money.py) sees what exists at runtime. This file sees what the source
declares, including regions that never execute (`if TYPE_CHECKING:`) and module scope, so a
`to_major_units(money) -> Fraction` function, or a type-checking-only `to_major` method, fails
here by name even if no other guard recognises its spelling.
"""

import ast
import importlib
from pathlib import Path
from types import ModuleType

import pytest

import otc_shared_kernel

KERNEL_DIR = Path(otc_shared_kernel.__file__).parent

# Keyed by dotted path below the package (`text.__init__` for a subpackage; `__init__` is the
# package root).
# Every name bound at module scope in each kernel module (defs, classes, assignments, imports),
# walking into `if`/`try`/`with` blocks but not into function or class bodies. Dunders excluded.
MODULE_NAMES: dict[str, set[str]] = {
    "__init__": {
        "BusinessReference",
        "CreditLineReference",
        "DespatchReference",
        "InvoiceReference",
        "OrderNumber",
        "DEFAULT_EXPONENT",
        "NON_DEFAULT_EXPONENTS",
        "exponent_of",
        "AggregateRoot",
        "Entity",
        "CurrencyMismatchError",
        "DomainError",
        "InvalidBusinessReferenceError",
        "InvalidCurrencyCodeError",
        "InvalidGlnError",
        "InvalidMoneyAmountError",
        "InvalidUniqueIdError",
        "QuantityMustBePositiveError",
        "GLN",
        "Money",
        "Quantity",
        "UniqueId",
    },
    "business_reference": {
        "dataclass",
        "ClassVar",
        "Self",
        "InvalidBusinessReferenceError",
        "_MIN_DIGITS",
        "_MAX_SEQUENCE",
        "BusinessReference",
        "OrderNumber",
        "DespatchReference",
        "InvoiceReference",
        "CreditLineReference",
    },
    "currency_exponent": {
        "Mapping",
        "MappingProxyType",
        "DEFAULT_EXPONENT",
        "NON_DEFAULT_EXPONENTS",
        "exponent_of",
    },
    "entity": {"UniqueId", "Entity", "AggregateRoot"},
    "errors": {
        "DomainError",
        "InvalidCurrencyCodeError",
        "InvalidMoneyAmountError",
        "CurrencyMismatchError",
        "QuantityMustBePositiveError",
        "InvalidGlnError",
        "InvalidBusinessReferenceError",
        "InvalidUniqueIdError",
    },
    "gln": {"dataclass", "InvalidGlnError", "_LENGTH", "_BODY_LENGTH", "_is_ascii_digits", "GLN"},
    "money": {
        "dataclass",
        "CurrencyMismatchError",
        "InvalidCurrencyCodeError",
        "InvalidMoneyAmountError",
        "Quantity",
        "MIN_MINOR_UNITS",
        "MAX_MINOR_UNITS",
        "_is_alpha3",
        "Money",
    },
    "quantity": {"dataclass", "QuantityMustBePositiveError", "Quantity"},
    "unique_id": {
        "uuid",
        "dataclass",
        "Self",
        "InvalidUniqueIdError",
        "_CANONICAL_LENGTH",
        "UniqueId",
    },
}

# Every name bound directly in a class body of Money (source level, TYPE_CHECKING blocks included).
MONEY_CLASS_BODY_NAMES = {
    "amount",
    "currency",
    "__post_init__",
    "zero",
    "is_negative",
    "is_zero",
    "add",
    "subtract",
    "multiply",
    "compare",
    "__add__",
    "__sub__",
    "__mul__",
    "__lt__",
    "__le__",
    "__gt__",
    "__ge__",
    "__str__",
    "_require_same_currency",
}


def _bound_names(statements: list[ast.stmt]) -> set[str]:
    names: set[str] = set()
    for node in statements:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import):
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(a.asname or a.name for a in node.names)
        for field in ("body", "orelse", "finalbody"):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                names |= _bound_names(getattr(node, field, []))
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                names |= _bound_names(handler.body)
    return names


def module_names(source: str) -> set[str]:
    return {n for n in _bound_names(ast.parse(source).body) if not n.startswith("__")}


def class_body_names(source: str, class_name: str) -> set[str]:
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return _bound_names(node.body)
    raise AssertionError(f"class {class_name} not found")


def _on_disk_modules() -> set[str]:
    """Every .py under the kernel, recursively, keyed by dotted path (`text.__init__`)."""
    return {
        ".".join(p.relative_to(KERNEL_DIR).with_suffix("").parts) for p in KERNEL_DIR.rglob("*.py")
    }


def _source_of(module: str) -> Path:
    return KERNEL_DIR.joinpath(*module.split(".")).with_suffix(".py")


def _import_name(module: str) -> str:
    dotted = "otc_shared_kernel" if module == "__init__" else f"otc_shared_kernel.{module}"
    return dotted.removesuffix(".__init__")


def test_the_kernel_module_population_is_the_literal_list() -> None:
    on_disk = _on_disk_modules()
    assert on_disk == set(MODULE_NAMES), (
        f"a kernel module was added or removed: +{sorted(on_disk - set(MODULE_NAMES))} "
        f"-{sorted(set(MODULE_NAMES) - on_disk)}"
    )


@pytest.mark.parametrize("module", sorted(MODULE_NAMES))
def test_every_kernel_module_binds_exactly_the_allowlisted_top_level_names(module: str) -> None:
    found = module_names(_source_of(module).read_text())
    expected = MODULE_NAMES[module]
    assert found == expected, (
        f"{module}.py top-level names changed: +{sorted(found - expected)} "
        f"-{sorted(expected - found)}"
    )


def runtime_names(module: str) -> set[str]:
    """Every non-dunder name the imported module really holds, whatever form bound it
    (tuple unpacking, walrus, a `for` target, `globals()[...] =`). A package holds its imported
    submodules as attributes; those are modules the population test already lists, not names."""
    name = _import_name(module)
    imported = importlib.import_module(name)
    return {
        n
        for n, value in vars(imported).items()
        if not n.startswith("__")
        and not (isinstance(value, ModuleType) and value.__name__.startswith(f"{name}."))
    }


@pytest.mark.parametrize("module", sorted(MODULE_NAMES))
def test_every_kernel_module_holds_at_runtime_only_the_allowlisted_names(module: str) -> None:
    found = runtime_names(module)
    extra = found - MODULE_NAMES[module]
    assert not extra, f"{module} holds names at runtime that the allowlist lacks: {sorted(extra)}"


def test_money_class_body_binds_exactly_the_allowlisted_names_even_under_type_checking() -> None:
    found = class_body_names((KERNEL_DIR / "money.py").read_text(), "Money")
    assert found == MONEY_CLASS_BODY_NAMES, (
        f"Money's class body changed: +{sorted(found - MONEY_CLASS_BODY_NAMES)} "
        f"-{sorted(MONEY_CLASS_BODY_NAMES - found)}"
    )


# --- the instrument itself: each hiding place MUST be seen -------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "def to_major_units(m): ...\n",
        "if TYPE_CHECKING:\n    def to_major_units(m): ...\n",
        "try:\n    pass\nexcept ValueError:\n    X = 1\n",
        "RATE = 100\n",
        "from fractions import Fraction\n",
        "import fractions as fr\n",
    ],
)
def test_module_scan_sees_a_name_wherever_it_is_bound(source: str) -> None:
    assert module_names(source), source


def test_class_scan_sees_a_name_inside_a_type_checking_block() -> None:
    source = "class Money:\n    if TYPE_CHECKING:\n        def to_major(self) -> 'x': ...\n"
    assert class_body_names(source, "Money") == {"to_major"}
