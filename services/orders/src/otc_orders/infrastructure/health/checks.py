"""R60: one bounded readiness check per dependency, and the `HealthResponse` they add up to.

The canonical copy is Orders'; every other service holds an identical copy
(`tests/architecture/test_observability_copy_parity.py`), and the Gateway's is
`infrastructure/health_checks.py`. Each `HealthCheck` is run under `asyncio.timeout`: a
docker-paused broker leaves the TCP connection open, and an unbounded probe would hang the endpoint
(#7's NATS probe shipped without a bound, disclosed by its implementer:
`order-to-cash-nestjs/progress/impl_observability_reliability.md:912`). The checks run together, so
a hung one costs one bound, not several. Liveness consults none of this.

`task_reasons` is the other half of readiness: the asyncio tasks that serve a dependency (a
responder, a consumer, the relay) are attributed to that dependency's check, so a task that died
makes its own check `down` while the probe of a healthy dependency stays `up`. It reads task state
only and does no I/O.
"""

import asyncio
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass

from otc_contracts.generated import openapi

type Probe = Callable[[], Awaitable[object]]

CHECK_TIMEOUT_SECONDS = 2.0
SHUTTING_DOWN = "shutting down"


def no_reasons() -> Sequence[str]:
    return ()


def dead_tasks(
    tasks: Mapping[str, asyncio.Task[None]], names: Collection[str]
) -> Callable[[], Sequence[str]]:
    """The `task_reasons` of a check: one reason for each of `names` whose task is done. Read live
    from the tasks (a done-callback may not have run yet); a name with no task is not a reason."""

    def reasons() -> Sequence[str]:
        return [
            f"transport task {name} is not running"
            for name in names
            if name in tasks and tasks[name].done()
        ]

    return reasons


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    up: bool
    detail: str | None


@dataclass(frozen=True, slots=True)
class HealthCheck:
    name: str
    probe: Probe
    timeout_seconds: float = CHECK_TIMEOUT_SECONDS
    task_reasons: Callable[[], Sequence[str]] = no_reasons

    async def run(self) -> CheckResult:
        reasons = self.task_reasons()
        if reasons:
            return CheckResult(self.name, False, "; ".join(reasons))
        try:
            async with asyncio.timeout(self.timeout_seconds):
                await self.probe()
        except TimeoutError:
            return CheckResult(self.name, False, f"no answer within {self.timeout_seconds} s")
        except Exception as error:
            return CheckResult(self.name, False, type(error).__name__)
        return CheckResult(self.name, True, None)


async def run_checks(
    checks: Sequence[HealthCheck], *, shutting_down: bool = False
) -> list[CheckResult]:
    """Every check at once; a service that is shutting down answers `down` for all of them without
    probing anything (its connections are closing)."""
    if shutting_down:
        return [CheckResult(check.name, False, SHUTTING_DOWN) for check in checks]
    return list(await asyncio.gather(*(check.run() for check in checks)))


def health_body(results: Sequence[CheckResult]) -> openapi.HealthResponse:
    up = all(result.up for result in results)
    return openapi.HealthResponse(
        status=openapi.Status.up if up else openapi.Status.down,
        checks={
            result.name: openapi.Checks(
                status=openapi.Status.up if result.up else openapi.Status.down,
                detail=result.detail,
            )
            for result in results
        },
    )
