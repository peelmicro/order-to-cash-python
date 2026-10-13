"""`SystemClock`: the wall clock, as an aware UTC instant in whole milliseconds (OI19).

The projector's only reader of "now" is the fact retry wrapper (`messaging/fact_retry.py`), which
stamps the dead-letter headers and measures the processing latency.
"""

from datetime import UTC, datetime

from otc_contracts import wire_instant


class SystemClock:
    def now(self) -> datetime:
        return wire_instant(datetime.now(UTC))
