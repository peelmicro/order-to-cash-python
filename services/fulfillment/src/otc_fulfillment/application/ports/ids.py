"""`IdSource`: where the application gets every identifier it hands to the domain (FS24).

The domain mints nothing itself (`reserve_order` and `release_order` take a required `new_id`);
the handlers pass `scope.ids.new`, so a test that supplies known identifiers observes exactly those
on the reservations and the facts.
"""

from typing import Protocol

from otc_shared_kernel import UniqueId


class IdSource(Protocol):
    def new(self) -> UniqueId: ...
