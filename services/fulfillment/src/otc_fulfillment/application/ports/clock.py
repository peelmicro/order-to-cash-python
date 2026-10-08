"""Fulfillment's COPY of Orders' `application/ports/clock.py` (the canonical).

The canonical: `services/orders/src/otc_orders/application/ports/clock.py`.
After this docstring the copy equals it, modulo the token map `otc_orders` ->
`otc_fulfillment` and `ORDERS_FACTS_TOPIC` -> `FULFILLMENT_FACTS_TOPIC`, and modulo the
formatter's line reflow of the longer names. Any other difference fails
`tests/architecture/test_outbox_copy_parity.py`. Change the canonical, never this copy.
"""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """An aware UTC instant, truncated to whole milliseconds."""
        ...
