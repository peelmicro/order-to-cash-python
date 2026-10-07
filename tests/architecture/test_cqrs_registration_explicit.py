"""Handler registration is explicit, in a composition root: no import-time decorators (feature 43).

Round 1 recognised SHAPES (a decorator imported from `otc_cqrs`, a `<x>.register_*(` call) and lost
to a service-local `@handles(X)` collecting into a list that a loop in `composition.py` drains, and
to alias / `partial` / `getattr` forms. This round changes the kind of guard (Phase 7 gate rule;
CLAUDE.md defeat-list row 11): an ALLOW-LIST FROM A CENSUS instead of recognition.

1. otc_cqrs itself holds no module-level state and exports no decorator (rule A).
2. Every decorator in `services/*/src/**/*.py` must be in `ALLOWED_DECORATORS`, a literal from a
   census. Any other decorator fails by file and line until a human adds it with a reason. That is
   what catches a service-local `@handles(X)`, however it is later drained (rule B).
3. `register_command|query|event` may be referenced only in the exact composition root
   `services/<svc>/src/otc_<svc>/composition.py`, and there only as statement-level calls with a
   class reference first (no loop, comprehension, lambda, alias, `partial`, `getattr`) (rule C).

The census command (AST over the globbed population, decorator call stripped to its callee):

    uv run python -c "import ast,glob,collections; c=collections.Counter(); [c.update([ast.unparse(
    d.func if isinstance(d,ast.Call) else d)]) for f in glob.glob('services/*/src/**/*.py',
    recursive=True) for n in ast.walk(ast.parse(open(f).read())) if isinstance(n,(ast.FunctionDef,
    ast.AsyncFunctionDef,ast.ClassDef)) for d in n.decorator_list]; print(dict(c))"

Populations are globbed (never a file list: #8 D10). A row left open under the stopping rule is
stated in the comment block at the bottom of this file.
"""

import ast
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CQRS_SRC = REPO_ROOT / "packages" / "cqrs" / "src" / "otc_cqrs"
SERVICE_SOURCES = "services/*/src/**/*.py"
REGISTER_NAMES = {"register_command", "register_query", "register_event"}

# Census, this round: exactly these seven decorators are used under services/*/src.
ALLOWED_DECORATORS = {
    "app.get": "FastAPI route registration on the app object (health endpoints)",
    "asynccontextmanager": "lifespan context managers",
    "classmethod": "alternative constructors (Order.place / rehydrate style)",
    "dataclass": "value objects and records",
    "model_validator": "pydantic settings cross-field validation",
    "property": "read-only accessors",
    "staticmethod": "pure helpers on a class",
}

ALLOWED_TOP_LEVEL = (
    ast.Import,
    ast.ImportFrom,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.TypeAlias,
)
DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
INDIRECTION = (
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.Lambda,
)


def parse(text: str) -> ast.Module:
    return ast.parse(text)


def service_population() -> list[Path]:
    files = sorted(REPO_ROOT.glob(SERVICE_SOURCES))
    return [p for p in files if "__pycache__" not in p.parts]


def relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def is_composition_root(rel_path: str) -> bool:
    """Exactly `services/<svc>/src/otc_<svc>/composition.py`; a basename match is not enough."""
    parts = rel_path.split("/")
    return (
        len(parts) == 5
        and parts[0] == "services"
        and parts[2] == "src"
        and parts[3] == f"otc_{parts[1]}"
        and parts[4] == "composition.py"
    )


def decorators_in(tree: ast.Module) -> list[tuple[int, str]]:
    """(line, callee text) of every decorator on any def or class, in any region."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, DEFS):
            for decorator in node.decorator_list:
                callee = decorator.func if isinstance(decorator, ast.Call) else decorator
                found.append((decorator.lineno, ast.unparse(callee)))
    return found


def unlisted_decorators(tree: ast.Module) -> list[str]:
    return [
        f"line {n}: @{name}" for n, name in decorators_in(tree) if name not in ALLOWED_DECORATORS
    ]


def register_references(tree: ast.Module) -> list[ast.expr]:
    """Every attribute, name or string literal that names a register_* method."""
    return [
        n
        for n in ast.walk(tree)
        if (isinstance(n, ast.Attribute) and n.attr in REGISTER_NAMES)
        or (isinstance(n, ast.Name) and n.id in REGISTER_NAMES)
        or (isinstance(n, ast.Constant) and n.value in REGISTER_NAMES)
    ]


def references_outside_root(tree: ast.Module) -> list[str]:
    return [f"line {n.lineno}: a reference to a register_* name" for n in register_references(tree)]


def _parents(tree: ast.Module) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def violations_inside_root(tree: ast.Module) -> list[str]:
    """In the root, a register_* reference must be the callee of a statement-level call whose first
    argument is a class reference (a Name or dotted Name), with no loop/comprehension/lambda
    above it inside its function."""
    parents = _parents(tree)
    problems = []
    for ref in register_references(tree):
        line = f"line {ref.lineno}"
        call = parents.get(ref)
        if not (isinstance(ref, ast.Attribute) and isinstance(call, ast.Call) and call.func is ref):
            problems.append(
                f"{line}: register_* used other than as a direct call (alias/partial/str)"
            )
            continue
        if not isinstance(parents.get(call), ast.Expr):
            problems.append(f"{line}: the call is not a statement (its result or the call is used)")
        node: ast.AST | None = call
        while node is not None and not isinstance(node, DEFS):
            if isinstance(node, INDIRECTION):
                problems.append(f"{line}: register_* under a loop, comprehension or lambda")
                break
            node = parents.get(node)
        first = call.args[0] if call.args else None
        is_class_ref = isinstance(first, ast.Name) or (
            isinstance(first, ast.Attribute) and isinstance(first.value, ast.Name | ast.Attribute)
        )
        if not is_class_ref:
            problems.append(f"{line}: first argument is not a class reference")
    return problems


def top_level_state(tree: ast.Module) -> list[str]:
    """Module-level statements that can run code or hold state at import."""
    found: list[str] = []
    for index, node in enumerate(tree.body):
        if isinstance(node, ALLOWED_TOP_LEVEL):
            continue
        if index == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # the module docstring
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "__all__"
        ):
            continue
        found.append(f"line {node.lineno}: {type(node).__name__}")
    return found


def cqrs_functions_used_as_decorators(trees: list[ast.Module]) -> list[str]:
    defined = {
        n.name
        for tree in trees
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    hits = []
    for tree in trees:
        for _, name in decorators_in(tree):
            if name.split("(")[0].split(".")[0] in defined:
                hits.append(f"@{name}")
    return hits


def classify_registration(rel_path: str, tree: ast.Module) -> list[str]:
    """Rule C for one services source file."""
    check = violations_inside_root if is_composition_root(rel_path) else references_outside_root
    return [f"{rel_path} {p}" for p in check(tree)]


def classify(rel_path: str, tree: ast.Module) -> list[str]:
    """Rules B and C for one services source file."""
    decorators = [f"{rel_path} {p}" for p in unlisted_decorators(tree)]
    return decorators + classify_registration(rel_path, tree)


# ------------------------------------------------------------------ the repository


def test_the_populations_are_not_empty() -> None:
    names = {p.name for p in CQRS_SRC.glob("*.py")}
    assert names >= {"dispatcher.py", "handlers.py", "messages.py", "__init__.py"}
    population = service_population()
    assert len(population) > 100, f"suspiciously small services population: {len(population)}"
    assert any(is_composition_root(relative(p)) for p in population), "no composition root found"


def test_otc_cqrs_has_no_module_level_state_that_could_register_at_import() -> None:
    offenders = {
        relative(p): top_level_state(parse(p.read_text())) for p in sorted(CQRS_SRC.glob("*.py"))
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert not offenders, f"otc_cqrs must hold no import-time state or side effects: {offenders}"


def test_otc_cqrs_exports_no_function_applied_as_a_decorator() -> None:
    trees = [parse(p.read_text()) for p in sorted(CQRS_SRC.glob("*.py"))]
    assert not cqrs_functions_used_as_decorators(trees)


def test_every_decorator_under_services_is_in_the_census_allow_list() -> None:
    offenders = [
        problem
        for p in service_population()
        for problem in (f"{relative(p)} {m}" for m in unlisted_decorators(parse(p.read_text())))
    ]
    assert not offenders, (
        f"a decorator outside the allow-list (a handler-registering decorator is forbidden; "
        f"add a legitimate one to ALLOWED_DECORATORS with a reason): {offenders}"
    )


def test_the_decorator_allow_list_is_exactly_the_census_of_the_real_population() -> None:
    used: Counter[str] = Counter()
    for p in service_population():
        used.update(name for _, name in decorators_in(parse(p.read_text())))
    assert set(used) == set(ALLOWED_DECORATORS), (
        f"unused allow-list entries: {sorted(set(ALLOWED_DECORATORS) - set(used))}; "
        f"used but unlisted: {sorted(set(used) - set(ALLOWED_DECORATORS))}"
    )


def test_register_references_exist_only_in_the_exact_composition_root_as_direct_calls() -> None:
    offenders = [
        problem
        for p in service_population()
        for problem in classify_registration(relative(p), parse(p.read_text()))
    ]
    assert not offenders, f"registration belongs in composition.py, as plain calls: {offenders}"


# ---- sentinels: each rule must be able to fail

HANDLER_FILE_B1 = (
    "HANDLERS = []\n"
    "def handles(t):\n"
    "    def deco(cls):\n"
    "        HANDLERS.append((t, cls))\n"
    "        return cls\n"
    "    return deco\n"
    "@handles(PlaceOrder)\n"
    "class PlaceOrderHandler: ...\n"
)
ROOT = "services/orders/src/otc_orders/composition.py"
NESTED = "services/orders/src/otc_orders/application/handlers/composition.py"


def test_sentinel_b1_a_service_local_registering_decorator_is_detected() -> None:
    hits = classify("services/orders/src/otc_orders/application/h.py", parse(HANDLER_FILE_B1))
    assert any("@handles" in h for h in hits), hits


def test_sentinel_c1_a_loop_draining_a_list_in_the_composition_root_is_detected() -> None:
    source = (
        "def wire(registry):\n    for t, c in HANDLERS:\n        registry.register_command(t, c)\n"
    )
    hits = classify(ROOT, parse(source))
    assert any("loop" in h for h in hits), hits
    comprehension = "def wire(r):\n    [r.register_command(t, c) for t, c in H]\n"
    assert any("loop, comprehension" in h for h in classify(ROOT, parse(comprehension)))


def test_sentinel_c2_a_bound_method_alias_is_detected() -> None:
    source = "def wire(r):\n    reg = r.register_command\n    reg(A, f)\n"
    assert classify(ROOT, parse(source))
    assert classify("services/orders/src/otc_orders/application/x.py", parse(source))


def test_sentinel_c3_functools_partial_is_detected() -> None:
    source = "import functools\ndef wire(r):\n    functools.partial(r.register_command, A)(f)\n"
    assert classify(ROOT, parse(source))


def test_sentinel_c4_getattr_with_the_method_name_is_detected() -> None:
    source = 'def wire(r):\n    getattr(r, "register_command")(A, f)\n'
    assert classify(ROOT, parse(source))
    assert classify("services/orders/src/otc_orders/application/x.py", parse(source))


def test_sentinel_a_file_named_composition_py_at_a_non_root_path_is_not_exempt() -> None:
    call = "def wire(r):\n    r.register_command(A, f)\n"
    assert not classify(ROOT, parse(call)), "the exact root must be allowed plain calls"
    assert not is_composition_root(NESTED)
    assert classify(NESTED, parse(call)), "a sibling basename must not be exempt"
    assert not is_composition_root("services/orders/src/otc_billing/composition.py")
    assert not is_composition_root("services/orders/src/otc_orders/composition.py.bak")


def test_sentinel_plain_registration_in_the_root_is_clean() -> None:
    source = (
        "def wire(r):\n"
        "    r.register_command(PlaceOrder, lambda s: PlaceOrderHandler(s.session))\n"
        "    r.register_query(mod.GetOrder, lambda s: GetOrderHandler(s.session))\n"
        "    r.register_event(OrderPlaced, lambda s: Notify())\n"
    )
    assert not classify(ROOT, parse(source))


def test_sentinel_a_call_with_a_non_class_first_argument_is_detected() -> None:
    source = "def wire(r):\n    r.register_command(make_type(), f)\n"
    assert any("class reference" in h for h in classify(ROOT, parse(source)))


def test_sentinel_text_that_only_looks_like_registration_is_not_a_hit() -> None:
    quiet = '# r.register_command(A, f)\ns = """\nr.register_command(A, f)\n"""\n'
    assert not classify("services/orders/src/otc_orders/application/x.py", parse(quiet))


def test_sentinel_top_level_state_is_detected() -> None:
    assert top_level_state(parse('"""doc"""\nREGISTRY = {}\n'))
    assert top_level_state(parse("import x\nREGISTRY.append(1)\n"))
    assert top_level_state(parse("if False:\n    pass\n"))
    assert not top_level_state(parse('"""doc"""\nimport x\n__all__ = ["a"]\ndef f(): ...\n'))


def test_sentinel_a_cqrs_function_used_as_a_decorator_is_detected() -> None:
    assert cqrs_functions_used_as_decorators(
        [parse("def handler(t):\n    return lambda f: f\n@handler(int)\nclass H: ...\n")]
    )


# Residual, carried (review round 2, section 3): shapes that still register without a decorator
# or a literal `register_*` name are NOT closed by rules B and C: F-a/F-b a computed
# `getattr(r, "register_" + kind)`, F-g a `register_*` call in a helper `def` that the root's loop
# calls, F-i a decorator applied by call (`handles(X)(cls)`), F-j import-time self-registration
# through `__init_subclass__`. The guard for them is a behavioural one (importing a service creates
# no registry and calls no `register_*`; the built tables equal the calls recorded from
# `composition.py`), carried as acceptance items on features 15, 17, 19, 23, 24 and 25, which build
# the composition roots. F-c (reaching `HandlerRegistry._commands` directly) is closed by ruff
# SLF001; F-d (building a `Dispatcher` without `build`) by the construction-site guard below.


# ---- F-d: `Dispatcher(...)` is constructed only inside HandlerRegistry.build

DISPATCHER_SOURCES = ("services/*/src/**/*.py", "packages/*/src/**/*.py")
THE_ONE_SITE = [("packages/cqrs/src/otc_cqrs/dispatcher.py", "HandlerRegistry", "build")]


def dispatcher_constructions(tree: ast.Module) -> list[tuple[str | None, str | None]]:
    """(enclosing class, enclosing function) of every call whose callee is `Dispatcher`,
    `<x>.Dispatcher` or `Dispatcher[...]`."""
    parents = _parents(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if isinstance(callee, ast.Subscript):
            callee = callee.value
        named = (isinstance(callee, ast.Name) and callee.id == "Dispatcher") or (
            isinstance(callee, ast.Attribute) and callee.attr == "Dispatcher"
        )
        if not named:
            continue
        function = klass = None
        cursor: ast.AST | None = node
        while cursor is not None:
            if function is None and isinstance(cursor, ast.FunctionDef | ast.AsyncFunctionDef):
                function = cursor.name
            if isinstance(cursor, ast.ClassDef):
                klass = cursor.name
                break
            cursor = parents.get(cursor)
        found.append((klass, function))
    return found


def all_dispatcher_constructions() -> list[tuple[str, str | None, str | None]]:
    files = sorted({p for pattern in DISPATCHER_SOURCES for p in REPO_ROOT.glob(pattern)})
    return [
        (relative(p), klass, function)
        for p in files
        if "__pycache__" not in p.parts
        for klass, function in dispatcher_constructions(parse(p.read_text()))
    ]


def test_dispatcher_is_constructed_only_inside_handler_registry_build() -> None:
    """Building a `Dispatcher` any other way skips startup validation entirely (review F-d).

    Loses (stated, not chased): an aliased import (`Dispatcher as D`), `type(d)(...)`, and
    `getattr`/`importlib` access; `ruff` and review cover those, and #8's `Dispatcher` is equally
    public.
    """
    assert all_dispatcher_constructions() == THE_ONE_SITE


def test_sentinel_every_construction_form_of_dispatcher_is_detected() -> None:
    for source in (
        "d = Dispatcher({}, {}, {})\n",
        "d = otc_cqrs.Dispatcher({}, {}, {})\n",
        "d = otc_cqrs.dispatcher.Dispatcher({}, {}, {})\n",
        "d = Dispatcher[Scope]({}, {}, {})\n",
        "def f():\n    return Dispatcher({}, {}, {})\n",
    ):
        assert dispatcher_constructions(parse(source)), source
    assert not dispatcher_constructions(parse("d: Dispatcher[Scope] = registry.build()\n"))
    assert dispatcher_constructions(
        parse("class HandlerRegistry:\n    def build(self):\n        return Dispatcher(1, 2, 3)\n")
    ) == [("HandlerRegistry", "build")]
