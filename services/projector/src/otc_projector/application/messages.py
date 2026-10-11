"""The ONE command of the projector (`PR27`).

The behaviour is uniform in `eventType` and all fourteen variations live in `project`, so there is a
single `ProjectFactCommand` carrying the whole parsed envelope (no field is copied by hand:
#8 id 58).
"""

from dataclasses import dataclass

from otc_contracts import FactEvent
from otc_cqrs import Command
from otc_projector.application.outcome import ProjectionOutcome


@dataclass(frozen=True, slots=True)
class ProjectFactCommand(Command[ProjectionOutcome]):
    event: FactEvent
