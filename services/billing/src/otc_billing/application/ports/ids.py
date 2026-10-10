"""`IdSource`: where the application gets every identifier it hands to the domain (BC36).

The domain mints nothing itself (`approve`, `refuse`, `release` and `consume` take a required
`new_id`); the transactional units pass `scope.ids.new`, so a test that supplies known identifiers
observes exactly those on the ledger entries and the facts.
"""

from typing import Protocol

from otc_shared_kernel import UniqueId


class IdSource(Protocol):
    def new(self) -> UniqueId: ...
