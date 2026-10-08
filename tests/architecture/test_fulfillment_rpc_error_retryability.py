"""FS21 / L8: a transient Fulfillment failure maps to a code Orders' saga adapter RETRIES.

The two services are imported side by side (tests are outside import-linter's `root_packages`
contracts, which keep services from importing each other). The terminal set is read from Orders'
own module, `TERMINAL_RPC_ERROR_CODES`, never a retyped list (#8 id 51).

#7 answered a concurrency error with `CONFLICT`, which was safe there because its orchestrator
retried every code; Orders' set is #8's nine, and `CONFLICT` is terminal in it, so a `CONFLICT`
from Fulfillment would end a `stock.reserve` row `rejected` for a failure that was transient.
"""

import uuid
from datetime import UTC, datetime

from otc_contracts.generated.asyncapi import Code
from otc_fulfillment.application.despatch_creation import NoReservedStockForDespatchError
from otc_fulfillment.application.ports.stock_store import (
    ConcurrentDespatchChangeError,
    ConcurrentReservationChangeError,
    StoreUnavailableError,
)
from otc_fulfillment.application.stock_replenishment import UnknownStockItemError
from otc_fulfillment.application.stock_reservation import NoKnownStockItemError
from otc_fulfillment.domain.errors import (
    FactAggregateMismatchError,
    InsufficientStockError,
    InvalidStockItemSnapshotError,
    ReservationTerminalError,
    UnknownReservationStatusError,
)
from otc_fulfillment.infrastructure.persistence.stock_transactions import (
    CONNECTION_EXCEPTION_CLASS,
    TRANSIENT_SQLSTATES,
)
from otc_fulfillment.presentation.stock_headers import InvalidStockHeadersError
from otc_fulfillment.presentation.stock_rpc_errors import map_error
from otc_fulfillment.presentation.stock_wire import InvalidStockRequestError
from otc_orders.infrastructure.messaging.nats_saga_commands import TERMINAL_RPC_ERROR_CODES
from otc_shared_kernel import UniqueId

NOW = datetime(2026, 10, 8, 9, 0, 0, tzinfo=UTC)
CORRELATION = UniqueId(uuid.UUID(int=0xC0))

TRANSIENT_STATES = [*sorted(TRANSIENT_SQLSTATES), CONNECTION_EXCEPTION_CLASS + "006"]
TRANSIENT_STORE_FAILURES: list[Exception] = [
    *(StoreUnavailableError(state) for state in TRANSIENT_STATES),
    ConcurrentReservationChangeError("ORD-000042"),
    ConcurrentDespatchChangeError("ORD-000042"),  # feature 18: consumed, but no advice (F8)
    RuntimeError("an unclassified failure"),  # INTERNAL_ERROR: also retried
]
EVERY_INPUT: list[Exception] = [
    *TRANSIENT_STORE_FAILURES,
    InvalidStockRequestError("x"),
    InvalidStockHeadersError("x"),
    NoKnownStockItemError("ORD-000042"),
    NoReservedStockForDespatchError("ORD-000042"),  # feature 18: PRECONDITION_FAILED, terminal
    UnknownStockItemError("ACME-CO", "PRD-Z9"),
    ReservationTerminalError("consumed", "released"),
    InsufficientStockError("PRD-A1", 5, 1),
    InvalidStockItemSnapshotError("x"),
    FactAggregateMismatchError("a", "b"),
    UnknownReservationStatusError("x"),
]


def test_fs21_every_transient_store_failure_maps_to_a_code_the_saga_adapter_retries() -> None:
    assert len(TRANSIENT_STORE_FAILURES) >= 9, "the population is the literal set plus class 08"
    for failure in TRANSIENT_STORE_FAILURES:
        code = map_error(failure, NOW, CORRELATION).code
        assert code not in TERMINAL_RPC_ERROR_CODES, (
            f"{type(failure).__name__}({failure}) is answered {code.value}, which Orders' saga "
            "adapter treats as a terminal rejection"
        )
        assert code in {Code.unavailable, Code.internal_error, Code.timeout}


def test_fs21_no_input_produces_conflict() -> None:
    codes = {map_error(error, NOW, CORRELATION).code for error in EVERY_INPUT}

    assert Code.conflict not in codes
    assert Code.conflict in TERMINAL_RPC_ERROR_CODES, "the premise: CONFLICT is terminal in Orders"
    assert len(codes) >= 5, "the inputs exercise the mapping's rows, not one"
