"""The six handlers, thin (`design.md` 7.1; `despatch.create` is feature 18): each takes the scope
and delegates to a read or to a transactional unit. Registered one statement each in
`composition.register_handlers`."""

from otc_fulfillment.application import despatch_creation, stock_replenishment, stock_reservation
from otc_fulfillment.application.messages import (
    CheckStockQuery,
    CreateDespatchCommand,
    DespatchResult,
    ListStockQuery,
    ReleaseResult,
    ReleaseStockCommand,
    ReplenishResult,
    ReplenishStockCommand,
    ReserveResult,
    ReserveStockCommand,
    StockAvailability,
    StockPage,
)
from otc_fulfillment.application.scope import FulfillmentScope


class CheckStockHandler:
    def __init__(self, scope: FulfillmentScope) -> None:
        self._scope = scope

    async def handle(self, query: CheckStockQuery, /) -> StockAvailability:
        return await self._scope.reads.availability(
            query.company_code, [(line.product_code, line.requested) for line in query.lines]
        )


class ListStockHandler:
    def __init__(self, scope: FulfillmentScope) -> None:
        self._scope = scope

    async def handle(self, query: ListStockQuery, /) -> StockPage:
        return await self._scope.reads.list(
            page=query.page,
            page_size=query.page_size,
            company_code=query.company_code,
            product_code=query.product_code,
            below_threshold=query.below_threshold,
        )


class ReserveStockHandler:
    def __init__(self, scope: FulfillmentScope) -> None:
        self._scope = scope

    async def handle(self, command: ReserveStockCommand, /) -> ReserveResult:
        return await stock_reservation.reserve(command, self._scope)


class ReleaseStockHandler:
    def __init__(self, scope: FulfillmentScope) -> None:
        self._scope = scope

    async def handle(self, command: ReleaseStockCommand, /) -> ReleaseResult:
        return await stock_reservation.release(command, self._scope)


class ReplenishStockHandler:
    def __init__(self, scope: FulfillmentScope) -> None:
        self._scope = scope

    async def handle(self, command: ReplenishStockCommand, /) -> ReplenishResult:
        return await stock_replenishment.replenish(command, self._scope)


class CreateDespatchHandler:
    def __init__(self, scope: FulfillmentScope) -> None:
        self._scope = scope

    async def handle(self, command: CreateDespatchCommand, /) -> DespatchResult:
        return await despatch_creation.create(command, self._scope)
