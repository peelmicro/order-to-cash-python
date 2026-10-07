"""The `R11` guard: a domain event's envelope is complete before anything is stored or published.

Pure: six scalar values in, `None` out or one `IncompleteDomainEventEnvelopeError` naming the field
that failed. The kernel imports nothing from `otc_contracts` (the envelope MODEL lives there); the
outbox writer calls this guard first and re-validates through the generic `Envelope[P]` second.

`EVENT_TYPE_PATTERN` is `specs/shared/asyncapi.yaml`'s `Envelope.eventType` pattern WITHOUT its
anchors, and the guard uses `re.fullmatch`: Python's `$` also matches before a trailing newline
(`re.match(r"^...$", "order.placed.v1\\n")` matches), so an anchored `re.match` would admit
`"order.placed.v1\\n"`. A test reads the spec and asserts `"^" + EVENT_TYPE_PATTERN + "$"` equals
it.
"""

import re
from datetime import datetime, timedelta

from otc_shared_kernel.errors import DomainError
from otc_shared_kernel.unique_id import UniqueId

EVENT_TYPE_PATTERN = r"[a-z]+\.[a-z_]+\.v[0-9]+"


class IncompleteDomainEventEnvelopeError(DomainError):
    CODE = "domain_event_envelope.incomplete"

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(self.CODE, f"domain event envelope field {field!r} {reason}")
        self.field = field


def _require_id(field: str, value: object) -> None:
    # `type(...) is` (not isinstance): a frozen dataclass does not stop None or a plain UUID at run
    # time, and `dataclasses.replace` / `object.__setattr__` bypass UniqueId's own non-nil check.
    if type(value) is not UniqueId:
        raise IncompleteDomainEventEnvelopeError(field, "is absent or not a UniqueId")
    if value.value.int == 0:
        raise IncompleteDomainEventEnvelopeError(field, "is the nil UUID")


def validate_domain_event_envelope(
    *,
    event_id: UniqueId,
    event_type: str,
    aggregate_id: UniqueId,
    correlation_id: UniqueId,
    causation_id: UniqueId,
    occurred_at: datetime,
) -> None:
    """Raise `IncompleteDomainEventEnvelopeError` unless the six values form a complete envelope."""
    _require_id("event_id", event_id)
    _require_id("aggregate_id", aggregate_id)
    _require_id("correlation_id", correlation_id)
    _require_id("causation_id", causation_id)
    if type(event_type) is not str or not event_type:
        raise IncompleteDomainEventEnvelopeError("event_type", "is absent or empty")
    if re.fullmatch(EVENT_TYPE_PATTERN, event_type) is None:
        raise IncompleteDomainEventEnvelopeError(
            "event_type", f"{event_type!r} does not match <aggregate>.<fact>.v<n>"
        )
    if not isinstance(occurred_at, datetime):
        raise IncompleteDomainEventEnvelopeError("occurred_at", "is absent")
    if occurred_at.utcoffset() != timedelta(0):
        raise IncompleteDomainEventEnvelopeError("occurred_at", "is naive or not UTC")
