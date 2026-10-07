"""Hand-rolled in-process dispatcher: registry keyed by message type, validated at startup.

Durability never depends on this: the outbox and `saga_commands` are the guarantee. This is the
in-process fast path from a presentation entry point down into the application layer.

Scope. `S` is the per-dispatch scope (in a service: an object owning one `AsyncSession`). The
registry stores handler *factories* `Callable[[S], Handler]`; the dispatcher stores no scope, no
session and no handler instance, and the caller passes its scope on every call, so a handler's
dependencies belong to one inbound message.

Registration is explicit: `HandlerRegistry.register_*` is called from a composition root. Nothing
here registers at import time (no decorator, no module-level state); see
tests/architecture/test_cqrs_registration_explicit.py.
"""

import importlib
import inspect
import pkgutil
from collections.abc import Callable, Iterator
from types import ModuleType
from typing import cast

from otc_cqrs.errors import DispatcherValidationError, HandlerNotFoundError
from otc_cqrs.handlers import CommandHandler, EventHandler, QueryHandler
from otc_cqrs.messages import Command, CommandType, Query, QueryType

type _Factory[S] = Callable[[S], object]


def _label(factory: Callable[..., object]) -> str:
    return getattr(factory, "__qualname__", None) or repr(factory)


def _modules_under(root: ModuleType) -> Iterator[ModuleType]:
    """`root` and, when it is a package, every submodule at any depth (imported)."""
    yield root
    for info in pkgutil.walk_packages(getattr(root, "__path__", ()), f"{root.__name__}."):
        yield importlib.import_module(info.name)


def _classes_in(owner: ModuleType | type, seen: set[type]) -> Iterator[type]:
    """Every class reachable as an attribute of `owner`, nested classes included."""
    for member in vars(owner).values():
        if inspect.isclass(member) and member not in seen:
            seen.add(member)
            yield member
            yield from _classes_in(member, seen)


def _messages_under(roots: tuple[ModuleType, ...]) -> set[type]:
    """Concrete commands and queries visible anywhere under `roots`.

    A message is counted wherever it is visible, defined there or imported (aliased or not), so a
    message imported from a module nobody scanned is still demanded a handler. Identity dedupes a
    class reachable under several names. A class with unbound type parameters is an abstract
    generic base (`class Base[T](Command[T])`), not a message.
    """
    seen: set[type] = set()
    found: set[type] = set()
    for root in roots:
        for module in _modules_under(root):
            for cls in _classes_in(module, seen):
                is_message = issubclass(cls, Command | Query) and cls not in (Command, Query)
                if is_message and not getattr(cls, "__parameters__", ()):
                    found.add(cls)
    return found


class HandlerRegistry[S]:
    """Mutable while a composition root wires it; `build` validates and returns a `Dispatcher`."""

    def __init__(self) -> None:
        self._commands: dict[type, list[_Factory[S]]] = {}
        self._queries: dict[type, list[_Factory[S]]] = {}
        self._events: dict[type, list[_Factory[S]]] = {}

    def register_command[C, R](
        self, command_type: CommandType[C, R], factory: Callable[[S], CommandHandler[C, R]]
    ) -> None:
        # The key is the class itself: `CommandType` is satisfied only by a class.
        self._commands.setdefault(cast("type", command_type), []).append(factory)

    def register_query[Q, R](
        self, query_type: QueryType[Q, R], factory: Callable[[S], QueryHandler[Q, R]]
    ) -> None:
        self._queries.setdefault(cast("type", query_type), []).append(factory)

    def register_event[E](
        self, event_type: type[E], factory: Callable[[S], EventHandler[E]]
    ) -> None:
        self._events.setdefault(event_type, []).append(factory)

    def registered_factories(self) -> list[Callable[[S], object]]:
        """Every factory registered so far, of all three kinds (read-only: a composition root
        builds each once at boot to prove its bindings)."""
        return [
            factory
            for table in (self._commands, self._queries, self._events)
            for factories in table.values()
            for factory in factories
        ]

    def build(self, *message_roots: ModuleType) -> Dispatcher[S]:
        """Validate against every command and query under `message_roots`, then freeze.

        Each root is a module or a package; a package is walked to every submodule, and nested
        classes are found, so adding a message module or nesting a class cannot escape the check.
        Raises `DispatcherValidationError` listing every defect. A command or query needs exactly
        one handler. An event with zero handlers is not an error (a fact may have no listener
        yet), so events are not scanned.
        """
        problems: list[str] = []
        commands: set[type] = set()
        queries: set[type] = set()
        for message in _messages_under(message_roots):
            is_command = issubclass(message, Command)
            if is_command and issubclass(message, Query):
                problems.append(
                    f"{message.__qualname__} is both a Command and a Query; "
                    "a message is exactly one."
                )
            elif is_command:
                commands.add(message)
            else:
                queries.add(message)
        # Registrations count too, so a handler registered for a type outside the scanned roots is
        # still checked for duplicates (never reported as "missing": absence needs the universe).
        for kind, universe, registered in (
            ("command", commands, self._commands),
            ("query", queries, self._queries),
        ):
            for message_type in sorted(universe | registered.keys(), key=lambda t: t.__qualname__):
                factories = registered.get(message_type, [])
                if not factories and message_type in universe:
                    problems.append(
                        f"No {kind} handler is registered for {message_type.__qualname__}. "
                        "Exactly one is required."
                    )
                elif len(factories) > 1:
                    names = ", ".join(_label(f) for f in factories)
                    problems.append(
                        f"{len(factories)} {kind} handlers are registered for "
                        f"{message_type.__qualname__}: {names}. Exactly one is required."
                    )
        if problems:
            raise DispatcherValidationError(problems)
        return Dispatcher(
            {k: v[0] for k, v in self._commands.items()},
            {k: v[0] for k, v in self._queries.items()},
            {k: tuple(v) for k, v in self._events.items()},
        )


class Dispatcher[S]:
    """Stateless: every call receives the caller's scope and builds its handler from it."""

    __slots__ = ("_commands", "_events", "_queries")

    def __init__(
        self,
        commands: dict[type, _Factory[S]],
        queries: dict[type, _Factory[S]],
        events: dict[type, tuple[_Factory[S], ...]],
    ) -> None:
        self._commands = commands
        self._queries = queries
        self._events = events

    async def send[R](self, command: Command[R], scope: S) -> R:
        factory = self._commands.get(type(command))
        if factory is None:
            raise HandlerNotFoundError(
                f"No command handler registered for {type(command).__qualname__}"
            )
        # Sound: `register_command` accepted `factory` only as `Callable[[S], CommandHandler[C, R]]`
        # for the class `C` this key came from, whose result type is the `R` of `Command[R]`.
        handler = cast("CommandHandler[Command[R], R]", factory(scope))
        return await handler.handle(command)

    async def ask[R](self, query: Query[R], scope: S) -> R:
        factory = self._queries.get(type(query))
        if factory is None:
            raise HandlerNotFoundError(
                f"No query handler registered for {type(query).__qualname__}"
            )
        # Sound for the same reason as `send`, through `register_query`.
        handler = cast("QueryHandler[Query[R], R]", factory(scope))
        return await handler.handle(query)

    async def publish(self, event: object, scope: S) -> None:
        """Run every handler registered for the event's RUNTIME type or a base of it, in turn.

        Zero handlers is a no-op. The first exception propagates unchanged and stops the
        remaining handlers. The cast is sound: a handler was registered under a class the event
        is an instance of.
        """
        for event_type in type(event).__mro__[:-1]:
            for factory in self._events.get(event_type, ()):
                await cast("EventHandler[object]", factory(scope)).handle(event)
