"""`GatewayScope`: the per-request scope of the dispatcher (`S` in `otc_cqrs.Dispatcher[S]`).

The composition root builds one for every inbound request; the dispatcher stores none. A binding the
root forgot is refused HERE, at construction, which the root also does once at boot: never as an
`AttributeError` on the first request. It satisfies `OrderReadScope` structurally, which is all the
list and detail handlers ever ask of it.
"""

from dataclasses import dataclass, fields

from otc_gateway.application.ports.operators import OperatorDirectory
from otc_gateway.application.ports.order_read_model import OrderReadModel
from otc_gateway.application.ports.rpc_client import RpcClient
from otc_gateway.application.ports.tokens import TokenService
from otc_gateway.domain.issued_order_window import IssuedOrderWindow


class MissingBindingError(Exception):
    """A port of the scope was given no implementation."""

    def __init__(self, binding: str) -> None:
        super().__init__(f"the composition root bound nothing to the {binding!r} port")
        self.binding = binding


@dataclass(frozen=True, slots=True, kw_only=True)
class GatewayScope:
    rpc: RpcClient
    read_model: OrderReadModel
    issued_orders: IssuedOrderWindow
    tokens: TokenService
    operators: OperatorDirectory

    def __post_init__(self) -> None:
        for field in fields(self):
            if getattr(self, field.name) is None:
                raise MissingBindingError(field.name)
