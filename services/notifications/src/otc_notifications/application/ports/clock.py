"""`Clock`: the only source of "now" for application and infrastructure code."""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """An aware UTC instant, truncated to whole milliseconds."""
        ...
