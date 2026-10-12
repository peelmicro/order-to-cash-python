"""Acceptance item 5 (carried from `cqrs_dispatcher`) and item 8 (the lambda-handler residual), for
the Gateway's real root.

Item 5's behavioural probe (`tests/architecture/test_registration_behaviour.py`) runs this service
in a fresh interpreter: importing every module creates no registry and calls no `register_*`; every
registration comes from a distinct statement of `composition.py`; the built tables equal the
recorded registrations. Its `TABLES["gateway"]` is a literal of 5 commands and 9 queries.

Item 8: the probe records no handler class for a registration whose handler is a FACTORY LAMBDA, so
a lambda whose body calls a module-level factory returning another handler would pass. The
Gateway's root registers none: every handler is a class, and this file keeps that true. The day a
lambda handler is registered here, `test_the_root_registers_no_lambda_handler` fails, and the
residual's re-open trigger ("any service registers a lambda handler whose body calls a non-class
factory") is on the table.
"""

import ast
import inspect
from pathlib import Path

from otc_cqrs import HandlerRegistry
from otc_gateway import composition
from otc_gateway.application.scope import GatewayScope

ROOT = Path(composition.__file__)


def test_the_root_registers_no_lambda_handler() -> None:
    tree = ast.parse(ROOT.read_text(encoding="utf-8"))
    registrations = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"register_command", "register_query", "register_event"}
    ]
    lambdas = [n for n in ast.walk(tree) if isinstance(n, ast.Lambda)]

    assert len(registrations) == 14  # the real n, counted from the AST of the root
    for call in registrations:
        assert not any(isinstance(n, ast.Lambda) for arg in call.args for n in ast.walk(arg)), (
            f"line {call.lineno}: a lambda handler; extend the registration probe to record and "
            "name the lambda's handler class (feature 25 acceptance item 8)"
        )
    # the only lambda in the root is a readiness probe, outside `register_handlers`
    assert all(lam.lineno > max(c.lineno for c in registrations) for lam in lambdas)


def test_every_registered_handler_is_a_class_of_the_application_layer() -> None:
    registry = HandlerRegistry[GatewayScope]()
    composition.register_handlers(registry)

    factories = registry.registered_factories()

    assert len(factories) == 14
    for factory in factories:
        assert inspect.isclass(factory), f"{factory!r} is not a class"
        assert factory.__module__.startswith("otc_gateway.application."), factory
        assert factory.__name__.endswith("Handler")


def test_every_handler_class_is_registered_for_exactly_one_message() -> None:
    registry = HandlerRegistry[GatewayScope]()
    composition.register_handlers(registry)

    names = [f.__qualname__ for f in registry.registered_factories()]

    assert len(names) == len(set(names)) == 14
