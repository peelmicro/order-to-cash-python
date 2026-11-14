# ruff: noqa: E501 - test names are the sentences the acceptance items use
"""Feature 31: the instruments of the suite, armed WITHOUT a fleet (acceptance items 4 and 6).

An instrument that has never failed proves nothing, so each one is fed the input it must refuse:

* the causal-order check (R24, #8 id 105): a timeline with no `causationId`, a timeline whose cause
  comes after its effect, a timeline that resolves fewer edges than the facts require;
* the money sweep (R1): the Python-specific shapes of a JSON number (`true`, `100.0`, `1e2`, a value
  beyond `bigint`), the currency forms (`eur`, `EURO`, `EUR\\n`, missing) and the sentinel that an
  empty sweep fails;
* `poll`: paced between probes and bounded (#8 id 63).
"""

import asyncio
import sys
import time
from itertools import pairwise
from typing import Any

import pytest

support: Any = sys.modules["api_support"]

A, B, C = (
    "00000000-0000-4000-8000-00000000000a",
    "00000000-0000-4000-8000-00000000000b",
    "00000000-0000-4000-8000-00000000000c",
)


def entry(event_id: str, event_type: str, causation_id: str | None) -> dict[str, Any]:
    found: dict[str, Any] = {
        "eventId": event_id,
        "eventType": event_type,
        "occurredAt": "2026-10-18T10:00:00.000Z",
    }
    if causation_id is not None:
        found["causationId"] = causation_id
    return found


CHAIN = [
    entry(A, "a.happened.v1", None),
    entry(B, "b.happened.v1", A),
    entry(C, "c.happened.v1", B),
]


# ------------------------------------------------------------------------ R24 / #8 id 105


def test_r24_a_timeline_in_causal_order_passes_and_reports_the_edges_it_checked() -> None:
    assert support.assert_causal_order(CHAIN, required_edges=2) == 2


def test_r24_id105_a_timeline_without_any_causation_id_fails_naming_that_no_edges_were_checked() -> (
    None
):
    without = [entry(A, "a.happened.v1", None), entry(B, "b.happened.v1", None)]

    with pytest.raises(AssertionError, match="no causal edges were checked"):
        support.assert_causal_order(without, required_edges=1)


def test_r24_a_timeline_with_two_entries_swapped_fails_naming_the_violation() -> None:
    swapped = [CHAIN[0], CHAIN[2], CHAIN[1]]  # c (caused by b) now sits before b

    with pytest.raises(
        AssertionError,
        match=r"causal order violated: c\.happened\.v1 \(index 1\) precedes its cause b\.happened\.v1 \(index 2\)",
    ):
        support.assert_causal_order(swapped, required_edges=2)


def test_r24_a_timeline_that_resolves_fewer_edges_than_required_fails_naming_both_counts() -> None:
    with pytest.raises(AssertionError, match=r"resolved only 2 causal edge\(s\), fewer than the 3"):
        support.assert_causal_order(CHAIN, required_edges=3)


def test_r24_a_causation_id_naming_nothing_in_the_timeline_is_not_an_edge() -> None:
    foreign = [
        entry(A, "a.happened.v1", "00000000-0000-4000-8000-0000000000ff"),
        entry(B, "b.happened.v1", A),
    ]

    assert support.timeline_edges(foreign) == [(0, 1)]


def test_r24_a_requirement_of_zero_edges_is_refused() -> None:
    with pytest.raises(AssertionError, match="at least one edge"):
        support.assert_causal_order(CHAIN, required_edges=0)


def test_r24_the_required_edges_are_counted_from_the_published_facts() -> None:
    facts = [
        {"eventId": A, "causationId": "00000000-0000-4000-8000-0000000000e1", "eventType": "a"},
        {"eventId": B, "causationId": A, "eventType": "b"},
        {"eventId": C, "causationId": B, "eventType": "c"},
        {"eventId": "d", "causationId": "d", "eventType": "self"},
    ]

    assert support.fact_edges(facts) == 2  # a command id and a self-cause are not edges


# ------------------------------------------------------------------------------------------ R1


def sweep(text: str) -> list[Any]:
    return list(support.sweep_for_money_fields(support.parse_json(text)))


def problems(text: str) -> list[str]:
    return list(support.money_problems(sweep(text)))


def test_r1_a_canonical_money_amount_that_regressed_to_a_decimal_string_is_still_discovered() -> (
    None
):
    """Port of #8's `MoneyFieldSweepCanonicalAmountTests`."""
    [finding] = sweep('{"paymentReference":"P","amount":{"amount":"124250","currency":"EUR"}}')

    assert finding.path == "$.amount.amount"
    assert finding.amount == "124250"
    assert finding.currency == "EUR"
    assert problems('{"amount":{"amount":"124250","currency":"EUR"}}') != []


def test_r1_the_currency_is_inherited_from_the_nearest_ancestor_however_deep() -> None:
    found = sweep(
        '{"currency":"EUR","totals":{"totalAmount":5},"items":[{"unitPrice":7,"lineDiscount":1}]}'
    )

    assert sorted(f.path for f in found) == [
        "$.items[0].lineDiscount",
        "$.items[0].unitPrice",
        "$.totals.totalAmount",
    ]
    assert all(f.currency == "EUR" for f in found)


def test_r1_a_json_true_is_not_a_number_so_it_is_not_flagged_beside_a_currency_but_is_when_it_is_the_amount() -> (
    None
):
    """Python's `bool` is an `int`: `isinstance(True, int)`. `projectionPending: true` sits beside
    `currency` in the real POST /orders answer and must NOT be a money field; `{amount: true}` must
    be one, and must fail the integer check."""
    assert sweep('{"currency":"EUR","projectionPending":true,"totalAmount":3}') != []
    assert [
        f.path for f in sweep('{"currency":"EUR","projectionPending":true,"totalAmount":3}')
    ] == ["$.totalAmount"]

    [finding] = sweep('{"amount":true,"currency":"EUR"}')
    assert finding.path == "$.amount"
    assert any(
        "integer count of minor units, got True" in p for p in support.money_problems([finding])
    )


@pytest.mark.parametrize("token", ["100.0", "1e2", "1E+2", "1.5", "-0.0", "100.00"])
def test_r1_a_json_number_written_as_a_decimal_is_refused_and_named(token: str) -> None:
    text = f'{{"currency":"EUR","totalAmount":{token}}}'

    [message] = problems(text)

    assert message.startswith("$.totalAmount: R1 requires an integer"), message
    assert support.find_decimal_numbers(support.parse_json(text)) == [f"$.totalAmount={token}"]


@pytest.mark.parametrize(
    ("number", "refused"),
    [
        (2**63 - 1, False),
        (-(2**63), False),
        (0, False),
        (2**63, True),
        (-(2**63) - 1, True),
        (10**30, True),
    ],
)
def test_r1_an_integer_beyond_the_bigint_column_is_refused(number: int, refused: bool) -> None:
    messages = problems(f'{{"currency":"EUR","totalAmount":{number}}}')

    assert (messages != []) is refused, messages
    if refused:
        assert "beyond the bigint column" in messages[0]


@pytest.mark.parametrize(
    ("currency_json", "accepted"),
    [
        ('"EUR"', True),
        ('"JPY"', True),
        (
            '"XXX"',
            True,
        ),  # shaped like a code; whether it IS an ISO 4217 code is checked against the services' own currencies table, not here
        ('"eur"', False),
        ('"Eur"', False),
        ('"EURO"', False),
        ('"EU"', False),
        ('""', False),
        ('" EUR"', False),
        ('"EUR\\n"', False),
        ('"EUR "', False),
        ('"€UR"', False),
        ("978", False),
        ("null", False),
        ("true", False),
        ("[]", False),
    ],
)
def test_r1_the_currency_must_be_exactly_three_capital_letters(
    currency_json: str, accepted: bool
) -> None:
    messages = problems(f'{{"currency":{currency_json},"totalAmount":5}}')

    assert (messages == []) is accepted, messages


def test_r1_a_money_field_with_no_currency_anywhere_above_it_is_not_discovered_so_the_minimum_is_the_guard() -> (
    None
):
    assert sweep('{"totalAmount":5}') == []
    with pytest.raises(
        AssertionError, match=r"found 0 monetary field\(s\), fewer than the 3.*vacuous"
    ):
        support.check_money_findings("GET /example", sweep('{"totalAmount":5}'), minimum=3)


def test_r1_a_response_whose_money_fields_all_vanished_fails_the_minimum_naming_the_response() -> (
    None
):
    with pytest.raises(
        AssertionError,
        match=r"POST /orders: the sweep found 1 monetary field\(s\), fewer than the 3",
    ):
        support.check_money_findings(
            "POST /orders", sweep('{"currency":"EUR","totalAmount":5}'), minimum=3
        )


def test_r1_the_failure_names_the_path_of_every_violation_not_only_the_first() -> None:
    findings = sweep('{"currency":"eur","totals":{"initialAmount":1.5,"totalAmount":2}}')

    with pytest.raises(AssertionError) as failure:
        support.check_money_findings("GET /orders/{id}", findings, minimum=1)

    for path in ("$.totals.initialAmount", "$.totals.totalAmount"):
        assert path in str(failure.value)


# ---------------------------------------------------------------------------------------- poll


async def test_poll_waits_between_probes_and_gives_up_naming_what() -> None:
    """#8 id 63: the pacing is proven by a CHANGE OF KIND. A probe that never succeeds is called
    at most once per `PACING_SECONDS`: with the sleep deleted it would be called thousands of times
    in the same window; and the bound is `asyncio.timeout`, so the wait ends and names `what`."""
    calls: list[float] = []

    async def never() -> None:
        calls.append(time.monotonic())
        await asyncio.sleep(0)  # yields, so a loop without its pacing sleep is still cancellable
        return None

    began = time.monotonic()
    try:
        # an OUTSIDE bound: a poll whose own bound was widened or deleted fails here, by name
        async with asyncio.timeout(5):
            with pytest.raises(TimeoutError, match=r"never happened within 0\.55 s: the thing"):
                await support.poll(never, "the thing", seconds=0.55)
    except TimeoutError:
        pytest.fail(
            f"poll(seconds=0.55) did not end at its own bound within 5 s ({len(calls)} probes): "
            "the bound is not the asyncio.timeout the claim names"
        )

    elapsed = time.monotonic() - began
    assert 0.5 <= elapsed < 2.0
    assert 4 <= len(calls) <= 7, (
        f"{len(calls)} probes in 0.55 s: the loop is not paced at {support.PACING_SECONDS} s"
    )
    gaps = [b - a for a, b in pairwise(calls)]
    assert min(gaps) >= support.PACING_SECONDS * 0.9, gaps


async def test_poll_returns_the_first_truthy_answer_without_waiting_for_the_bound() -> None:
    answers: Any = iter([None, 0, "", [], "found"])

    async def probe() -> Any:
        return next(answers)

    began = asyncio.get_running_loop().time()
    assert await support.poll(probe, "an answer", seconds=30) == "found"
    assert asyncio.get_running_loop().time() - began < 2.0
