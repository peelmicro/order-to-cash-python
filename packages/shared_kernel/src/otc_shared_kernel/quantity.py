"""`Quantity`: a strictly positive whole-unit count (R3, domain-model.md 2.2)."""

from dataclasses import dataclass

from otc_shared_kernel.errors import QuantityMustBePositiveError


@dataclass(frozen=True, slots=True)
class Quantity:
    """Strictly positive `int`. Zero, negatives, fractions, `bool` and every non-`int` are refused.

    There is deliberately no float-accepting entry point (#8 needed `From(double)` only because
    C# could not otherwise express "fractional"): Python checks the runtime type, so a `2.0` or
    `2.5` is refused by `__post_init__` itself.
    """

    value: int

    def __post_init__(self) -> None:
        # `type(...) is int` (not isinstance): `bool` is a subclass of int, and so is any IntEnum.
        if type(self.value) is not int or self.value <= 0:
            raise QuantityMustBePositiveError(self.value)

    def __str__(self) -> str:
        return str(self.value)
