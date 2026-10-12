"""Handler registration, proven by BEHAVIOUR (feature 15; feature 43's carried residual rows).

`test_cqrs_registration_explicit.py` recognises shapes (a decorator, a `register_*` literal) and
its own header lists what a syntax guard still loses: F-a/F-b (`getattr(r, "register_" + kind)`),
F-g (a helper `def` that the root's loop calls), F-i (a decorator applied by call) and F-j
(`__init_subclass__` self-registration, drained by the root). #8's defect D10 was a guard that kept
losing to the next shape. This one does not read shapes; it RUNS the service in a fresh interpreter
with `HandlerRegistry` and `Dispatcher` instrumented, and asserts what happened:

1. IMPORT: importing every module of the package (walked, `pkgutil.walk_packages`) creates no
   `HandlerRegistry` and no `Dispatcher` and calls no `register_*`.
2. WIRE: running the composition root (`composition.build_dispatcher()`) records every `register_*`
   call with its CALLER FRAME. Every call comes from `composition.py`, from a statement that IS a
   direct `<x>.register_command|query|event(...)` call (cross-checked against the file's AST, which
   is what F-a/F-b fail), the statement names its message and handler by plain references that are
   not parameters or locals of the enclosing function (what a helper `def` or a loop, F-g, fails
   even with ONE registration), the statement NAMES what it registers (the recorded message class
   is the terminal identifier of its message argument; the recorded handler class, when the
   handler is a class, is the terminal identifier of its handler argument, or appears in a factory
   lambda's body; for a lambda the handler class is not recorded, so only the message is checked
   against it: what F-j alone fails even with ONE registration, `SelfRegistering.message` or a
   global unpacked at import), and no two registrations share one statement (the same defect at
   n >= 2, however the list was filled).
3. TABLES: the built dispatcher's tables hold exactly the recorded registrations (a table poked
   directly, F-c, would hold a key nothing recorded), and exactly one `Dispatcher` was built, by
   `HandlerRegistry.build`.

Armed: the fixtures below run the same probe on a package that does F-g + F-j as ONE pipeline, on
F-j alone at n = 1 (a class-attribute holder; module globals), on a helper `def` nested in the root,
on F-a, and on an import-time registry; each must fail by the intended clause, and the control
package with two plain statements must pass, so the instrument can say yes as well as no.
"""

import ast
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES = [
    "orders",
    "fulfillment",
    "billing",
    "notifications",
    "projector",
    "gateway",
]  # services whose composition root has `build_dispatcher`; the census below keeps it complete

# `PlaceOrderCommand` (feature 15), the ten saga fact commands and the five dispatch-owed events
# (feature 16), `CancelOrderCommand` and two more dispatch-owed events (feature 41: `credit.release`
# and the operator's `stock.release`); Fulfillment (feature 17): three commands, two queries, no
# events (no post-commit in-process hop is owed: the relay is its only post-commit obligation);
# Billing (features 19, 21):
# three commands (hold, release, issue invoice), two queries (credit list, invoice list), no events
# (it consumes no fact and owes no in-process hop either). Notifications (feature 23): the seven
# notify commands, one per notified fact, no query and no event. Projector (feature 24): ONE command
# (`ProjectFactCommand`: the behaviour is uniform in `eventType`, the fourteen variations live in
# `project`), no query and no event; it is also the first service the census below had to name.
TABLES: dict[str, dict[str, list[str]]] = {
    "orders": {
        "commands": [
            "otc_orders.application.commands.cancel_order.CancelOrderCommand",
            "otc_orders.application.commands.place_order.PlaceOrderCommand",
            *(
                f"otc_orders.application.saga.fact_commands.Handle{name}FactCommand"
                for name in (
                    "OrderPlaced",
                    "StockReserved",
                    "StockRejected",
                    "StockReleased",
                    "CreditApproved",
                    "CreditRejected",
                    "OrderDespatched",
                    "InvoiceIssued",
                    "PaymentReceived",
                    "CreditReleased",
                )
            ),
        ],
        # Feature 40: the reference listing behind `catalog.reference.list`.
        "queries": ["otc_orders.application.queries.list_reference_data.ListReferenceDataQuery"],
        "events": [
            f"otc_orders.application.saga.dispatch_events.{name}"
            for name in (
                "OrderPlacedFactRecorded",
                "OrderMarkedStockReserved",
                "CreditRejectionRecorded",
                "OrderConfirmedBySaga",
                "OrderMarkedDespatched",
                "CreditReleaseOwed",
                "OperatorCancelAccepted",
            )
        ],
    },
    "fulfillment": {
        "commands": [
            f"otc_fulfillment.application.messages.{name}"
            for name in (
                "ReserveStockCommand",
                "ReleaseStockCommand",
                "ReplenishStockCommand",
                "CreateDespatchCommand",
            )
        ],
        "queries": [
            f"otc_fulfillment.application.messages.{name}"
            for name in ("CheckStockQuery", "ListStockQuery")
        ],
        "events": [],
    },
    "billing": {
        "commands": [
            f"otc_billing.application.messages.{name}"
            for name in (
                "HoldCreditCommand",
                "ReleaseCreditCommand",
                "IssueInvoiceCommand",
                "RegisterPaymentCommand",
            )
        ],
        "queries": [
            f"otc_billing.application.messages.{name}"
            for name in ("ListCreditQuery", "ListInvoicesQuery")
        ],
        "events": [],
    },
    "notifications": {
        "commands": [
            f"otc_notifications.application.messages.{name}"
            for name in (
                "NotifyOrderPlacedCommand",
                "NotifyOrderConfirmedCommand",
                "NotifyOrderDespatchedCommand",
                "NotifyInvoiceIssuedCommand",
                "NotifyPaymentReceivedCommand",
                "NotifyOrderCompletedCommand",
                "NotifyOrderCancelledCommand",
            )
        ],
        "queries": [],
        "events": [],
    },
}

# Gateway (feature 25): five commands (login, place order, cancel order, register payment, replenish
# stock) and nine queries (current user, order list, order detail, stock, invoices, credits, and the
# three catalog lists), no event. Its root registers NO lambda handler (every handler is a class),
# so the lambda-handler residual of feature 24's review does not apply to it
# (`services/gateway/tests/unit/test_gateway_registration.py` guards that claim).
TABLES["gateway"] = {
    "commands": [
        f"otc_gateway.application.messages.{name}"
        for name in (
            "LoginCommand",
            "PlaceOrderCommand",
            "CancelOrderCommand",
            "RegisterInvoicePaymentCommand",
            "ReplenishStockCommand",
        )
    ],
    "queries": [
        f"otc_gateway.application.messages.{name}"
        for name in (
            "GetCurrentUserQuery",
            "ListOrdersQuery",
            "GetOrderQuery",
            "ListStockQuery",
            "ListInvoicesQuery",
            "ListCreditsQuery",
            "ListProductsQuery",
            "ListRetailersQuery",
            "ListCompaniesQuery",
        )
    ],
    "events": [],
}

TABLES["projector"] = {
    "commands": ["otc_projector.application.messages.ProjectFactCommand"],
    "queries": [],
    "events": [],
}

PROBE = textwrap.dedent(
    """
    import importlib, json, pkgutil, sys

    package, *paths = sys.argv[1:]
    sys.path[:0] = paths
    import otc_cqrs.dispatcher as d

    phase = "import"
    events = []

    def frame_of(depth):
        f = sys._getframe(depth)
        return {"file": f.f_code.co_filename, "line": f.f_lineno, "function": f.f_code.co_name}

    def wrap(cls, name, label):
        original = getattr(cls, name)
        def recorder(self, *args, **kwargs):
            subject = handler = None
            if args and isinstance(args[0], type):
                subject = args[0].__module__ + "." + args[0].__qualname__
            if len(args) > 1 and isinstance(args[1], type):
                handler = args[1].__qualname__  # a factory lambda has no class to name
            events.append({"phase": phase, "what": label, "subject": subject, "handler": handler,
                           "caller": frame_of(2)})  # 0 frame_of, 1 recorder, 2 the caller
            return original(self, *args, **kwargs)
        setattr(cls, name, recorder)

    wrap(d.HandlerRegistry, "__init__", "HandlerRegistry()")
    wrap(d.Dispatcher, "__init__", "Dispatcher()")
    for kind in ("register_command", "register_query", "register_event"):
        wrap(d.HandlerRegistry, kind, kind)

    root = importlib.import_module(package)
    modules = [root.__name__]
    for info in pkgutil.walk_packages(root.__path__, root.__name__ + "."):
        importlib.import_module(info.name)
        modules.append(info.name)

    phase = "wire"
    composition = importlib.import_module(package + ".composition")
    dispatcher = composition.build_dispatcher()
    tables = {
        "commands": sorted(k.__module__ + "." + k.__qualname__ for k in dispatcher._commands),
        "queries": sorted(k.__module__ + "." + k.__qualname__ for k in dispatcher._queries),
        "events": sorted(k.__module__ + "." + k.__qualname__ for k in dispatcher._events),
    }
    print(json.dumps({"events": events, "tables": tables, "modules": modules,
                      "composition_file": composition.__file__}))
    """
)
KINDS = {"register_command": "commands", "register_query": "queries", "register_event": "events"}


def probe(package: str, *extra_paths: Path) -> dict[str, Any]:
    done = subprocess.run(  # noqa: S603 - the interpreter running this test, a fixed script
        [sys.executable, "-c", PROBE, package, *map(str, extra_paths)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, f"the probe could not run {package}:\n{done.stderr}"
    result: dict[str, Any] = json.loads(done.stdout.splitlines()[-1])
    return result


def terminal_identifier(node: ast.AST) -> str | None:
    """`Foo` for `Foo` and for `pkg.Foo`: the last identifier of a plain reference."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def registration_statements(composition_file: str) -> dict[int, dict[str, Any]]:
    """Statements that are `<x>.register_*(...)` calls in the root's AST, by line number, each as
    `{"problems": [...], "message": <terminal identifier of the message argument>, "handler":
    <identifiers the handler argument names: its terminal identifier, or every name in a factory
    lambda's body>}`. Empty problems: the arguments are literal references.

    A registration whose message or handler is a parameter or a locally bound name of the
    enclosing function (a loop variable, an unpacked pair, an alias) is DATA-DRIVEN: the statement
    cannot say what it registers, so one statement may stand for many registrations. This is what
    makes the "distinct statement" clause bite at n = 1, where no second registration shares the
    statement (feature 24 review, B3; the F-g weakness `progress/review_cqrs_dispatcher.md:164`
    recorded: the first-argument check accepted any `Name`, including a parameter)."""
    tree = ast.parse(Path(composition_file).read_text(encoding="utf-8"))
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    def enclosing_function(node: ast.AST) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                return node
        return None

    def bound_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
        arguments = function.args
        names = {
            a.arg
            for a in (
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
                *filter(None, (arguments.vararg, arguments.kwarg)),
            )
        }
        names |= {
            n.id
            for n in ast.walk(function)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
        }
        return names

    found: dict[int, dict[str, Any]] = {}
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr in KINDS
        ):
            continue
        problems: list[str] = []
        function = enclosing_function(node)
        local = bound_names(function) if function is not None else set()
        arguments = node.value.args
        if len(arguments) < 2:
            problems.append("fewer than two positional arguments")
        for position, argument in zip(("message", "handler"), arguments[:2], strict=False):
            if isinstance(argument, ast.Lambda) and position == "handler":
                # a factory (`lambda scope: Saga(scope.x())`): its own parameters are its own;
                # a name it closes over that the enclosing function binds is data-driven
                own = {a.arg for a in (*argument.args.posonlyargs, *argument.args.args)}
                captured = {
                    n.id
                    for n in ast.walk(argument.body)
                    if isinstance(n, ast.Name) and n.id not in own and n.id in local
                }
                if captured:
                    problems.append(
                        f"the handler factory closes over local {sorted(captured)} of "
                        f"`{function.name if function else '?'}`"
                    )
            elif not isinstance(argument, ast.Name | ast.Attribute):
                problems.append(
                    f"the {position} is not a plain reference ({ast.unparse(argument)})"
                )
            elif isinstance(argument, ast.Name) and argument.id in local:
                problems.append(
                    f"the {position} `{argument.id}` is a parameter or a local of "
                    f"`{function.name if function else '?'}`"
                )
        handler_ids: set[str] = set()
        if len(arguments) > 1:
            if isinstance(arguments[1], ast.Lambda):
                for inner in ast.walk(arguments[1].body):
                    if (identifier := terminal_identifier(inner)) is not None:
                        handler_ids.add(identifier)
            elif (identifier := terminal_identifier(arguments[1])) is not None:
                handler_ids.add(identifier)
        found[node.lineno] = {
            "problems": problems,
            "message": terminal_identifier(arguments[0]) if arguments else None,
            "handler": handler_ids,
        }
    return found


def violations(result: dict[str, Any]) -> list[str]:
    """Every clause of the contract the probe's result breaks; empty means the contract holds."""
    found: list[str] = []
    events = result["events"]
    at_import = [e for e in events if e["phase"] == "import"]
    for e in at_import:
        found.append(f"IMPORT: {e['what']} ran while importing ({e['caller']})")
    wiring = [e for e in events if e["phase"] == "wire"]
    registrations = [e for e in wiring if e["what"] in KINDS]
    composition_file = result["composition_file"]
    statements = registration_statements(composition_file)
    sites: dict[tuple[str, int], list[str]] = {}
    for e in registrations:
        caller = e["caller"]
        if caller["file"] != composition_file:
            found.append(
                f"WIRE: {e['what']}({e['subject']}) was called from {caller['file']}:"
                f"{caller['line']}, not from composition.py"
            )
        elif caller["line"] not in statements:
            found.append(
                f"WIRE: {e['what']}({e['subject']}) was reached from composition.py:"
                f"{caller['line']}, which is not a direct `.register_*(...)` statement"
            )
        else:
            statement = statements[caller["line"]]
            for problem in statement["problems"]:
                found.append(
                    f"WIRE: {e['what']}({e['subject']}) at composition.py:{caller['line']} is "
                    f"data-driven: {problem}"
                )
            # the statement must NAME what it registers (feature 24 review, B5): the class the
            # probe saw registered is the terminal identifier of the statement's own argument, so
            # an attribute of a self-registering base or a module global unpacked at import fails
            message = (e["subject"] or "").rsplit(".", 1)[-1]
            if statement["message"] != message:
                found.append(
                    f"WIRE: {e['what']}({e['subject']}) at composition.py:{caller['line']} does "
                    f"not name its message: the statement says `{statement['message']}`"
                )
            handler = (e.get("handler") or "").rsplit(".", 1)[-1]
            if handler and handler not in statement["handler"]:
                found.append(
                    f"WIRE: {e['what']}({e['subject']}) at composition.py:{caller['line']} does "
                    f"not name its handler `{handler}`: the statement says "
                    f"{sorted(statement['handler'])}"
                )
        sites.setdefault((caller["file"], caller["line"]), []).append(e["subject"])
    for (file, line), subjects in sorted(sites.items()):
        if len(subjects) > 1:
            found.append(
                f"WIRE: {len(subjects)} registrations share one statement ({Path(file).name}:"
                f"{line}): {subjects}"
            )
    recorded: dict[str, list[str]] = {"commands": [], "queries": [], "events": []}
    for e in registrations:
        recorded[KINDS[e["what"]]].append(e["subject"])
    for table, keys in result["tables"].items():
        if sorted(set(recorded[table])) != keys:
            found.append(
                f"TABLES: {table} hold {keys} but the recorded registrations are "
                f"{sorted(set(recorded[table]))}"
            )
    built = [e for e in wiring if e["what"] == "Dispatcher()"]
    if len(built) != 1 or not built[0]["caller"]["file"].endswith("otc_cqrs/dispatcher.py"):
        found.append(f"TABLES: expected one Dispatcher built by HandlerRegistry.build, got {built}")
    return found


def composition_roots_with_a_dispatcher(root: Path) -> set[str]:
    """Every service whose `composition.py` defines `build_dispatcher` at module level, read from
    the filesystem (never from `SERVICES`): the population `SERVICES` must equal."""
    found = set()
    for composition in sorted((root / "services").glob("*/src/otc_*/composition.py")):
        tree = ast.parse(composition.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == "build_dispatcher"
            for node in tree.body
        ):
            found.add(composition.parents[2].name)
    return found


def test_the_services_list_is_exactly_the_composition_roots_that_define_a_dispatcher() -> None:
    """A new service with a dispatcher fails here until it joins `SERVICES` and `TABLES`: the
    behavioural probe cannot examine a service nobody listed."""
    assert composition_roots_with_a_dispatcher(REPO_ROOT) == set(SERVICES)
    assert set(TABLES) == set(SERVICES)


def test_census_sentinel_a_dispatcher_root_missing_from_the_list_is_reported(
    tmp_path: Path,
) -> None:
    for name, source in (
        ("listed", "def build_dispatcher():\n    ...\n"),
        ("unlisted", "def build_dispatcher():\n    ...\n"),
        ("plain", "VALUE = 1\n"),
    ):
        package = tmp_path / "services" / name / "src" / f"otc_{name}"
        package.mkdir(parents=True)
        (package / "composition.py").write_text(source, encoding="utf-8")
    assert composition_roots_with_a_dispatcher(tmp_path) == {"listed", "unlisted"}


def test_the_probe_walks_the_whole_package() -> None:
    result = probe("otc_orders")
    modules = set(result["modules"])
    assert len(modules) > 40, f"suspiciously small walk: {len(modules)}"
    assert {
        "otc_orders.composition",
        "otc_orders.main",
        "otc_orders.application.commands.place_order",
        "otc_orders.presentation.orders_create_responder",
    } <= modules


@pytest.mark.parametrize("service", SERVICES)
def test_a_service_registers_only_from_its_composition_root_and_its_tables_match(
    service: str,
) -> None:
    result = probe(f"otc_{service}")

    assert violations(result) == []
    registrations = [e for e in result["events"] if e["what"] in KINDS]
    assert registrations, "the probe saw no registration at all: it would pass for anything"
    # The population is a literal per service (TABLES), sorted as the probe reports it.
    expected = TABLES[service]
    assert result["tables"]["commands"] == sorted(expected["commands"])
    assert result["tables"]["queries"] == sorted(expected["queries"])
    assert result["tables"]["events"] == sorted(expected["events"])


# ---- the instrument must be able to fail: fixture packages

COMMON = """
from otc_cqrs import Command, HandlerRegistry


class PlaceA(Command[None]):
    pass


class PlaceB(Command[None]):
    pass


class HandleA:
    def __init__(self, scope): ...
    async def handle(self, command): ...


class HandleB(HandleA):
    pass
"""


def make_package(root: Path, name: str, *, application: str, composition: str) -> None:
    package = root / name
    (package / "application").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "application" / "__init__.py").write_text("")
    (package / "application" / "handlers.py").write_text(textwrap.dedent(application))
    (package / "composition.py").write_text(textwrap.dedent(composition))


CONTROL = (
    COMMON,
    """
    import otc_probe_control.application as application_package
    from otc_cqrs import HandlerRegistry
    from otc_probe_control.application.handlers import HandleA, HandleB, PlaceA, PlaceB

    def build_dispatcher():
        registry = HandlerRegistry()
        registry.register_command(PlaceA, HandleA)
        registry.register_command(PlaceB, HandleB)
        return registry.build(application_package)
    """,
)

# F-j + F-g as ONE pipeline: handlers self-register at import through __init_subclass__ (no
# decorator, no `register_*` name), and a helper `def` the root's loop calls drains them.
F_G_AND_F_J = (
    COMMON.replace(
        "class HandleA:",
        "HANDLERS = {}\n\n\nclass Base:\n    def __init_subclass__(cls, *, message, **kw):\n"
        "        super().__init_subclass__(**kw)\n        HANDLERS[message] = cls\n\n\n"
        "class HandleA(Base, message=PlaceA):",
    ).replace("class HandleB(HandleA):", "class HandleB(Base, message=PlaceB):"),
    """
    import otc_probe_pipeline.application as application_package
    from otc_cqrs import HandlerRegistry
    from otc_probe_pipeline.application.handlers import HANDLERS

    def _one(registry, message, handler):
        registry.register_command(message, handler)

    def build_dispatcher():
        registry = HandlerRegistry()
        for message, handler in HANDLERS.items():
            _one(registry, message, handler)
        return registry.build(application_package)
    """,
)

# n = 1 (the projector's real population): ONE handler self-registers through `__init_subclass__`
# into a CLASS attribute (no module-level container) and a helper `def` drains it. No two
# registrations share a statement, so only the "plain references" rule can see it (review B3, Q8b).
ONE_COMMON = """
from otc_cqrs import Command


class PlaceA(Command[None]):
    pass


class SelfRegistering:
    handlers = {}

    def __init_subclass__(cls, *, message, **kw):
        super().__init_subclass__(**kw)
        SelfRegistering.handlers = {**SelfRegistering.handlers, message: cls}


class HandleA(SelfRegistering, message=PlaceA):
    def __init__(self, scope): ...
    async def handle(self, command): ...
"""
ONE_PIPELINE = (
    ONE_COMMON,
    """
    import otc_probe_one_helper.application as application_package
    from otc_cqrs import HandlerRegistry
    from otc_probe_one_helper.application.handlers import SelfRegistering

    def _one(registry, message, handler):
        registry.register_command(message, handler)

    def build_dispatcher():
        registry = HandlerRegistry()
        for message, handler in SelfRegistering.handlers.items():
            _one(registry, message, handler)
        return registry.build(application_package)
    """,
)
# the same, with the loop in the root itself (the `.register_*` call sits in the root's function)
ONE_LOOP = (
    ONE_COMMON,
    """
    import otc_probe_one_loop.application as application_package
    from otc_cqrs import HandlerRegistry
    from otc_probe_one_loop.application.handlers import SelfRegistering

    def build_dispatcher():
        registry = HandlerRegistry()
        for message, handler in SelfRegistering.handlers.items():
            registry.register_command(message, handler)
        return registry.build(application_package)
    """,
)
# the handler factory closes over a loop variable
ONE_LAMBDA_CLOSURE = (
    ONE_COMMON,
    """
    import otc_probe_one_lambda.application as application_package
    from otc_cqrs import HandlerRegistry
    from otc_probe_one_lambda.application.handlers import PlaceA, SelfRegistering

    def build_dispatcher():
        registry = HandlerRegistry()
        for _, handler in SelfRegistering.handlers.items():
            registry.register_command(PlaceA, lambda scope: handler(scope))
        return registry.build(application_package)
    """,
)
# n = 1, a direct statement with literal references and a factory over its OWN parameter: passes
ONE_CONTROL = (
    ONE_COMMON,
    """
    import otc_probe_one_control.application as application_package
    from otc_cqrs import HandlerRegistry
    from otc_probe_one_control.application.handlers import HandleA, PlaceA

    def build_dispatcher():
        registry = HandlerRegistry()
        registry.register_command(PlaceA, lambda scope: HandleA(scope))
        return registry.build(application_package)
    """,
)

# the helper `def` NESTED inside the root's function (review B6: premise "the enclosing function is
# the INNERMOST `def`"): its parameters differ from the loop variables, so only the innermost `def`
# knows that `message` is a parameter.
ONE_NESTED_HELPER = (
    ONE_COMMON,
    """
    import otc_probe_one_nested.application as application_package
    from otc_cqrs import HandlerRegistry
    from otc_probe_one_nested.application.handlers import SelfRegistering

    def build_dispatcher():
        registry = HandlerRegistry()

        def _one(message, handler):
            registry.register_command(message, handler)

        for m, h in SelfRegistering.handlers.items():
            _one(m, h)
        return registry.build(application_package)
    """,
)

# F-j ALONE at n = 1 (review B5): ONE statement whose arguments are attributes of the
# self-registering base; no helper, no loop, no local, no second registration on the statement.
ONE_HOLDER_COMMON = """
from otc_cqrs import Command


class PlaceA(Command[None]):
    pass


class SelfRegistering:
    message = None
    handler = None

    def __init_subclass__(cls, *, message, **kw):
        super().__init_subclass__(**kw)
        SelfRegistering.message = message
        SelfRegistering.handler = cls


class HandleA(SelfRegistering, message=PlaceA):
    def __init__(self, scope): ...
    async def handle(self, command): ...
"""
ONE_HOLDER = (
    ONE_HOLDER_COMMON,
    """
    import otc_probe_one_holder.application as application_package
    from otc_cqrs import HandlerRegistry
    from otc_probe_one_holder.application.handlers import SelfRegistering

    def build_dispatcher():
        registry = HandlerRegistry()
        registry.register_command(SelfRegistering.message, SelfRegistering.handler)
        return registry.build(application_package)
    """,
)
# the same, the pair unpacked into module globals at import
ONE_GLOBALS = (
    ONE_HOLDER_COMMON,
    """
    import otc_probe_one_globals.application as application_package
    from otc_cqrs import HandlerRegistry
    from otc_probe_one_globals.application.handlers import SelfRegistering

    _MESSAGE, _HANDLER = SelfRegistering.message, SelfRegistering.handler

    def build_dispatcher():
        registry = HandlerRegistry()
        registry.register_command(_MESSAGE, _HANDLER)
        return registry.build(application_package)
    """,
)
# a statement that names a DIFFERENT class than the one it registers: the message is right but the
# handler argument is an alias for a sibling (the handler clause alone)
ONE_HANDLER_ALIAS = (
    ONE_COMMON,
    """
    import otc_probe_one_alias.application as application_package
    from otc_cqrs import HandlerRegistry
    from otc_probe_one_alias.application.handlers import HandleA as Aliased, PlaceA

    def build_dispatcher():
        registry = HandlerRegistry()
        registry.register_command(PlaceA, Aliased)
        return registry.build(application_package)
    """,
)

F_A = (
    COMMON,
    """
    import otc_probe_getattr.application as application_package
    from otc_cqrs import HandlerRegistry
    from otc_probe_getattr.application.handlers import HandleA, HandleB, PlaceA, PlaceB

    def build_dispatcher():
        registry = HandlerRegistry()
        kind = "command"
        getattr(registry, "register_" + kind)(PlaceA, HandleA)
        getattr(registry, "register_" + kind)(PlaceB, HandleB)
        return registry.build(application_package)
    """,
)

IMPORT_TIME_REGISTRY = (
    COMMON + "\nREGISTRY = HandlerRegistry()\nREGISTRY.register_command(PlaceA, HandleA)\n",
    """
    import otc_probe_import.application as application_package
    from otc_cqrs import HandlerRegistry
    from otc_probe_import.application.handlers import HandleB, PlaceA, PlaceB, REGISTRY

    def build_dispatcher():
        registry = HandlerRegistry()
        registry.register_command(PlaceA, REGISTRY)
        registry.register_command(PlaceB, HandleB)
        return registry.build(application_package)
    """,
)

# the real tables poked directly, bypassing `register_*` (F-c, closed statically by SLF001 too)
TABLE_POKE = (
    COMMON,
    """
    import otc_probe_poke.application as application_package
    from otc_cqrs import HandlerRegistry
    from otc_probe_poke.application.handlers import HandleA, HandleB, PlaceA, PlaceB

    def build_dispatcher():
        registry = HandlerRegistry()
        registry.register_command(PlaceA, HandleA)
        registry._commands.setdefault(PlaceB, []).append(HandleB)
        return registry.build(application_package)
    """,
)

FIXTURES = {
    "control": ("otc_probe_control", CONTROL),
    "pipeline": ("otc_probe_pipeline", F_G_AND_F_J),
    "one_helper": ("otc_probe_one_helper", ONE_PIPELINE),
    "one_loop": ("otc_probe_one_loop", ONE_LOOP),
    "one_lambda": ("otc_probe_one_lambda", ONE_LAMBDA_CLOSURE),
    "one_control": ("otc_probe_one_control", ONE_CONTROL),
    "one_nested": ("otc_probe_one_nested", ONE_NESTED_HELPER),
    "one_holder": ("otc_probe_one_holder", ONE_HOLDER),
    "one_globals": ("otc_probe_one_globals", ONE_GLOBALS),
    "one_alias": ("otc_probe_one_alias", ONE_HANDLER_ALIAS),
    "getattr": ("otc_probe_getattr", F_A),
    "import": ("otc_probe_import", IMPORT_TIME_REGISTRY),
    "poke": ("otc_probe_poke", TABLE_POKE),
}


@pytest.fixture
def fixture_result(tmp_path: Path) -> Any:
    def run(name: str) -> dict[str, Any]:
        package, (application, composition) = FIXTURES[name]
        make_package(tmp_path, package, application=application, composition=composition)
        return probe(package, tmp_path)

    return run


def test_sentinel_the_control_package_with_two_plain_statements_passes(fixture_result: Any) -> None:
    assert violations(fixture_result("control")) == []


def test_sentinel_a_helper_loop_draining_import_time_self_registration_is_caught(
    fixture_result: Any,
) -> None:
    # F-g + F-j as one pipeline: 2 registrations from ONE statement of the helper
    found = violations(fixture_result("pipeline"))

    assert any(v.startswith("WIRE: 2 registrations share one statement") for v in found), found


def test_sentinel_a_computed_getattr_registration_is_caught(fixture_result: Any) -> None:
    found = violations(fixture_result("getattr"))

    assert any("not a direct `.register_*(...)` statement" in v for v in found), found


def test_sentinel_a_registry_created_while_importing_is_caught(fixture_result: Any) -> None:
    found = violations(fixture_result("import"))

    assert any(v.startswith("IMPORT: HandlerRegistry() ran while importing") for v in found), found
    assert any(v.startswith("IMPORT: register_command ran while importing") for v in found), found


def test_sentinel_a_table_poked_without_register_is_caught(fixture_result: Any) -> None:
    found = violations(fixture_result("poke"))

    assert any(v.startswith("TABLES: commands hold") for v in found), found


def test_sentinel_one_control_registration_with_literal_references_passes(
    fixture_result: Any,
) -> None:
    result = fixture_result("one_control")

    assert [e for e in result["events"] if e["what"] in KINDS], "the control registered nothing"
    assert violations(result) == []


@pytest.mark.parametrize("name", ["one_helper", "one_loop"])
def test_sentinel_a_single_registration_driven_by_a_helper_or_a_loop_is_caught(
    fixture_result: Any, name: str
) -> None:
    """B3: at n = 1 no two registrations share a statement; the data-driven statement is caught
    by its message/handler arguments being a parameter or a loop variable."""
    result = fixture_result(name)
    registrations = [e for e in result["events"] if e["what"] in KINDS and e["phase"] == "wire"]
    assert len(registrations) == 1, registrations
    found = violations(result)

    assert any(
        "is data-driven: the message `message` is a parameter or a local" in v for v in found
    ), found
    assert not any("share one statement" in v for v in found), found


def test_sentinel_a_handler_factory_closing_over_a_loop_variable_is_caught(
    fixture_result: Any,
) -> None:
    found = violations(fixture_result("one_lambda"))

    assert any("the handler factory closes over local ['handler']" in v for v in found), found


def test_sentinel_a_helper_def_nested_in_the_root_is_caught_by_the_innermost_function(
    fixture_result: Any,
) -> None:
    """B6: premise (2), the enclosing function is the INNERMOST `def`. The loop variables differ
    from the helper's parameters, so an outermost-`def` lookup finds `message` unbound."""
    result = fixture_result("one_nested")
    registrations = [e for e in result["events"] if e["what"] in KINDS and e["phase"] == "wire"]
    assert len(registrations) == 1, registrations
    found = violations(result)

    assert any(
        "is data-driven: the message `message` is a parameter or a local of `_one`" in v
        for v in found
    ), found


@pytest.mark.parametrize("name", ["one_holder", "one_globals"])
def test_sentinel_f_j_alone_at_n_equals_one_is_caught_by_the_statement_naming_rule(
    fixture_result: Any, name: str
) -> None:
    """B5: ONE self-registering handler, ONE direct statement, no helper, loop or local. Neither
    the 'plain references' rule nor the 'share one statement' rule can see it; the statement
    naming rule does."""
    result = fixture_result(name)
    registrations = [e for e in result["events"] if e["what"] in KINDS and e["phase"] == "wire"]
    assert len(registrations) == 1, registrations
    found = violations(result)

    assert any("does not name its message" in v for v in found), found
    assert any("does not name its handler `HandleA`" in v for v in found), found
    assert not any("data-driven" in v or "share one statement" in v for v in found), found


def test_sentinel_a_handler_argument_that_does_not_carry_the_registered_class_name_is_caught(
    fixture_result: Any,
) -> None:
    found = violations(fixture_result("one_alias"))

    assert any("does not name its handler `HandleA`" in v for v in found), found
    assert not any("does not name its message" in v for v in found), found
