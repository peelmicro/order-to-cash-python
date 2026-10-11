"""`ProjectorScope`: the per-message scope of the dispatcher (`S` in `otc_cqrs.Dispatcher[S]`).

The composition root builds one for every inbound message; the dispatcher stores none. A binding the
root forgot is refused HERE, at construction, which the root also does once at boot: never as an
`AttributeError` on the first message.
"""

from dataclasses import dataclass, fields

from otc_projector.application.ports.read_model import ReadModelWriter
from otc_projector.application.ports.update_signal import UpdateSignalPublisher


class MissingBindingError(Exception):
    """A port of the scope was given no implementation."""

    def __init__(self, binding: str) -> None:
        super().__init__(f"the composition root bound nothing to the {binding!r} port")
        self.binding = binding


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectorScope:
    read_model: ReadModelWriter
    signals: UpdateSignalPublisher

    def __post_init__(self) -> None:
        for field in fields(self):
            if getattr(self, field.name) is None:
                raise MissingBindingError(field.name)
