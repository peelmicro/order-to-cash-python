"""Fixed, past UTC instants: no `datetime.now()` anywhere in the seed.

Every timestamp the seed writes is computed from one of these constants, so two runs produce
byte-identical rows. All of them are whole milliseconds (indeed whole seconds), so the
`timestamptz(3)` rounding and the wire formatter's truncation can never disagree on a seeded value
(backlog 205): `tests/unit/test_seed_instants.py` asserts it over every instant of the dataset.
"""

from datetime import UTC, datetime, timedelta

# Every master-data row (currencies, products, retailers, companies, credit lines, stock) is
# stamped with this instant: before any order was ever placed.
MASTER_DATA_TIMESTAMP = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
# The first sample order's date; the others are whole days after it.
BASE_DATE = datetime(2026, 6, 1, 9, 0, 0, tzinfo=UTC)


def add_minutes(instant: datetime, minutes: int) -> datetime:
    return instant + timedelta(minutes=minutes)


def add_seconds(instant: datetime, seconds: int) -> datetime:
    return instant + timedelta(seconds=seconds)


def add_days(instant: datetime, days: int) -> datetime:
    return instant + timedelta(days=days)


def format_instant(instant: datetime) -> str:
    """`YYYY-MM-DDTHH:MM:SS.mmmZ` (UTC, milliseconds truncated): #7's `toISOString()`.

    The same text `otc_contracts.wire.format_instant` writes; this copy exists because the domain
    may not import `otc_contracts` (pydantic). `tests/unit/test_seed_instants.py` pins the two
    to each other over every instant of the dataset.
    """
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("an instant must be timezone-aware")
    utc = instant.astimezone(UTC)
    return (
        f"{utc.year:04d}-{utc.month:02d}-{utc.day:02d}"
        f"T{utc.hour:02d}:{utc.minute:02d}:{utc.second:02d}.{utc.microsecond // 1000:03d}Z"
    )
