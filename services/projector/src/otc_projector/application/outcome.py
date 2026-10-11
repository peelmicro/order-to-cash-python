"""What applying one fact came to: the fact was applied, or it had been applied before."""

import enum


class ProjectionOutcome(enum.Enum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
