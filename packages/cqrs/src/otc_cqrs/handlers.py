"""Handler protocols. Structural: a handler is any object with the right `handle` coroutine."""

from typing import Protocol


class CommandHandler[C, R](Protocol):
    async def handle(self, command: C, /) -> R: ...


class QueryHandler[Q, R](Protocol):
    async def handle(self, query: Q, /) -> R: ...


class EventHandler[E](Protocol):
    async def handle(self, event: E, /) -> None: ...
