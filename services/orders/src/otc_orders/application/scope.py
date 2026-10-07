"""`OrdersScope`: the per-message scope of the dispatcher (`S` in `otc_cqrs.Dispatcher[S]`).

The composition root builds one for every inbound message and hands it to `Dispatcher.send`; the
dispatcher stores none. A binding the root forgot is refused HERE, at construction, which the root
also does once at boot: never as an `AttributeError` on the first message.
"""

from dataclasses import MISSING, dataclass, fields

from otc_cqrs import Dispatcher
from otc_orders.application.ports.clock import Clock
from otc_orders.application.ports.reference_catalog import ReferenceCatalog
from otc_orders.application.ports.saga_signal import SagaCommandSignal
from otc_orders.application.ports.stock_availability import StockAvailability
from otc_orders.application.ports.unit_of_work import UnitOfWork
from otc_orders.application.saga.fact_consumption import FactConsumption


class MissingBindingError(Exception):
    """A port of the scope was given no implementation."""

    def __init__(self, binding: str) -> None:
        super().__init__(f"the composition root bound nothing to the {binding!r} port")
        self.binding = binding


@dataclass(frozen=True, slots=True, kw_only=True)
class OrdersScope:
    unit_of_work: UnitOfWork
    catalog: ReferenceCatalog
    stock: StockAvailability
    clock: Clock
    # The saga's bindings (feature 16). Optional so that a scope built for the `orders.create` path
    # needs none of them; a handler that needs one asks for it with `required`, and the composition
    # root builds every registered handler once at boot, so a forgotten binding fails the boot.
    dispatcher: Dispatcher[OrdersScope] | None = None
    fact_consumption: FactConsumption | None = None
    saga_signal: SagaCommandSignal | None = None

    def __post_init__(self) -> None:
        for field in fields(self):
            required = field.default is MISSING
            if required and getattr(self, field.name) is None:
                raise MissingBindingError(field.name)

    def required_dispatcher(self) -> Dispatcher[OrdersScope]:
        if self.dispatcher is None:
            raise MissingBindingError("dispatcher")
        return self.dispatcher

    def required_fact_consumption(self) -> FactConsumption:
        if self.fact_consumption is None:
            raise MissingBindingError("fact_consumption")
        return self.fact_consumption

    def required_saga_signal(self) -> SagaCommandSignal:
        if self.saga_signal is None:
            raise MissingBindingError("saga_signal")
        return self.saga_signal
