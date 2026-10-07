"""The ten fact commands, one per consumed fact (`design.md` 7.7).

Each holds the validated envelope (`Envelope[dict[str, Any]]`, the seven fields) and the topic it
came from. The four self-produced facts map to nothing: they are acknowledged before any command is
built (SO2). Ten classes with identical fields, not a base class: `HandlerRegistry.build` demands a
handler for every concrete `Command` it can see, and a shared concrete base would be demanded one.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from otc_contracts import Envelope
from otc_cqrs import Command
from otc_orders.application.saga.fact_handler import SagaFactResult


@dataclass(frozen=True, slots=True)
class HandleOrderPlacedFactCommand(Command[SagaFactResult]):
    envelope: Envelope[dict[str, Any]]
    topic: str


@dataclass(frozen=True, slots=True)
class HandleStockReservedFactCommand(Command[SagaFactResult]):
    envelope: Envelope[dict[str, Any]]
    topic: str


@dataclass(frozen=True, slots=True)
class HandleStockRejectedFactCommand(Command[SagaFactResult]):
    envelope: Envelope[dict[str, Any]]
    topic: str


@dataclass(frozen=True, slots=True)
class HandleStockReleasedFactCommand(Command[SagaFactResult]):
    envelope: Envelope[dict[str, Any]]
    topic: str


@dataclass(frozen=True, slots=True)
class HandleCreditApprovedFactCommand(Command[SagaFactResult]):
    envelope: Envelope[dict[str, Any]]
    topic: str


@dataclass(frozen=True, slots=True)
class HandleCreditRejectedFactCommand(Command[SagaFactResult]):
    envelope: Envelope[dict[str, Any]]
    topic: str


@dataclass(frozen=True, slots=True)
class HandleOrderDespatchedFactCommand(Command[SagaFactResult]):
    envelope: Envelope[dict[str, Any]]
    topic: str


@dataclass(frozen=True, slots=True)
class HandleInvoiceIssuedFactCommand(Command[SagaFactResult]):
    envelope: Envelope[dict[str, Any]]
    topic: str


@dataclass(frozen=True, slots=True)
class HandlePaymentReceivedFactCommand(Command[SagaFactResult]):
    envelope: Envelope[dict[str, Any]]
    topic: str


@dataclass(frozen=True, slots=True)
class HandleCreditReleasedFactCommand(Command[SagaFactResult]):
    envelope: Envelope[dict[str, Any]]
    topic: str


type FactCommand = (
    HandleOrderPlacedFactCommand
    | HandleStockReservedFactCommand
    | HandleStockRejectedFactCommand
    | HandleStockReleasedFactCommand
    | HandleCreditApprovedFactCommand
    | HandleCreditRejectedFactCommand
    | HandleOrderDespatchedFactCommand
    | HandleInvoiceIssuedFactCommand
    | HandlePaymentReceivedFactCommand
    | HandleCreditReleasedFactCommand
)

FACT_COMMANDS: Mapping[str, type[FactCommand]] = {
    "order.placed.v1": HandleOrderPlacedFactCommand,
    "stock.reserved.v1": HandleStockReservedFactCommand,
    "stock.rejected.v1": HandleStockRejectedFactCommand,
    "stock.released.v1": HandleStockReleasedFactCommand,
    "credit.approved.v1": HandleCreditApprovedFactCommand,
    "credit.rejected.v1": HandleCreditRejectedFactCommand,
    "order.despatched.v1": HandleOrderDespatchedFactCommand,
    "invoice.issued.v1": HandleInvoiceIssuedFactCommand,
    "payment.received.v1": HandlePaymentReceivedFactCommand,
    "credit.released.v1": HandleCreditReleasedFactCommand,
}
