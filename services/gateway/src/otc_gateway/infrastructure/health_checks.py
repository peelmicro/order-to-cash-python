"""R60 for the Gateway: the two dependencies it owns, each bounded (`openapi.yaml` `healthReady`).

The Gateway has no write model; it depends on the RPC transport (NATS) and the read model (MongoDB).
Each check is bounded by `asyncio.timeout`: a docker-paused broker leaves the TCP connection open
and an unbounded ping would hang the probe (#7's NATS probe shipped without a bound, disclosed by
its implementer: `order-to-cash-nestjs/progress/impl_observability_reliability.md:912`). Liveness
consults none of this.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

CHECK_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    up: bool
    detail: str | None


@dataclass(frozen=True, slots=True)
class HealthCheck:
    name: str
    probe: Callable[[], Awaitable[object]]
    timeout_seconds: float = CHECK_TIMEOUT_SECONDS

    async def run(self) -> CheckResult:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                await self.probe()
        except TimeoutError:
            return CheckResult(self.name, False, f"no answer within {self.timeout_seconds} s")
        except Exception as error:
            return CheckResult(self.name, False, type(error).__name__)
        return CheckResult(self.name, True, None)
