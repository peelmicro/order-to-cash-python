"""The port every store the seed writes to implements."""

from collections.abc import Mapping
from typing import Protocol

from otc_seed.application.dataset import SeedDataset


class SeedTarget(Protocol):
    """One store: the orders, fulfillment or billing database, or the MongoDB read model."""

    @property
    def name(self) -> str: ...

    async def verify(self) -> None:
        """Raise if the store is not ready to be written (unreachable, or not migrated to head)."""
        ...

    async def seed(self, dataset: SeedDataset) -> Mapping[str, int]:
        """Write what is missing; return the number of rows/documents actually added, per table or
        collection. A store that already holds the dataset adds nothing and returns all zeros."""
        ...
