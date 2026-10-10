"""`InvoiceState`: the closed pair `Issued | Paid(paid_at)` (`design.md` 5.2; BI10, BI23, BI27).

`status` and `paid_at` are ONE value, not two fields. Python has no sealed classes and no zero
value, so the closure is built from three parts:

* `type InvoiceState = Issued | Paid` over two FINAL, frozen, slotted dataclasses, and every
  `match` over it ends in `assert_never` (here and in the mapper): a third member is a
  `mypy --strict` error at each site. Finality is a runtime refusal (`__init_subclass__` raises),
  not the `typing.final` decorator: a new decorator under `services/*/src` fails the census guard
  (`tests/architecture/test_cqrs_registration_explicit.py`, which this feature may not edit);
* `Paid.__post_init__` refuses anything but an aware `datetime`: a `None` that slipped past the type
  checker (an `Any` from a driver row) is a raise, not a state;
* a structural test that the alias's members are exactly the two classes.

`parse_invoice_state` is the only function that combines the store's two columns. It is loud: an
unknown token is `UnknownInvoiceStatusError`, a disagreeing pair is `InvalidInvoiceSnapshotError`.
`state_token` writes only the lower-case contract tokens (BI27).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, assert_never

from otc_billing.domain.invoice_errors import (
    InvalidInvoiceSnapshotError,
    InvalidInvoiceStateError,
    UnknownInvoiceStatusError,
)


class InvoiceStatus(Enum):
    ISSUED = "issued"
    PAID = "paid"


@dataclass(frozen=True, slots=True)
class Issued:
    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("Issued is final: InvoiceState is a closed pair")


@dataclass(frozen=True, slots=True)
class Paid:
    paid_at: datetime

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("Paid is final: InvoiceState is a closed pair")

    def __post_init__(self) -> None:
        if type(self.paid_at) is not datetime or self.paid_at.utcoffset() is None:
            raise InvalidInvoiceStateError(self.paid_at)


type InvoiceState = Issued | Paid

_BY_TOKEN: dict[str, InvoiceStatus] = {
    "issued": InvoiceStatus.ISSUED,
    "paid": InvoiceStatus.PAID,
}


def state_token(state: InvoiceState) -> InvoiceStatus:
    match state:
        case Issued():
            return InvoiceStatus.ISSUED
        case Paid():
            return InvoiceStatus.PAID
        case _:
            assert_never(state)


def paid_at_of(state: InvoiceState) -> datetime | None:
    match state:
        case Issued():
            return None
        case Paid():
            return state.paid_at
        case _:
            assert_never(state)


def parse_invoice_state(
    token: object, paid_at: object, *, invoice_reference: str | None = None
) -> InvoiceState:
    """The store's two columns -> one value. `invoice_reference` only names the invoice in a
    refusal (BI10: "a domain error naming the invoice")."""
    if type(token) is not str or token not in _BY_TOKEN:
        raise UnknownInvoiceStatusError(token)
    named = "the stored invoice" if invoice_reference is None else f"invoice {invoice_reference}"
    status = _BY_TOKEN[token]
    match status:
        case InvoiceStatus.ISSUED:
            if paid_at is not None:
                raise InvalidInvoiceSnapshotError(f"{named} is issued but carries paid_at")
            return Issued()
        case InvoiceStatus.PAID:
            if type(paid_at) is not datetime or paid_at.utcoffset() is None:
                raise InvalidInvoiceSnapshotError(
                    f"{named} is paid but its paid_at is {paid_at!r}, not an aware instant"
                )
            return Paid(paid_at)
        case _:
            assert_never(status)
