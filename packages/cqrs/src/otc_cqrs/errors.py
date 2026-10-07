"""Dispatcher errors. Plain exceptions: this package has no dependencies at all."""


class DispatcherValidationError(Exception):
    """Startup validation failed: a command/query has no handler or several, or is malformed.

    All problems are collected into one message so a composition root reports every defect at once.
    """

    def __init__(self, problems: list[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("\n".join(problems))


class HandlerNotFoundError(Exception):
    """A message was dispatched whose type was never registered (outside the validated universe)."""
