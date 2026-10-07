"""`SystemClock`: the wall clock, as an aware UTC instant in whole milliseconds (OI19)."""

from datetime import UTC, datetime

from otc_contracts import wire_instant


class SystemClock:
    def now(self) -> datetime:
        return wire_instant(datetime.now(UTC))
