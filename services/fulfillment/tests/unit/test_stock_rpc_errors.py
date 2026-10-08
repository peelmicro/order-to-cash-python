"""F4: one case per row of the error mapping (`design.md` 8.5): code AND details."""

import uuid
from datetime import UTC, datetime

import pytest

from otc_contracts.generated.asyncapi import Code, RpcError
from otc_fulfillment.application.ports.stock_store import (
    ConcurrentReservationChangeError,
    StoreUnavailableError,
)
from otc_fulfillment.application.stock_replenishment import UnknownStockItemError
from otc_fulfillment.application.stock_reservation import NoKnownStockItemError
from otc_fulfillment.domain.errors import InsufficientStockError, ReservationTerminalError
from otc_fulfillment.infrastructure.persistence.range_guards import QuantityOutOfRangeError
from otc_fulfillment.presentation.stock_headers import InvalidStockHeadersError
from otc_fulfillment.presentation.stock_rpc_errors import map_error
from otc_fulfillment.presentation.stock_wire import InvalidStockRequestError
from otc_shared_kernel import UniqueId

NOW = datetime(2026, 10, 8, 9, 0, 0, tzinfo=UTC)
CORRELATION = UniqueId(uuid.UUID(int=0xC0))


def mapped(error: Exception) -> RpcError:
    return map_error(error, NOW, CORRELATION)


ROWS: list[tuple[str, Exception, Code, dict[str, object] | None]] = [
    ("invalid request", InvalidStockRequestError("bad"), Code.validation_failed, None),
    ("invalid headers", InvalidStockHeadersError("bad"), Code.validation_failed, None),
    (
        "no carrier",
        NoKnownStockItemError("ORD-000042"),
        Code.not_found,
        {"orderReference": "ORD-000042"},
    ),
    (
        "replenish unknown product",
        UnknownStockItemError("ACME-CO", "PRD-Z9"),
        Code.not_found,
        {"companyCode": "ACME-CO", "productCode": "PRD-Z9"},
    ),
    (
        "consumed reservation",
        ReservationTerminalError("consumed", "released"),
        Code.precondition_failed,
        {"code": "reservation.terminal"},
    ),
    (
        "range guard",
        QuantityOutOfRangeError("stock.units", 2**31, -(2**31), 2**31 - 1),
        Code.domain_error,
        {"code": "quantity.out_of_range"},
    ),
    (
        "any other domain error",
        InsufficientStockError("PRD-A1", 5, 1),
        Code.domain_error,
        {"code": "stock.insufficient"},
    ),
    ("store unavailable", StoreUnavailableError("40P01"), Code.unavailable, None),
    (
        "concurrent reservation change",
        ConcurrentReservationChangeError("ORD-000042"),
        Code.unavailable,
        None,
    ),
    ("anything else", RuntimeError("select * from secrets"), Code.internal_error, None),
]


@pytest.mark.parametrize(("label", "error", "code", "details"), ROWS, ids=[r[0] for r in ROWS])
def test_each_row_of_the_mapping_answers_its_code_and_details(
    label: str, error: Exception, code: Code, details: dict[str, object] | None
) -> None:
    rpc = mapped(error)

    assert rpc.code is code, label
    assert rpc.details == details
    assert rpc.correlation_id == CORRELATION.value
    assert rpc.occurred_at == NOW
    assert rpc.message


def test_an_internal_error_never_carries_the_exceptions_text() -> None:
    rpc = mapped(RuntimeError("select * from secrets"))

    assert "secrets" not in rpc.message


def test_the_correlation_id_is_optional() -> None:
    assert map_error(InvalidStockRequestError("x"), NOW, None).correlation_id is None


def test_no_row_of_the_mapping_produces_a_code_that_is_never_produced() -> None:
    never = {
        Code.conflict,
        Code.timeout,
        Code.order_not_cancellable,
        Code.stock_unavailable,
        Code.invoice_not_payable,
        Code.payment_mismatch,
    }
    produced = {mapped(error).code for _, error, _, _ in ROWS}

    assert produced.isdisjoint(never)
