"""Refusals of the outbox writer. Infrastructure errors, not domain ones: the domain does not
know the outbox exists."""


class UnmappedDomainEventError(Exception):
    """A domain event of a class the payload mapper has no case for (names the class)."""

    def __init__(self, event_class: str) -> None:
        super().__init__(f"no outbox payload mapping exists for domain event class {event_class!r}")
        self.event_class = event_class


class UndeclaredFactError(Exception):
    """An event whose `EVENT_TYPE` is not in the fact catalogue, or whose payload is not the
    catalogue's payload model for that type (OI1: refuse the write, never store it)."""

    def __init__(self, event_type: str, reason: str) -> None:
        super().__init__(f"fact {event_type!r} is not in the fact catalogue: {reason}")
        self.event_type = event_type
