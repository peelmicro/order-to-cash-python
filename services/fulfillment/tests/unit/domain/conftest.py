"""Builders for the stock aggregate's pure unit tests (`specs/fulfillment_stock/design.md` 13.1).

Pytest fixtures, not helper modules: the repository runs `--import-mode=importlib`, so a test module
cannot import a sibling module. Builders, not mocks. Every id is built from a distinct number, so
the order id, the carrier id, the correlation id and the causation id are pairwise different, and
the product codes are chosen so that none contains another (`PRD-A1`, `PRD-B2`, `PRD-C3`).

Loop scope: nothing here is async.
"""

import uuid
from collections.abc import Callable, Sequence

import pytest

from otc_fulfillment.domain.reservation import ReservationStatus
from otc_fulfillment.domain.snapshot import ReservationSnapshot, StockItemSnapshot
from otc_fulfillment.domain.stock_item import StockItem
from otc_shared_kernel import UniqueId

COMPANY = "ACME-CO"
RETAILER = "RET-9"


def _uid(number: int) -> UniqueId:
    return UniqueId(uuid.UUID(f"00000000-0000-4000-8000-{number:012x}"))


@pytest.fixture
def uid() -> Callable[[int], UniqueId]:
    """`uid(0xa1)`: a distinct, valid identifier per number."""
    return _uid


@pytest.fixture
def build_item() -> Callable[..., StockItem]:
    """`build_item("PRD-A1", units=10, item_number=0x1a1)`; `reservations` are
    `(number, order_reference, units, status)` rows of this item."""

    def build(
        product_code: str,
        *,
        units: int,
        reserved: int = 0,
        item_number: int = 0x100,
        reservations: Sequence[tuple[int, str, int, ReservationStatus]] = (),
        threshold: int = 3,
    ) -> StockItem:
        item_id = _uid(item_number)
        return StockItem.rehydrate(
            StockItemSnapshot(
                id=item_id,
                company_code=COMPANY,
                product_code=product_code,
                units=units,
                reserved_units=reserved,
                low_stock_threshold=threshold,
                reservations=tuple(
                    ReservationSnapshot(
                        id=_uid(number),
                        stock_id=item_id,
                        product_code=product_code,
                        order_reference=order_reference,
                        retailer_code=RETAILER,
                        units=reserved_units,
                        status=status,
                    )
                    for number, order_reference, reserved_units, status in reservations
                ),
            )
        )

    return build


@pytest.fixture
def id_source() -> Callable[[Sequence[UniqueId]], Callable[[], UniqueId]]:
    """`id_source([a, b, c])` -> a `new_id` that returns a, b, c in order and then fails loudly."""

    def make(supplied: Sequence[UniqueId]) -> Callable[[], UniqueId]:
        queue = list(supplied)

        def new_id() -> UniqueId:
            assert queue, "the domain asked for more identifiers than the test supplied"
            return queue.pop(0)

        return new_id

    return make
