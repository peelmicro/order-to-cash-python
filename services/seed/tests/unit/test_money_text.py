"""Human money text: the exponent comes from ISO 4217 (SA-5), grouping is a single ASCII space.

R-map (feature_list.json id 12, acceptance 3: the timeline summaries): ported from #8's
`TimelineMoneyFormattingTests.cs` (exponent-scaled, grouped amounts; non-round figures so a naive
"divide by 100" cannot pass by coincidence) and #7's `money-text.spec.ts` shapes. The expected
strings are typed here, not produced by the function.
"""

import pytest

from otc_seed.domain.data.sagas import SAGAS
from otc_seed.domain.money_text import format_money


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


def test_every_credit_summary_of_the_dataset_renders_the_amount_as_money() -> None:
    expected = {
        "ORD-000001": "Credit hold of 161.30 EUR approved",
        "ORD-000002": "Credit hold of 103.74 EUR approved",
        "ORD-000003": "Credit hold of 194.50 EUR approved",
        "ORD-000004": "Credit hold of 239.72 EUR approved",
        "ORD-000005": "Credit hold of 100.55 GBP approved",
        "ORD-000006": "Credit hold of 249.99 EUR rejected (simulated_cents_rule)",
    }
    seen: dict[str, str] = {}
    for saga in SAGAS:
        (entry,) = (
            t for t in saga.timeline if t.event_type.startswith("credit.") and "hold" in t.summary
        )
        seen[saga.order_reference] = entry.summary
    assert seen == expected
