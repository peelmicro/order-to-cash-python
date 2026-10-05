"""Sequential business references: `ORD-`, `DES-`, `INV-`, `CR-` + a zero-padded sequence.

domain-model.md 2.3 places all four in the shared kernel; one generic shape serves them, so
Fulfillment and Billing do not grow copies of the formatter (#8 built only `OrderNumber`; #7
built all four). The sequence is zero-padded to at least six digits and GROWS beyond six rather
than truncating (`ORD-1000000`). A reference is canonical: no leading zero beyond the padding and
a strictly positive sequence, so `parse(str(x)) == x` and `from_sequence(n)` is the only spelling.
"""

from dataclasses import dataclass
from typing import ClassVar, Self

from otc_shared_kernel.errors import InvalidBusinessReferenceError

_MIN_DIGITS = 6
_MAX_SEQUENCE = (1 << 63) - 1  # the allocating counter row is a bigint


@dataclass(frozen=True, slots=True)
class BusinessReference:
    value: str

    PREFIX: ClassVar[str] = ""
    ERROR_CODE: ClassVar[str] = ""

    def __post_init__(self) -> None:
        cls = type(self)
        if not cls.PREFIX:
            raise TypeError("BusinessReference is abstract: use one of its prefixed subclasses")
        if type(self.value) is not str or self._sequence_of(self.value) is None:
            raise InvalidBusinessReferenceError(cls.ERROR_CODE, cls.PREFIX, self.value)

    @classmethod
    def _sequence_of(cls, value: str) -> int | None:
        head = cls.PREFIX + "-"
        digits = value[len(head) :]
        if not value.startswith(head) or not digits.isascii() or not digits.isdigit():
            return None
        # Shorter than six digits is refused by the canonical-spelling check below.
        if len(digits) > len(str(_MAX_SEQUENCE)):
            return None
        sequence = int(digits)
        if sequence < 1 or sequence > _MAX_SEQUENCE or digits != f"{sequence:0{_MIN_DIGITS}d}":
            return None
        return sequence

    @classmethod
    def parse(cls, value: str) -> Self:
        return cls(value)

    @classmethod
    def from_sequence(cls, sequence: int) -> Self:
        if type(sequence) is not int or not 1 <= sequence <= _MAX_SEQUENCE:
            raise InvalidBusinessReferenceError(cls.ERROR_CODE, cls.PREFIX, sequence)
        return cls(f"{cls.PREFIX}-{sequence:0{_MIN_DIGITS}d}")

    @property
    def sequence(self) -> int:
        sequence = self._sequence_of(self.value)
        assert sequence is not None  # noqa: S101 - validated in __post_init__
        return sequence

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class OrderNumber(BusinessReference):
    PREFIX: ClassVar[str] = "ORD"
    ERROR_CODE: ClassVar[str] = "order_number.invalid"


@dataclass(frozen=True, slots=True)
class DespatchReference(BusinessReference):
    PREFIX: ClassVar[str] = "DES"
    ERROR_CODE: ClassVar[str] = "despatch_reference.invalid"


@dataclass(frozen=True, slots=True)
class InvoiceReference(BusinessReference):
    PREFIX: ClassVar[str] = "INV"
    ERROR_CODE: ClassVar[str] = "invoice_reference.invalid"


@dataclass(frozen=True, slots=True)
class CreditLineReference(BusinessReference):
    PREFIX: ClassVar[str] = "CR"
    ERROR_CODE: ClassVar[str] = "credit_line_reference.invalid"
