"""`UniqueId`: a UUID generated inside the domain (domain-model.md 2.5), version 4.

#7 generates v4 (`unique-id.ts:27`, `crypto.randomUUID()`) and #8 generates v4 (`UniqueId.cs:18`,
`Guid.NewGuid()`); `uuid.uuid4()` matches. Parsing accepts any non-nil UUID in canonical
hyphenated form (as #8 does; #7's parse insists on v4) because an `eventId` or seeded key arrives
from outside and the domain's duty is "a real UUID", not "a v4".
"""

import uuid
from dataclasses import dataclass
from typing import Self

from otc_shared_kernel.errors import InvalidUniqueIdError

_CANONICAL_LENGTH = 36


@dataclass(frozen=True, slots=True)
class UniqueId:
    value: uuid.UUID

    def __post_init__(self) -> None:
        if type(self.value) is not uuid.UUID or self.value.int == 0:
            raise InvalidUniqueIdError(self.value)

    @classmethod
    def new(cls) -> Self:
        return cls(uuid.uuid4())

    @classmethod
    def parse(cls, value: str) -> Self:
        if type(value) is not str or len(value) != _CANONICAL_LENGTH:
            raise InvalidUniqueIdError(value)
        try:
            parsed = uuid.UUID(value)
        except ValueError:
            raise InvalidUniqueIdError(value) from None
        if str(parsed) != value.lower():
            raise InvalidUniqueIdError(value)
        return cls(parsed)

    def __str__(self) -> str:
        return str(self.value)
