"""The replenish transactional unit (`design.md` 6.4, 7.3): all-or-nothing, not idempotent (FS14).

Every named item is locked first; if any product has no row `UnknownStockItemError` is raised BEFORE
any line is replenished, so a partial application is impossible. A repeated product's lines are
summed. The column width is enforced where the repository assigns `units` (FS20). No outbox row:
a top-up is a delta, and R61 emits no fact.
"""

from functools import partial

from otc_fulfillment.application.messages import (
    ReplenishResult,
    ReplenishStockCommand,
    StockViewData,
)
from otc_fulfillment.application.ports.stock_store import StockTransaction
from otc_fulfillment.application.scope import FulfillmentScope
from otc_shared_kernel import Quantity


class UnknownStockItemError(Exception):
    """A replenish line names a product with no stock item under the company (FS14)."""

    def __init__(self, company_code: str, product_code: str) -> None:
        super().__init__(f"no stock item for product {product_code!r} of company {company_code!r}")
        self.company_code = company_code
        self.product_code = product_code


async def _replenish_work(
    tx: StockTransaction, *, command: ReplenishStockCommand
) -> ReplenishResult:
    totals: dict[str, int] = {}
    for line in command.lines:
        totals[line.product_code] = totals.get(line.product_code, 0) + line.units.value
    repository = tx.repository
    items = await repository.lock_for_replenish(command.company_code, list(totals))
    for product_code in totals:
        if product_code not in items:
            raise UnknownStockItemError(command.company_code, product_code)
    for product_code, total in totals.items():
        items[product_code].replenish(Quantity(total))
    await repository.save()
    return ReplenishResult(
        items=tuple(
            StockViewData(
                company_code=items[code].company_code,
                product_code=items[code].product_code,
                units=items[code].units,
                reserved_units=items[code].reserved_units,
                low_stock_threshold=items[code].low_stock_threshold,
            )
            for code in totals
        )
    )


async def replenish(command: ReplenishStockCommand, scope: FulfillmentScope) -> ReplenishResult:
    return await scope.transactions.run(partial(_replenish_work, command=command))
