"""The issue-fixture builder refuses coinciding or zero totals unless told (task F1; BI38).

#8's round-1 blocking defect `D2`: replacing the request's discount with `0` left 199 unit and 74
integration tests green, because every issue request the suite sent carried a zero discount. The
builder lives in the integration conftest; a conftest is not importable by name under
`--import-mode=importlib`, so the module is loaded from its path (the pattern of
`test_cents_rule_fixture_guard.py`), and the function tested is the very one the `issue_body`
fixture hands out.

Loop scope: nothing here is async.
"""

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

CONFTEST = Path(__file__).resolve().parents[1] / "integration" / "conftest.py"
ORDER = {"order_reference": "ORD-000101", "retailer_code": "RETAIL-77", "company_code": "SUPPLY-CO"}


def _conftest() -> ModuleType:
    spec = importlib.util.spec_from_file_location("billing_integration_conftest_f1", CONFTEST)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build() -> Callable[..., Any]:
    builder: Callable[..., Any] = _conftest().build_issue_fixture
    return builder


# 3 x 1999 + 2 x 1234 = 8465: with discount 350 the total is 8115
LINES = [("PRD-ZZ", 3, 1999), ("PRD-AA", 2, 1234)]


def test_the_issue_fixture_computes_the_figures_from_the_lines_and_accepts_distinct_ones() -> None:
    fixture = build()(LINES, 350, **ORDER)
    assert (fixture.amount, fixture.discount, fixture.total) == (8465, 350, 8115)
    assert fixture.body["discount"] == 350
    assert [ln["productCode"] for ln in fixture.body["lines"]] == ["PRD-ZZ", "PRD-AA"], (
        "the lines must be sent in the order given"
    )
    assert fixture.body["lines"][0] == {"productCode": "PRD-ZZ", "units": 3, "unitPrice": 1999}


def test_the_issue_fixture_refuses_coinciding_or_zero_totals_unless_told() -> None:
    builder = build()
    refused: dict[str, tuple[list[tuple[str, int, int]], int]] = {
        "a zero discount": (LINES, 0),
        "a zero total": (LINES, 8465),
        "lines that sum to zero": ([("PRD-AA", 2, 0)], 0),
        "a discount contained in the amount": ([("PRD-AA", 1, 8465)], 46),
        "a discount equal to the total": ([("PRD-AA", 1, 700)], 350),
        "a total contained in the amount": ([("PRD-AA", 1, 81150)], 73035),
    }
    for label, (lines, discount) in refused.items():
        try:
            builder(lines, discount, **ORDER)
        except AssertionError as error:
            refusal = str(error)
        else:
            pytest.fail(f"BI38: the fixture builder accepted {label}")
        assert "fixture refused" in refusal, f"{label}: refused for another reason: {refusal}"

    # the controls: the same helper lets the deliberate zeros through
    zero_discount = builder(LINES, 0, **ORDER, zero_discount_on_purpose=True)
    assert (zero_discount.discount, zero_discount.total) == (0, 8465)
    zero_total = builder(LINES, 8465, **ORDER, zero_total_on_purpose=True)
    assert (zero_total.total, zero_total.discount) == (0, 8465)
    # a flag does not excuse a figure that is not zero
    with pytest.raises(AssertionError, match="fixture refused"):
        builder(LINES, 350, **ORDER, zero_discount_on_purpose=True)
    with pytest.raises(AssertionError, match="fixture refused"):
        builder(LINES, 350, **ORDER, zero_total_on_purpose=True)
