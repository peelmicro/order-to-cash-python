"""`GatewayRuntime`: what the lifespan stores in `app.state.runtime` and every route reads.

Built by the composition root (`otc_gateway.composition`), which is the only place adapters are
chosen. A frozen value: the routes never reach an adapter, only these members.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from otc_cqrs import Dispatcher
from otc_gateway.application.ports.clock import Clock
from otc_gateway.application.ports.tokens import TokenService
from otc_gateway.application.scope import GatewayScope
from otc_gateway.application.stream.hub import StreamHub
from otc_gateway.domain.login_throttle import LoginThrottle
from otc_gateway.infrastructure.health_checks import HealthCheck


@dataclass(frozen=True, slots=True)
class GatewayRuntime:
    dispatcher: Dispatcher[GatewayScope]
    scope: GatewayScope  # one per runtime: every adapter in it is shared and per-request-safe
    tokens: TokenService
    login_throttle: LoginThrottle
    clock: Clock
    health_checks: Sequence[HealthCheck]
    openapi_document: str  # the committed specs/shared/openapi.yaml, as text (GET /docs)
    stream_hub: StreamHub  # GET /orders/stream: the replay buffer and the fan-out
    stream_ping_interval_seconds: float  # the heartbeat of every open stream
