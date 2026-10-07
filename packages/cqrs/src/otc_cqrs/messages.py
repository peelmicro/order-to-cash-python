"""Message markers: the closed universe startup validation checks registrations against.

Zero handlers is only decidable against a known set of command and query types, because a handler
that was never written leaves no artifact to scan. A command is therefore declared by subclassing
`Command[R]` and a query by subclassing `Query[R]`. Events carry no marker: a fact may
legitimately have zero listeners.

`R` is the result type. It survives `Dispatcher.send` / `ask` under `mypy --strict`, and it is
also tied to the handler: each marker carries a phantom classmethod, `_result_witness`, whose
signature mentions `R` on both sides. `HandlerRegistry.register_command` / `register_query` take
the message CLASS as a protocol requiring that method, so the checker infers `R` from the message
class and demands a handler returning exactly that `R` (the guarantee #8 had from
`ICommandHandler<in TCommand, TResult> where TCommand : ICommand<TResult>`). The method is never
called; it exists only for the type checker.
"""

from typing import Protocol, Self


class Command[R]:
    """Marker for a command whose handler returns `R` (use `None` for no result)."""

    __slots__ = ()

    @classmethod
    def _result_witness(cls, instance: Self, result: R, /) -> R:
        raise NotImplementedError  # pragma: no cover - type-level witness, never called


class Query[R]:
    """Marker for a query whose handler returns `R`."""

    __slots__ = ()

    @classmethod
    def _result_witness(cls, instance: Self, result: R, /) -> R:
        raise NotImplementedError  # pragma: no cover - type-level witness, never called


class CommandType[C, R](Protocol):
    """A command class `C` whose result type is `R` (what `register_command` accepts)."""

    def _result_witness(self, instance: C, result: R, /) -> R: ...


class QueryType[Q, R](Protocol):
    """A query class `Q` whose result type is `R` (what `register_query` accepts)."""

    def _result_witness(self, instance: Q, result: R, /) -> R: ...
