"""No module outside `otc_orders/domain/order.py` constructs an `Order` (feature 15, F7 carried).

`Order.__init__` takes already-validated state (the three totals included), so a caller that built
an `Order` directly would skip `place`'s checks or `rehydrate`'s. The repository mapper reaches an
`Order` only through `Order.place` / `Order.rehydrate`. This is that claim as a census (a search
result, not a belief), AST over every file of `services/orders/src/otc_orders`:

* a call is a CONSTRUCTION of the domain aggregate when its callee is `cls` (any class: a
  classmethod alternative constructor is exactly how `place` and `rehydrate` build one), or a
  name that resolves to `otc_orders.domain.order.Order` in that module: `Order` inside
  `order.py`, a name imported from that module (aliases included: `import ... as`,
  `from ... import Order as O`), or the dotted forms `<module alias>.Order` /
  `otc_orders.domain.order.Order`. A `Order(` in `models.py` is the ORM class (a local
  `class Order(Base)`), which that module does not import from the domain, so it is not a
  construction of the aggregate: classified, not excluded.
* the expected population is the literal below: `cls(` in `place` and in `rehydrate`, nothing else.
* the other half of the claim: where the two factories are CALLED (`Order.place` by the place-order
  handler, `Order.rehydrate` by the row mapper) is also a literal.

Hits (this round, by `scan`): `domain/order.py` `cls(` x2 (`place`, `rehydrate`); `models.py` has a
`class Order(Base)` and no call. Loses, stated: `type(order)(...)`, `getattr`/`importlib` access and
`copy`/`pickle`; ruff and review cover those, and the instrument is armed against the aliasing forms
that were reachable by accident.
"""

import ast
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "services" / "orders" / "src" / "otc_orders"
DOMAIN_ORDER_MODULE = "otc_orders.domain.order"
ORDER_PY = "domain/order.py"

Site = tuple[str, str | None, str | None]  # (file, enclosing class, enclosing function)

EXPECTED_CONSTRUCTIONS: Counter[Site] = Counter(
    {(ORDER_PY, "Order", "place"): 1, (ORDER_PY, "Order", "rehydrate"): 1}
)
EXPECTED_FACTORY_CALLS: Counter[tuple[str, str, str | None]] = Counter(
    {
        ("place", "application/commands/place_order.py", "handle"): 1,
        ("rehydrate", "infrastructure/persistence/order_mapper.py", "order_of"): 1,
    }
)


def _domain_order_names(tree: ast.Module, rel_path: str) -> tuple[set[str], set[str]]:
    """(names bound to the aggregate class, names bound to its module) in this module."""
    classes: set[str] = {"Order"} if rel_path == ORDER_PY else set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == DOMAIN_ORDER_MODULE:
            classes.update(a.asname or a.name for a in node.names if a.name == "Order")
        elif isinstance(node, ast.ImportFrom) and node.module == "otc_orders.domain":
            modules.update(a.asname or a.name for a in node.names if a.name == "order")
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name == DOMAIN_ORDER_MODULE:
                    modules.add(a.asname or DOMAIN_ORDER_MODULE)
    return classes, modules


def _is_aggregate(callee: ast.expr, classes: set[str], modules: set[str]) -> bool:
    if isinstance(callee, ast.Name):
        return callee.id in classes
    if isinstance(callee, ast.Attribute) and callee.attr == "Order":
        return ast.unparse(callee.value) in modules
    return False


def _enclosing(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> tuple[str | None, str | None]:
    function = klass = None
    cursor: ast.AST | None = node
    while cursor is not None:
        if function is None and isinstance(cursor, ast.FunctionDef | ast.AsyncFunctionDef):
            function = cursor.name
        if isinstance(cursor, ast.ClassDef):
            klass = cursor.name
            break
        cursor = parents.get(cursor)
    return klass, function


def constructions(rel_path: str, source: str) -> Counter[Site]:
    tree = ast.parse(source)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    classes, modules = _domain_order_names(tree, rel_path)
    found: Counter[Site] = Counter()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        is_cls = isinstance(node.func, ast.Name) and node.func.id == "cls"
        if is_cls or _is_aggregate(node.func, classes, modules):
            klass, function = _enclosing(node, parents)
            found[(rel_path, klass, function)] += 1
    return found


def factory_calls(rel_path: str, source: str) -> Counter[tuple[str, str, str | None]]:
    tree = ast.parse(source)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    classes, modules = _domain_order_names(tree, rel_path)
    found: Counter[tuple[str, str, str | None]] = Counter()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"place", "rehydrate"}
            and _is_aggregate(node.func.value, classes, modules)
        ):
            found[(node.func.attr, rel_path, _enclosing(node, parents)[1])] += 1
    return found


def population() -> list[tuple[str, str]]:
    return [
        (p.relative_to(SOURCE).as_posix(), p.read_text(encoding="utf-8"))
        for p in sorted(SOURCE.rglob("*.py"))
        if "__pycache__" not in p.parts
    ]


def test_the_population_is_the_whole_orders_source_tree() -> None:
    files = {rel for rel, _ in population()}
    assert len(files) > 40, f"suspiciously small population: {len(files)}"
    assert {ORDER_PY, "infrastructure/persistence/order_mapper.py", "composition.py"} <= files


def test_only_order_py_constructs_an_order_and_only_in_place_and_rehydrate() -> None:
    found: Counter[Site] = Counter()
    for rel, source in population():
        found.update(constructions(rel, source))
    assert found == EXPECTED_CONSTRUCTIONS, (
        f"an Order is constructed outside its factories: {found}"
    )


def test_the_factories_are_called_from_exactly_the_literal_sites() -> None:
    found: Counter[tuple[str, str, str | None]] = Counter()
    for rel, source in population():
        found.update(factory_calls(rel, source))
    assert found == EXPECTED_FACTORY_CALLS


def test_the_orm_class_named_order_is_not_a_construction_of_the_aggregate() -> None:
    models = (SOURCE / "infrastructure/persistence/models.py").read_text(encoding="utf-8")
    assert "class Order(Base)" in models
    assert not constructions("infrastructure/persistence/models.py", models)


# ---- sentinels: each hiding place MUST be seen

MAPPER = "infrastructure/persistence/order_mapper.py"
DIRECT = "from otc_orders.domain.order import Order\ndef f(s):\n    return Order(id=1)\n"


def test_sentinel_a_direct_order_call_in_the_mapper_is_detected() -> None:
    assert constructions(MAPPER, DIRECT) == Counter({(MAPPER, None, "f"): 1})


def test_sentinel_an_aliased_import_is_detected() -> None:
    source = "from otc_orders.domain.order import Order as Agg\ndef f():\n    return Agg()\n"
    assert constructions(MAPPER, source)


def test_sentinel_a_module_alias_and_the_dotted_path_are_detected() -> None:
    alias = "import otc_orders.domain.order as o\ndef f():\n    return o.Order()\n"
    dotted = (
        "import otc_orders.domain.order\ndef f():\n    return otc_orders.domain.order.Order()\n"
    )
    from_package = "from otc_orders.domain import order as o\ndef f():\n    return o.Order()\n"
    assert constructions(MAPPER, alias)
    assert constructions(MAPPER, dotted)
    assert constructions(MAPPER, from_package)


def test_sentinel_a_cls_call_outside_order_py_is_detected() -> None:
    source = "class Mapper:\n    @classmethod\n    def build(cls):\n        return cls()\n"
    assert constructions(MAPPER, source) == Counter({(MAPPER, "Mapper", "build"): 1})


def test_sentinel_a_second_cls_call_in_order_py_raises_the_count() -> None:
    source = (
        "class Order:\n    @classmethod\n    def place(cls):\n"
        "        a = cls()\n        return cls()\n"
    )
    assert constructions(ORDER_PY, source) == Counter({(ORDER_PY, "Order", "place"): 2})


def test_sentinel_the_orm_namesake_and_text_that_only_looks_like_a_call_are_not_hits() -> None:
    orm = "class Order(Base): ...\ndef f():\n    return Order(id=1)\n"
    quiet = '# Order(x)\ns = """\nOrder(x)\n"""\n'
    assert not constructions("infrastructure/persistence/models.py", orm)
    assert not constructions(MAPPER, DIRECT.replace("Order(id=1)", "make()"))
    assert not constructions(MAPPER, quiet)


def test_sentinel_a_factory_called_from_another_site_changes_the_literal() -> None:
    source = "from otc_orders.domain.order import Order\ndef g(s):\n    return Order.rehydrate(s)\n"
    assert factory_calls(MAPPER, source) == Counter({("rehydrate", MAPPER, "g"): 1})
    assert factory_calls(MAPPER, source) != Counter({("rehydrate", MAPPER, "order_of"): 1})
