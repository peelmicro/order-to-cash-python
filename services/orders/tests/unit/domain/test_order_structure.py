"""Structural guards for what Python cannot enforce at compile time (`design.md` L4, L5).

Tasks 3.9, 3.13 and 3.14.

C# and TypeScript refuse `order.status = x` from outside the class; Python does not. The property
"only these functions write this field" is therefore a test over the SOURCE (AST), with sentinels
for every hiding place it must see and two spellings it must not mistake for a write.
"""

import ast
import inspect
import typing
from collections.abc import Callable
from pathlib import Path

import pytest

import otc_orders.domain
from otc_orders.domain.order import Order
from otc_orders.domain.state_machine import LEGAL_EDGES, Edge
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.order_status import OrderStatus, parse_order_status
from otc_shared_kernel import Money, Quantity

DOMAIN_DIR = Path(otc_orders.domain.__file__).parent
ORDERS_PACKAGE_DIR = DOMAIN_DIR.parent
ORDER_PY = DOMAIN_DIR / "order.py"

STATUS_TOKENS = [
    "placed",
    "stock_reserved",
    "credit_approved",
    "confirmed",
    "despatched",
    "invoiced",
    "paid",
    "completed",
    "cancelled",
]

# Every private attribute holding aggregate state -> the functions allowed to write it.
LITERAL_WRITERS: dict[str, set[str]] = {
    "_status": {"__init__", "_transition_to"},
    "_cancellation_reason": {"__init__", "_transition_to"},
    "_lines": {"__init__", "_commit_lines"},
    "_initial_amount": {"__init__", "_commit_lines"},
    "_initial_discount": {"__init__", "_commit_lines"},
    "_total_amount": {"__init__", "_commit_lines"},
    "_updated_at": {"__init__", "_transition_to", "_commit_lines"},
}
PRIVATE_NAMES = set(LITERAL_WRITERS)
REFLECTION_NAMES = {"setattr", "__setattr__", "delattr", "__delattr__"}


# ---------------------------------------------------------------------------- the instrument


def _targets(node: ast.AST) -> list[ast.expr]:
    """Every assignment target of a statement, unpacking tuples and lists."""
    raw: list[ast.expr] = []
    if isinstance(node, ast.Assign):
        raw = list(node.targets)
    elif isinstance(node, ast.AugAssign | ast.AnnAssign):
        raw = [node.target]
    elif isinstance(node, ast.Delete):
        raw = list(node.targets)
    elif isinstance(node, ast.For | ast.AsyncFor):
        raw = [node.target]
    elif isinstance(node, ast.With | ast.AsyncWith):
        raw = [item.optional_vars for item in node.items if item.optional_vars is not None]
    flat: list[ast.expr] = []
    while raw:
        target = raw.pop()
        if isinstance(target, ast.Tuple | ast.List):
            raw.extend(target.elts)
        elif isinstance(target, ast.Starred):
            raw.append(target.value)
        else:
            flat.append(target)
    return flat


def writers_of_private_state(source: str) -> dict[str, set[str]]:
    """private attribute -> names of the innermost functions that write `<anything>.<attribute>`.

    Walks the whole tree, so a write inside `if False:` or `if TYPE_CHECKING:` counts: this guard
    reads what the source says, not what runs.
    """
    found: dict[str, set[str]] = {}

    def visit(node: ast.AST, function: str) -> None:
        for target in _targets(node):
            if isinstance(target, ast.Attribute) and target.attr in PRIVATE_NAMES:
                found.setdefault(target.attr, set()).add(function)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                visit(child, child.name)
            elif isinstance(child, ast.Lambda):
                visit(child, "<lambda>")
            else:
                visit(child, function)

    visit(ast.parse(source), "<module>")
    return found


def reflection_references(source: str) -> list[int]:
    """Lines referring to `setattr` / `__setattr__` / `delattr`, as a name or an attribute."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Name) and node.id in REFLECTION_NAMES) or (
            isinstance(node, ast.Attribute) and node.attr in REFLECTION_NAMES
        ):
            lines.append(node.lineno)
    return lines


def private_reads_from_outside(source: str) -> list[int]:
    """Lines accessing a private state name on an object that is not `self`."""
    return [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute)
        and node.attr in PRIVATE_NAMES
        and not (isinstance(node.value, ast.Name) and node.value.id == "self")
    ]


MUST_BE_SEEN_AS_A_WRITE = {
    "a plain write in another method": "class O:\n    def other(self):\n        self._status = 1\n",
    "a write inside if False": (
        "class O:\n    def m(self):\n        if False:\n            self._status = 1\n"
    ),
    "a write inside if TYPE_CHECKING": (
        "class O:\n    def m(self):\n        if TYPE_CHECKING:\n            self._status = 1\n"
    ),
    "an augmented write": "class O:\n    def m(self):\n        self._lines += (1,)\n",
    "an annotated write": "class O:\n    def m(self):\n        self._status: int = 1\n",
    "a tuple-unpacking write": "class O:\n    def m(self):\n        self._status, x = 1, 2\n",
    "a write through another object": "def m(order):\n    order._status = 1\n",
    "a delete": "class O:\n    def m(self):\n        del self._status\n",
}
MUST_BE_SEEN_AS_REFLECTION = {
    "setattr": 'class O:\n    def m(self, x):\n        setattr(self, "_status", x)\n',
    "object.__setattr__": (
        'class O:\n    def m(self, x):\n        object.__setattr__(self, "_status", x)\n'
    ),
}
MUST_NOT_COUNT = {
    "the name in a comment": "class O:\n    def m(self):\n        pass  # self._status = 1\n",
    "the name in a string": 'class O:\n    def m(self):\n        x = "self._status = 1"\n',
    "a read": "class O:\n    def m(self):\n        return self._status\n",
    "the name in a docstring": 'class O:\n    def m(self):\n        """self._status = 1"""\n',
}


@pytest.mark.parametrize("shape", sorted(MUST_BE_SEEN_AS_A_WRITE))
def test_the_writer_scan_sees_a_private_write_wherever_it_hides(shape: str) -> None:
    found = writers_of_private_state(MUST_BE_SEEN_AS_A_WRITE[shape])
    assert found, f"the writer scan failed to see: {shape}"


@pytest.mark.parametrize("shape", sorted(MUST_BE_SEEN_AS_REFLECTION))
def test_the_reflection_scan_sees_setattr_in_both_spellings(shape: str) -> None:
    assert reflection_references(MUST_BE_SEEN_AS_REFLECTION[shape]), shape


@pytest.mark.parametrize("shape", sorted(MUST_NOT_COUNT))
def test_the_writer_scan_does_not_mistake_text_for_a_write(shape: str) -> None:
    assert writers_of_private_state(MUST_NOT_COUNT[shape]) == {}, f"false positive on: {shape}"


# ---------------------------------------------------------------------------------- the guards


def test_private_state_has_exactly_the_literal_writers() -> None:
    found = writers_of_private_state(ORDER_PY.read_text(encoding="utf-8"))
    assert found == LITERAL_WRITERS, (
        "private state is written by functions the design does not allow: "
        + "; ".join(
            f"{name}: found {sorted(found.get(name, set()))}, allowed {sorted(allowed)}"
            for name, allowed in LITERAL_WRITERS.items()
            if found.get(name, set()) != allowed
        )
    )


def test_no_domain_module_refers_to_setattr_or_dunder_setattr() -> None:
    offenders = {
        path.relative_to(ORDERS_PACKAGE_DIR).as_posix(): lines
        for path in sorted(DOMAIN_DIR.rglob("*.py"))
        if (lines := reflection_references(path.read_text(encoding="utf-8")))
    }
    assert not offenders, (
        f"setattr/__setattr__ in the domain (a write the AST cannot name): {offenders}"
    )
    assert len(list(DOMAIN_DIR.rglob("*.py"))) >= 10, "the domain walk found almost nothing"


def _public_callables() -> dict[str, Callable[..., object]]:
    return {
        name: member
        for name, member in inspect.getmembers(Order)
        if not name.startswith("_") and callable(member) and not isinstance(member, property)
    }


def _mentions(annotation: object, wanted: type) -> bool:
    return annotation is wanted or any(
        _mentions(argument, wanted) for argument in typing.get_args(annotation)
    )


def test_no_public_method_takes_an_order_status_and_none_targets_placed() -> None:
    public = _public_callables()
    assert {
        "place",
        "rehydrate",
        "mark_stock_reserved",
        "approve_credit",
        "confirm",
        "mark_despatched",
        "mark_invoiced",
        "mark_paid",
        "complete",
        "cancel",
        "add_line",
        "remove_line",
        "change_line",
        "pull_domain_events",
        "clear_domain_events",
    } <= set(public)
    offenders = [
        f"{name}({parameter.name})"
        for name, member in public.items()
        for parameter in inspect.signature(member).parameters.values()
        if _mentions(parameter.annotation, OrderStatus)
    ]
    assert not offenders, f"a public method lets a caller name a target status: {offenders}"

    into_placed = [(parse_order_status(token), OrderStatus.PLACED) for token in STATUS_TOKENS]
    assert len(into_placed) == 9
    assert not any(Edge(source, target) in LEGAL_EDGES for source, target in into_placed)


def test_public_state_has_no_setter_and_nothing_outside_the_class_reaches_private_state(
    placed_order: Order,
) -> None:
    for name, value in {
        "status": OrderStatus.PAID,
        "cancellation_reason": CancellationReason.OPERATOR_CANCELLED,
        "lines": (),
        "initial_amount": Money(1, "EUR"),
        "initial_discount": Money(1, "EUR"),
        "total_amount": Money(1, "EUR"),
    }.items():
        assert isinstance(inspect.getattr_static(Order, name), property), name
        assert inspect.getattr_static(Order, name).fset is None, name
        with pytest.raises(AttributeError):
            setattr(placed_order, name, value)
    with pytest.raises(AttributeError):
        placed_order.invented = 1  # type: ignore[attr-defined]  # `__slots__` forbids new names
    assert not hasattr(placed_order, "__dict__")
    assert placed_order.lines[0].quantity == Quantity(3)

    offenders = {
        path.relative_to(ORDERS_PACKAGE_DIR).as_posix(): lines
        for path in sorted(ORDERS_PACKAGE_DIR.rglob("*.py"))
        if (lines := private_reads_from_outside(path.read_text(encoding="utf-8")))
    }
    assert not offenders, f"private aggregate state reached from outside `self`: {offenders}"


def test_the_outside_access_scan_sees_a_foreign_read() -> None:
    assert private_reads_from_outside("def m(order):\n    return order._status\n")
    assert not private_reads_from_outside(
        "class O:\n    def m(self):\n        return self._status\n"
    )
