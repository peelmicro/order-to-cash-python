"""`BillingScope`: the per-message scope of the dispatcher (`S` in `otc_cqrs.Dispatcher[S]`).

The composition root builds one for every inbound message and hands it to `Dispatcher.send` /
`ask`; the dispatcher stores none. A binding the root forgot is refused HERE, at construction, which
the root also does once at boot: never as an `AttributeError` on the first message.
"""

from dataclasses import dataclass, fields

from otc_billing.application.ports.clock import Clock
from otc_billing.application.ports.credit_decision import CreditDecisionPort
from otc_billing.application.ports.credit_store import CreditReads, CreditTransactions
from otc_billing.application.ports.ids import IdSource
from otc_billing.application.ports.invoice_store import InvoiceReads


class MissingBindingError(Exception):
    """A port of the scope was given no implementation."""

    def __init__(self, binding: str) -> None:
        super().__init__(f"the composition root bound nothing to the {binding!r} port")
        self.binding = binding


@dataclass(frozen=True, slots=True, kw_only=True)
class BillingScope:
    transactions: CreditTransactions
    reads: CreditReads
    invoice_reads: InvoiceReads
    clock: Clock
    ids: IdSource
    credit_decision: CreditDecisionPort

    def __post_init__(self) -> None:
        for field in fields(self):
            if getattr(self, field.name) is None:
                raise MissingBindingError(field.name)
