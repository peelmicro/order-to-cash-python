"""The seed use case: verify every target, then write each one.

Verification of ALL targets comes first, so a database that is not migrated stops the run before
anything is written anywhere. The stores are independent (a database per service, plus MongoDB),
so there is no cross-store transaction; each relational target writes in one transaction of its
own, and because every write is "insert what is missing", a run that failed halfway is completed
by running it again.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from otc_seed.application.dataset import SeedDataset, default_dataset
from otc_seed.application.ports import SeedTarget


@dataclass(frozen=True, slots=True)
class SeedReport:
    """Rows/documents added by this run: target name -> table or collection -> count."""

    added: Mapping[str, Mapping[str, int]]

    @property
    def total_added(self) -> int:
        return sum(count for tables in self.added.values() for count in tables.values())


async def run_seed(targets: Sequence[SeedTarget], dataset: SeedDataset | None = None) -> SeedReport:
    names = [target.name for target in targets]
    if len(set(names)) != len(names):
        raise ValueError(f"two targets share a name: {names}")
    data = dataset if dataset is not None else default_dataset()
    for target in targets:
        await target.verify()
    added: dict[str, Mapping[str, int]] = {}
    for target in targets:
        added[target.name] = dict(await target.seed(data))
    return SeedReport(added)
