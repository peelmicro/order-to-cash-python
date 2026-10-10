"""The integration request helper refuses a hold amount ending in 99 unless it is told the `.99`
rule is the point of the test (task H1; #7 `cents-rule-fixture-guard.ts`, #8
`CentsRuleFixtureGuard.cs`). Feature 20's simulator refuses such amounts, so a feature-19 fixture
that used one would change meaning silently.

The helper lives in the integration conftest; a conftest is not importable by name under
`--import-mode=importlib`, so the module is loaded from its path, and the function tested is the
very one the `rpc` fixture calls.

Loop scope: nothing here is async.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

CONFTEST = Path(__file__).resolve().parents[1] / "integration" / "conftest.py"


def _conftest() -> ModuleType:
    spec = importlib.util.spec_from_file_location("billing_integration_conftest", CONFTEST)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hold(amount: int) -> dict[str, object]:
    return {
        "orderReference": "ORD-000101",
        "retailerCode": "RETAIL-77",
        "companyCode": "SUPPLY-CO",
        "amount": {"amount": amount, "currency": "EUR"},
    }


def test_the_request_helper_refuses_an_amount_ending_in_99_unless_allowed() -> None:
    refuse = _conftest().refuse_cents_rule
    for refused in (99, 199, 4299, 100_099):
        with pytest.raises(AssertionError, match="ends in 99"):
            refuse("billing.credit.hold", _hold(refused), allow_cents_rule=False)
    # the control rows: the same helper lets every other amount through, and the allowed 99
    for accepted in (0, 98, 100, 4200, 4210):
        refuse("billing.credit.hold", _hold(accepted), allow_cents_rule=False)
    refuse("billing.credit.hold", _hold(4299), allow_cents_rule=True)
    # only a hold carries an amount the rule reads
    refuse("billing.credit.release", {"orderReference": "ORD-000101"}, allow_cents_rule=False)
