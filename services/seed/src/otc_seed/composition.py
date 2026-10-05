"""The composition root of the seed: the only place adapters are chosen.

Reads configuration through `SeedSettings` (pydantic-settings) only. Engines and the MongoDB client
belong to a `SeedRuntime`, which the caller closes (`aclose`) in the same event loop that used them.
The wiring is validated at build time: every expected target must be present, exactly once, and an
unknown or missing one raises here, not as an `AttributeError` on the first write.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pymongo import AsyncMongoClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from otc_seed.application import SeedTarget
from otc_seed.infrastructure.mongo import MongoTimelineTarget
from otc_seed.infrastructure.postgres import BillingTarget, FulfillmentTarget, OrdersTarget
from otc_seed.infrastructure.settings import SeedSettings

EXPECTED_TARGETS: tuple[str, ...] = ("orders", "fulfillment", "billing", "mongo")


def validate_wiring(targets: Sequence[SeedTarget]) -> None:
    names = [target.name for target in targets]
    if sorted(names) != sorted(EXPECTED_TARGETS):
        raise RuntimeError(f"seed wiring: expected targets {list(EXPECTED_TARGETS)}, got {names}")


@dataclass(slots=True)
class SeedRuntime:
    targets: tuple[SeedTarget, ...]
    _engines: tuple[AsyncEngine, ...]
    _mongo: AsyncMongoClient[dict[str, Any]]

    async def aclose(self) -> None:
        for engine in self._engines:
            await engine.dispose()
        await self._mongo.close()


def build_runtime(settings: SeedSettings) -> SeedRuntime:
    orders = create_async_engine(settings.orders_url)
    fulfillment = create_async_engine(settings.fulfillment_url)
    billing = create_async_engine(settings.billing_url)
    mongo: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.mongo_connection_uri)
    targets: tuple[SeedTarget, ...] = (
        OrdersTarget(orders),
        FulfillmentTarget(fulfillment),
        BillingTarget(billing),
        MongoTimelineTarget(mongo, settings.mongo_database),
    )
    validate_wiring(targets)
    return SeedRuntime(targets, (orders, fulfillment, billing), mongo)
