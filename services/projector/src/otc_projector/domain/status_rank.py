"""The status rank table (`PR12`): the status a fact proves was reached, totalised by an integer.

`completed` and `cancelled` outrank every in-flight status, so a late in-flight fact can never
regress a terminal document (`R52`): the stored status is raised only when the new rank is strictly
greater. The nine pairs are pinned to `tests/fixtures/read_model_constants.json` (`PR40`); the
seed keeps its own local copy pinned to the same file. A status-less fact has rank `0`.
"""

from types import MappingProxyType

STATUS_RANK = MappingProxyType(
    {
        "placed": 1,
        "stock_reserved": 2,
        "credit_approved": 3,
        "confirmed": 4,
        "despatched": 5,
        "invoiced": 6,
        "paid": 7,
        "completed": 98,
        "cancelled": 99,
    }
)

NO_RANK = 0


def rank_of(status: str | None) -> int:
    """The rank of an implied status; `None` (a fact that implies none) is rank `0`."""
    if status is None:
        return NO_RANK
    return STATUS_RANK[status]
