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
   is what F-a/F-b fail), and no two registrations share one statement (what a helper `def` driven
   by a loop, F-g, fails, however its list was filled, F-j).
3. TABLES: the built dispatcher's tables hold exactly the recorded registrations (a table poked
   directly, F-c, would hold a key nothing recorded), and exactly one `Dispatcher` was built, by
   `HandlerRegistry.build`.

Armed: the fixtures below run the same probe on a package that does F-g + F-j as ONE pipeline (and
on F-a, and an import-time registry); each must fail by the intended clause, and the control package
with two plain statements must pass, so the instrument can say yes as well as no.
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
SERVICES = ["orders"]  # services that have a composition root with `build_dispatcher`

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
            subject = None
            if args and isinstance(args[0], type):
                subject = args[0].__module__ + "." + args[0].__qualname__
            events.append({"phase": phase, "what": label, "subject": subject,
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


def registration_statements(composition_file: str) -> set[int]:
    """Line numbers of statements that are `<x>.register_*(...)` calls, in the root's AST."""
    tree = ast.parse(Path(composition_file).read_text(encoding="utf-8"))
    return {
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr in KINDS
    }


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
    # The population is a literal: `PlaceOrderCommand` (feature 15), the ten saga fact commands and
    # the five dispatch-owed events (feature 16), sorted as the probe reports them.
    assert result["tables"]["commands"] == sorted(
        [
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
        ]
    )
    assert result["tables"]["events"] == sorted(
        f"otc_orders.application.saga.dispatch_events.{name}"
        for name in (
            "OrderPlacedFactRecorded",
            "OrderMarkedStockReserved",
            "CreditRejectionRecorded",
            "OrderConfirmedBySaga",
            "OrderMarkedDespatched",
        )
    )


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
