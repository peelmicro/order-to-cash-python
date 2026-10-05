"""`Entity` and `AggregateRoot` (identity equality; collected domain events)."""

from otc_shared_kernel.unique_id import UniqueId


class Entity:
    """Two entities are equal iff they are the same concrete type AND carry the same `UniqueId`."""

    __slots__ = ("_id",)

    def __init__(self, entity_id: UniqueId) -> None:
        if type(entity_id) is not UniqueId:
            raise TypeError("an entity's identity must be a UniqueId")
        self._id = entity_id

    @property
    def id(self) -> UniqueId:
        return self._id

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Entity):
            return NotImplemented
        return type(self) is type(other) and self._id == other._id

    def __hash__(self) -> int:
        return hash((type(self), self._id))


class AggregateRoot(Entity):
    """Collects the domain events an operation raised; the application layer reads and clears them.

    Events are typed `object`: the fact envelope (R11) lives in `contracts`, not here, and the
    kernel must not depend on it.
    """

    __slots__ = ("_domain_events",)

    def __init__(self, entity_id: UniqueId) -> None:
        super().__init__(entity_id)
        self._domain_events: list[object] = []

    @property
    def domain_events(self) -> tuple[object, ...]:
        return tuple(self._domain_events)

    def _raise_event(self, event: object) -> None:
        self._domain_events.append(event)

    def pull_domain_events(self) -> tuple[object, ...]:
        """Read AND clear: returns what was raised and leaves the aggregate with none."""
        events = tuple(self._domain_events)
        self._domain_events.clear()
        return events

    def clear_domain_events(self) -> None:
        self._domain_events.clear()
