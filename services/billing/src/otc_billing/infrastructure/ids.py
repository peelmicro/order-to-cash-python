"""`UuidIdSource`: random UUIDs (version 4), the production `IdSource`."""

from otc_shared_kernel import UniqueId


class UuidIdSource:
    def new(self) -> UniqueId:
        return UniqueId.new()
