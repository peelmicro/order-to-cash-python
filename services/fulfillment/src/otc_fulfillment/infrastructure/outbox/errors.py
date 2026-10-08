"""Fulfillment's COPY of Orders' `infrastructure/outbox/errors.py` (the canonical).

The canonical: `services/orders/src/otc_orders/infrastructure/outbox/errors.py`.
After this docstring the copy equals it, modulo the token map `otc_orders` ->
`otc_fulfillment` and `ORDERS_FACTS_TOPIC` -> `FULFILLMENT_FACTS_TOPIC`, and modulo the
formatter's line reflow of the longer names. Any other difference fails
`tests/architecture/test_outbox_copy_parity.py`. Change the canonical, never this copy.
"""


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
