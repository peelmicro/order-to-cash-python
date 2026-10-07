"""`format_money`: the human text of an amount (OP-1, moved here from the seed's domain).

The fourteen vectors are the seed's (`services/seed/tests/unit/test_money_text.py`), ported from
#8's `TimelineMoneyFormattingTests.cs` and #7's `money-text.spec.ts`. The expected strings are typed
here, not produced by the function, and every figure is non-round so that "divide by 100" cannot
pass by coincidence for the currencies whose exponent is not 2 (JPY 0, KWD 3, CLF 4).
"""

import pytest

from otc_shared_kernel import format_money


@pytest.mark.parametrize(
    ("minor", "currency", "text"),
    [
        (16130, "EUR", "161.30 EUR"),
        (24999, "EUR", "249.99 EUR"),
        (10055, "GBP", "100.55 GBP"),
        (5, "EUR", "0.05 EUR"),
        (0, "USD", "0.00 USD"),
        (123456789, "EUR", "1 234 567.89 EUR"),
        (100000, "EUR", "1 000.00 EUR"),
        (999, "EUR", "9.99 EUR"),
        (1234567, "JPY", "1 234 567 JPY"),
        (1234, "KWD", "1.234 KWD"),
        (12345, "CLF", "1.2345 CLF"),
        (-5, "EUR", "-0.05 EUR"),
        (-123456, "EUR", "-1 234.56 EUR"),
        (9223372036854775807, "EUR", "92 233 720 368 547 758.07 EUR"),
    ],
)
def test_format_money_is_exponent_scaled_and_grouped(minor: int, currency: str, text: str) -> None:
    assert format_money(minor, currency) == text
