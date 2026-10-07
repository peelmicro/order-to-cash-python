"""Dispatch shape, scope lifetime, async semantics and startup validation of `otc_cqrs`.

The messages and handlers below are the test universe: defining them registers nothing, and every
test registers what it needs explicitly. `FIXTURES` is this module, scanned for the commands and
queries that need a handler.
"""

import asyncio
import gc
import importlib
import sys
import types
import weakref
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from otc_cqrs import (
    Command,
    Dispatcher,
    DispatcherValidationError,
    HandlerNotFoundError,
    HandlerRegistry,
    Query,
)

FIXTURES = sys.modules[__name__]


class FakeSession:
    """Stands in for an AsyncSession: one per inbound message, identified by `id`."""

    def __init__(self) -> None:
        self.id: UUID = uuid4()


@dataclass(frozen=True)
class Scope:
    session: FakeSession


@dataclass(frozen=True)
class PlaceOrder(Command[int]):
    quantity: int


@dataclass(frozen=True)
class Ping(Command[None]):
    pass


@dataclass(frozen=True)
class WhoAmI(Query[UUID]):
    pass


@dataclass(frozen=True)
class CountOrders(Query[int]):
    pass


@dataclass(frozen=True)
class OrderPlaced:
    quantity: int


@dataclass(frozen=True)
class OrderFact(OrderPlaced):
    """A subtype of the event, to prove runtime-type resolution."""


class PlaceOrderHandler:
    async def handle(self, command: PlaceOrder, /) -> int:
        return command.quantity * 2


class PingHandler:
    async def handle(self, command: Ping, /) -> None:
        return None


class SecondPingHandler:
    async def handle(self, command: Ping, /) -> None:
        return None


class WhoAmIHandler:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def handle(self, query: WhoAmI, /) -> UUID:
        return self._session.id


class CountOrdersHandler:
    async def handle(self, query: CountOrders, /) -> int:
        return 3


def wired() -> Dispatcher[Scope]:
    registry: HandlerRegistry[Scope] = HandlerRegistry()
    registry.register_command(PlaceOrder, lambda scope: PlaceOrderHandler())
    registry.register_command(Ping, lambda scope: PingHandler())
    registry.register_query(WhoAmI, lambda scope: WhoAmIHandler(scope.session))
    registry.register_query(CountOrders, lambda scope: CountOrdersHandler())
    return registry.build(FIXTURES)


async def test_send_routes_a_command_to_its_handler_and_returns_the_result() -> None:
    assert await wired().send(PlaceOrder(quantity=4), Scope(FakeSession())) == 8


async def test_send_of_a_no_result_command_returns_none() -> None:
    assert await wired().send(Ping(), Scope(FakeSession())) is None  # type: ignore[func-returns-value]


async def test_ask_routes_a_query_to_its_handler() -> None:
    assert await wired().ask(CountOrders(), Scope(FakeSession())) == 3


async def test_dispatch_is_keyed_by_message_type_not_by_registration_order() -> None:
    dispatcher = wired()
    scope = Scope(FakeSession())
    assert await dispatcher.send(PlaceOrder(quantity=1), scope) == 2
    assert await dispatcher.ask(CountOrders(), scope) == 3


async def test_an_unregistered_message_type_raises_handler_not_found() -> None:
    registry: HandlerRegistry[Scope] = HandlerRegistry()
    dispatcher = registry.build()  # no module scanned: nothing to validate against
    with pytest.raises(HandlerNotFoundError, match="PlaceOrder"):
        await dispatcher.send(PlaceOrder(quantity=1), Scope(FakeSession()))
    with pytest.raises(HandlerNotFoundError, match="CountOrders"):
        await dispatcher.ask(CountOrders(), Scope(FakeSession()))


def _session_reporting_calls(seen: list[UUID]) -> dict[str, Callable[[Scope], Awaitable[object]]]:
    """One dispatcher's three paths as callables; each handler reports its scope's session id.

    The message classes are local, so `build(FIXTURES)` elsewhere never demands handlers for them.
    """

    class ReportCommand(Command[None]):
        pass

    class ReportQuery(Query[None]):
        pass

    class ReportEvent:
        pass

    class Reporter:
        def __init__(self, session: FakeSession) -> None:
            self._session = session

        async def handle(self, message: ReportCommand | ReportQuery | ReportEvent, /) -> None:
            seen.append(self._session.id)

    registry: HandlerRegistry[Scope] = HandlerRegistry()
    registry.register_command(ReportCommand, lambda scope: Reporter(scope.session))
    registry.register_query(ReportQuery, lambda scope: Reporter(scope.session))
    registry.register_event(ReportEvent, lambda scope: Reporter(scope.session))
    dispatcher = registry.build()
    return {
        "send": lambda scope: dispatcher.send(ReportCommand(), scope),
        "ask": lambda scope: dispatcher.ask(ReportQuery(), scope),
        "publish": lambda scope: dispatcher.publish(ReportEvent(), scope),
    }


PATHS = ["send", "ask", "publish"]


@pytest.mark.parametrize("path", PATHS)
async def test_two_scopes_yield_two_distinct_scoped_dependencies(path: str) -> None:
    """#8 D1 on EVERY dispatch path: ONE dispatcher, two scopes; a capture returns one id twice."""
    seen: list[UUID] = []
    calls = _session_reporting_calls(seen)
    first_scope, second_scope = Scope(FakeSession()), Scope(FakeSession())
    await calls[path](first_scope)
    await calls[path](second_scope)
    assert seen == [first_scope.session.id, second_scope.session.id]
    assert first_scope.session.id != second_scope.session.id


@pytest.mark.parametrize("path", PATHS)
async def test_a_scope_is_not_retained_by_the_dispatcher_between_calls(path: str) -> None:
    seen: list[UUID] = []
    calls = _session_reporting_calls(seen)
    scope = Scope(FakeSession())
    await calls[path](scope)
    probe = weakref.ref(scope)
    del scope
    gc.collect()
    assert probe() is None, f"the dispatcher is holding on to a caller's scope ({path})"


async def test_a_handler_exception_propagates_unchanged() -> None:
    boom = ValueError("boom")

    class Failing:
        async def handle(self, command: PlaceOrder, /) -> int:
            raise boom

    registry: HandlerRegistry[Scope] = HandlerRegistry()
    registry.register_command(PlaceOrder, lambda scope: Failing())
    dispatcher = registry.build()
    with pytest.raises(ValueError, match="boom") as caught:
        await dispatcher.send(PlaceOrder(quantity=1), Scope(FakeSession()))
    assert caught.value is boom


async def test_cancellation_of_the_caller_is_not_swallowed() -> None:
    started = asyncio.Event()

    class Slow:
        async def handle(self, command: PlaceOrder, /) -> int:
            started.set()
            await asyncio.sleep(60)
            return 0

    registry: HandlerRegistry[Scope] = HandlerRegistry()
    registry.register_command(PlaceOrder, lambda scope: Slow())
    dispatcher = registry.build()
    task = asyncio.create_task(dispatcher.send(PlaceOrder(quantity=1), Scope(FakeSession())))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


async def test_a_handler_raising_cancelled_error_propagates_it() -> None:
    class Cancelling:
        async def handle(self, command: PlaceOrder, /) -> int:
            raise asyncio.CancelledError

    registry: HandlerRegistry[Scope] = HandlerRegistry()
    registry.register_command(PlaceOrder, lambda scope: Cancelling())
    with pytest.raises(asyncio.CancelledError):
        await registry.build().send(PlaceOrder(quantity=1), Scope(FakeSession()))


async def test_dispatch_creates_no_task_of_its_own() -> None:
    seen: list[int] = []

    class Counting:
        async def handle(self, command: PlaceOrder, /) -> int:
            seen.append(len(asyncio.all_tasks()))
            return 0

    registry: HandlerRegistry[Scope] = HandlerRegistry()
    registry.register_command(PlaceOrder, lambda scope: Counting())
    registry.register_event(OrderPlaced, lambda scope: _EventRecorder(seen_tasks=seen))
    dispatcher = registry.build()
    scope = Scope(FakeSession())
    await dispatcher.send(PlaceOrder(quantity=1), scope)
    await dispatcher.publish(OrderPlaced(quantity=1), scope)
    assert seen == [1, 1], "only the test's own task may exist while a handler runs"


class _EventRecorder:
    def __init__(
        self, log: list[object] | None = None, seen_tasks: list[int] | None = None
    ) -> None:
        self._log = log
        self._seen_tasks = seen_tasks

    async def handle(self, event: OrderPlaced, /) -> None:
        if self._log is not None:
            self._log.append(event)
        if self._seen_tasks is not None:
            self._seen_tasks.append(len(asyncio.all_tasks()))


async def test_publish_with_zero_handlers_is_a_no_op() -> None:
    await HandlerRegistry[Scope]().build().publish(OrderPlaced(quantity=1), Scope(FakeSession()))


async def test_publish_runs_every_handler_in_registration_order() -> None:
    order: list[str] = []

    def make(name: str) -> type:
        class Named:
            async def handle(self, event: OrderPlaced, /) -> None:
                order.append(name)

        return Named

    registry: HandlerRegistry[Scope] = HandlerRegistry()
    registry.register_event(OrderPlaced, lambda scope: make("first")())
    registry.register_event(OrderPlaced, lambda scope: make("second")())
    await registry.build().publish(OrderPlaced(quantity=1), Scope(FakeSession()))
    assert order == ["first", "second"]


async def test_publish_resolves_by_runtime_type_not_the_declared_type() -> None:
    log: list[object] = []
    registry: HandlerRegistry[Scope] = HandlerRegistry()
    registry.register_event(OrderFact, lambda scope: _FactRecorder(log))
    registry.register_event(OrderPlaced, lambda scope: _EventRecorder(log))
    dispatcher = registry.build()
    event: OrderPlaced = OrderFact(quantity=7)  # static type is the base, runtime type the subtype
    await dispatcher.publish(event, Scope(FakeSession()))
    assert log == ["fact", event], (
        "the derived handler and the base handler must both run, derived first"
    )
    log.clear()
    await dispatcher.publish(OrderPlaced(quantity=1), Scope(FakeSession()))
    assert log == [OrderPlaced(quantity=1)], "a plain base event must not reach the derived handler"


class _FactRecorder:
    def __init__(self, log: list[object]) -> None:
        self._log = log

    async def handle(self, event: OrderFact, /) -> None:
        self._log.append("fact")


async def test_publish_first_handler_exception_propagates_and_stops_the_rest() -> None:
    log: list[object] = []

    class Failing:
        async def handle(self, event: OrderPlaced, /) -> None:
            raise RuntimeError("first failed")

    registry: HandlerRegistry[Scope] = HandlerRegistry()
    registry.register_event(OrderPlaced, lambda scope: Failing())
    registry.register_event(OrderPlaced, lambda scope: _EventRecorder(log))
    with pytest.raises(RuntimeError, match="first failed"):
        await registry.build().publish(OrderPlaced(quantity=1), Scope(FakeSession()))
    assert log == []


def complete() -> HandlerRegistry[Scope]:
    registry: HandlerRegistry[Scope] = HandlerRegistry()
    registry.register_command(PlaceOrder, lambda scope: PlaceOrderHandler())
    registry.register_command(Ping, lambda scope: PingHandler())
    registry.register_query(WhoAmI, lambda scope: WhoAmIHandler(scope.session))
    registry.register_query(CountOrders, lambda scope: CountOrdersHandler())
    return registry


def test_a_complete_registration_validates() -> None:
    complete().build(FIXTURES)


def test_a_command_with_zero_handlers_fails_startup_naming_the_command() -> None:
    registry: HandlerRegistry[Scope] = HandlerRegistry()
    registry.register_command(PlaceOrder, lambda scope: PlaceOrderHandler())
    registry.register_query(WhoAmI, lambda scope: WhoAmIHandler(scope.session))
    registry.register_query(CountOrders, lambda scope: CountOrdersHandler())
    with pytest.raises(DispatcherValidationError) as caught:
        registry.build(FIXTURES)
    assert caught.value.problems == (
        "No command handler is registered for Ping. Exactly one is required.",
    )


def test_a_command_with_two_handlers_fails_startup_naming_both() -> None:
    registry = complete()
    registry.register_command(Ping, lambda scope: SecondPingHandler())
    with pytest.raises(DispatcherValidationError) as caught:
        registry.build(FIXTURES)
    (problem,) = caught.value.problems
    assert problem.startswith("2 command handlers are registered for Ping: ")
    assert "<lambda>" in problem


def test_a_query_with_zero_handlers_fails_startup() -> None:
    registry: HandlerRegistry[Scope] = HandlerRegistry()
    registry.register_command(PlaceOrder, lambda scope: PlaceOrderHandler())
    registry.register_command(Ping, lambda scope: PingHandler())
    registry.register_query(CountOrders, lambda scope: CountOrdersHandler())
    with pytest.raises(DispatcherValidationError) as caught:
        registry.build(FIXTURES)
    assert caught.value.problems == (
        "No query handler is registered for WhoAmI. Exactly one is required.",
    )


def test_a_query_with_two_handlers_fails_startup() -> None:
    registry = complete()
    registry.register_query(CountOrders, lambda scope: CountOrdersHandler())
    with pytest.raises(DispatcherValidationError) as caught:
        registry.build(FIXTURES)
    (problem,) = caught.value.problems
    assert problem.startswith("2 query handlers are registered for CountOrders: ")


def test_every_defect_is_reported_at_once() -> None:
    registry: HandlerRegistry[Scope] = HandlerRegistry()
    registry.register_command(Ping, lambda scope: PingHandler())
    registry.register_command(Ping, lambda scope: PingHandler())
    with pytest.raises(DispatcherValidationError) as caught:
        registry.build(FIXTURES)
    assert (
        len(caught.value.problems) == 4
    )  # PlaceOrder, Ping x2, WhoAmI, CountOrders -> 3 missing + 1 duplicate
    assert str(caught.value) == "\n".join(caught.value.problems)


def test_an_event_with_zero_handlers_is_not_a_startup_error() -> None:
    complete().build(FIXTURES)  # OrderPlaced is published nowhere handled; still fine


def test_an_event_with_several_handlers_is_not_a_startup_error() -> None:
    registry = complete()
    registry.register_event(OrderPlaced, lambda scope: _Noop())
    registry.register_event(OrderPlaced, lambda scope: _Noop())
    registry.build(FIXTURES)


class _Noop:
    async def handle(self, event: OrderPlaced, /) -> None:
        return None


def _module_of(name: str, **members: object) -> types.ModuleType:
    """A synthetic module holding `members`, so a test controls exactly what a scan can see."""
    module = types.ModuleType(name)
    for member_name, member in members.items():
        setattr(module, member_name, member)
    return module


def test_a_message_imported_from_an_unscanned_module_is_still_demanded_a_handler() -> None:
    """Escape route: `from elsewhere import Msg as Alias` in a scanned module (#8 D10 shape)."""

    class Elsewhere(Command[str]):  # defined in THIS module, so no `__module__` match is possible
        pass

    scanned = _module_of("scanned_messages", Aliased=Elsewhere)
    with pytest.raises(DispatcherValidationError) as caught:
        HandlerRegistry[Scope]().build(scanned)
    (problem,) = caught.value.problems
    assert problem.endswith("Elsewhere. Exactly one is required.")


def test_a_message_visible_under_two_names_is_reported_once() -> None:
    class Twice(Command[str]):
        pass

    scanned = _module_of("scanned_twice", First=Twice, Second=Twice)
    other = _module_of("scanned_twice_other", Third=Twice)
    with pytest.raises(DispatcherValidationError) as caught:
        HandlerRegistry[Scope]().build(scanned, other)
    assert len(caught.value.problems) == 1


def test_a_nested_message_class_is_found() -> None:
    """Escape route: `class Outer: class Nested(Command[int])` (#8's GetTypes covers nested)."""

    class Outer:
        class Nested(Command[int]):
            pass

        class Deeper:
            class Deepest(Query[int]):
                pass

    scanned = _module_of("scanned_nested", Outer=Outer)
    with pytest.raises(DispatcherValidationError) as caught:
        HandlerRegistry[Scope]().build(scanned)
    problems = caught.value.problems
    assert len(problems) == 2
    assert any(
        "No command handler" in p and p.endswith("Nested. Exactly one is required.")
        for p in problems
    )
    assert any(
        "No query handler" in p and p.endswith("Deepest. Exactly one is required.")
        for p in problems
    )


def test_a_new_submodule_of_a_scanned_package_is_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Escape route: a message module added later, never passed by hand (#8 D10 shape)."""
    package = tmp_path / "zz_cqrs_probe_pkg"
    (package / "inner").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "inner" / "__init__.py").write_text("")
    (package / "inner" / "deep_commands.py").write_text(
        "from otc_cqrs import Command\n\n\nclass DeepCommand(Command[int]):\n    pass\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        root = importlib.import_module("zz_cqrs_probe_pkg")
        with pytest.raises(DispatcherValidationError) as caught:
            HandlerRegistry[Scope]().build(root)
        (problem,) = caught.value.problems
        assert problem.endswith("DeepCommand. Exactly one is required.")
    finally:
        for name in [n for n in sys.modules if n.startswith("zz_cqrs_probe_pkg")]:
            del sys.modules[name]


def test_an_abstract_generic_base_is_not_a_message_but_its_concrete_subclass_is() -> None:
    """Escape route: `class Base[T](Command[T])` has unbound type parameters (review Q3)."""

    class GenericBase[T](Command[T]):
        pass

    class Concrete(GenericBase[int]):
        pass

    scanned = _module_of("scanned_generic", GenericBase=GenericBase, Concrete=Concrete)
    with pytest.raises(DispatcherValidationError) as caught:
        HandlerRegistry[Scope]().build(scanned)
    (problem,) = caught.value.problems
    assert problem.endswith("Concrete. Exactly one is required.")


def test_a_message_that_is_both_command_and_query_is_a_malformed_declaration() -> None:
    module = types.ModuleType("synthetic_messages")

    class Both(Command[int], Query[int]):
        pass

    Both.__module__ = module.__name__
    module.Both = Both  # type: ignore[attr-defined]
    with pytest.raises(DispatcherValidationError) as caught:
        HandlerRegistry[Scope]().build(module)
    (problem,) = caught.value.problems
    assert problem.endswith("Both is both a Command and a Query; a message is exactly one.")


def test_importing_a_module_with_handlers_registers_nothing() -> None:
    """The registry is empty until a composition root registers: importing is not registering."""
    registry: HandlerRegistry[Scope] = HandlerRegistry()
    with pytest.raises(DispatcherValidationError) as caught:
        registry.build(FIXTURES)
    assert len(caught.value.problems) == 4
    assert all(p.startswith("No ") for p in caught.value.problems)


def test_registered_factories_lists_every_kind_of_registered_handler() -> None:
    registry: HandlerRegistry[Scope] = HandlerRegistry()

    def command_factory(scope: Scope) -> PingHandler:
        return PingHandler()

    def query_factory(scope: Scope) -> WhoAmIHandler:
        return WhoAmIHandler(scope.session)

    def event_factory(scope: Scope) -> _EventRecorder:
        return _EventRecorder(log=[])

    registry.register_command(Ping, command_factory)
    registry.register_query(WhoAmI, query_factory)
    registry.register_event(OrderPlaced, event_factory)

    listed = registry.registered_factories()

    assert len(listed) == 3
    assert {command_factory, query_factory, event_factory} == set(listed)
