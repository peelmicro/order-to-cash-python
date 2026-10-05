"""`GLN`: 13 decimal digits, the last a GS1 mod-10 check digit (R4, domain-model.md 2.4)."""

from dataclasses import dataclass

from otc_shared_kernel.errors import InvalidGlnError

_LENGTH = 13
_BODY_LENGTH = 12


def _is_ascii_digits(value: str) -> bool:
    # `str.isdigit()` alone accepts Arabic-Indic and superscript digits; `isascii()` closes that.
    return value.isascii() and value.isdigit()


@dataclass(frozen=True, slots=True)
class GLN:
    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str:
            raise InvalidGlnError(self.value, "must be a str")
        if len(self.value) != _LENGTH or not _is_ascii_digits(self.value):
            raise InvalidGlnError(self.value, "must be exactly 13 ASCII decimal digits")
        expected = self.compute_check_digit(self.value[:_BODY_LENGTH])
        if int(self.value[_BODY_LENGTH]) != expected:
            raise InvalidGlnError(
                self.value, f"check digit must be {expected} (GS1 mod-10 over the first twelve)"
            )

    @staticmethod
    def compute_check_digit(body: str) -> int:
        """Weights 3, 1, 3, 1, ... starting from the rightmost digit of the 12-digit body."""
        if type(body) is not str or len(body) != _BODY_LENGTH or not _is_ascii_digits(body):
            raise InvalidGlnError(body, "a GLN body must be exactly 12 ASCII decimal digits")
        total = sum(
            int(digit) * (3 if distance % 2 == 0 else 1)
            for distance, digit in enumerate(reversed(body))
        )
        return (10 - total % 10) % 10

    def __str__(self) -> str:
        return self.value
