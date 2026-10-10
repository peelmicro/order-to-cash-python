"""`CREDIT_FAILURE_RATE` (R43) read through pydantic-settings: the default and the boot refusal.

The value is parsed by hand-written rules because what `float()` and pydantic accept is wider than
"a number in the closed interval [0, 1]" (measured on this machine: `nan`, `inf`, `infinity`,
`1_0` -> 10.0, an Arabic-Indic `0.5` all parse). The population of values is a literal in each
parametrisation; every refusal asserts the variable AND the offending value are named.

Loop scope: nothing here is async.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from otc_billing.composition import load_settings


@pytest.fixture
def clean_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    monkeypatch.chdir(tmp_path)  # no `.env` of a developer can supply a value
    monkeypatch.delenv("CREDIT_FAILURE_RATE", raising=False)
    monkeypatch.setenv("POSTGRES_APP_PASSWORD", "baseline-password")
    return monkeypatch


def test_r43_an_absent_rate_defaults_to_zero(clean_environment: pytest.MonkeyPatch) -> None:
    assert load_settings().credit_simulator.failure_rate == 0


def test_r43_an_empty_rate_means_zero_as_absent_does(clean_environment: pytest.MonkeyPatch) -> None:
    clean_environment.setenv("CREDIT_FAILURE_RATE", "")
    assert load_settings().credit_simulator.failure_rate == 0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0", 0.0),
        ("1", 1.0),
        ("0.25", 0.25),
        (".5", 0.5),
        ("1.", 1.0),
        (" 0.5 ", 0.5),
        ("0.5\n", 0.5),
        ("1e-1", 0.1),
        ("1e0", 1.0),
        ("+0.5", 0.5),
        ("0e5", 0.0),
    ],
)
def test_r43_a_number_in_the_closed_interval_is_accepted(
    clean_environment: pytest.MonkeyPatch, raw: str, expected: float
) -> None:
    clean_environment.setenv("CREDIT_FAILURE_RATE", raw)
    assert load_settings().credit_simulator.failure_rate == expected


@pytest.mark.parametrize(
    "raw",
    [
        "1.5",
        "-0.1",
        "1.0000001",
        "1e1",
        "abc",
        "true",
        "0x1",
        "1,000",
        "  ",
        "nan",
        "NaN",
        "inf",
        "-inf",
        "Infinity",
        "infinity",
        "1_0",
        "0_5",
        "\N{ARABIC-INDIC DIGIT ZERO}.\N{ARABIC-INDIC DIGIT FIVE}",  # float() reads this as 0.5
        "0.5.5",
        "--0.5",
    ],
)
def test_r43_anything_but_a_finite_number_in_the_closed_interval_fails_naming_variable_and_value(
    clean_environment: pytest.MonkeyPatch, raw: str
) -> None:
    clean_environment.setenv("CREDIT_FAILURE_RATE", raw)

    try:
        load_settings()
    except ValidationError as error:
        # the validator's OWN message: `str(error)` also echoes `input_value=...` and would
        # name the value even if the message did not (armed: A12)
        message = " ".join(str(e["msg"]) for e in error.errors())
    else:
        pytest.fail(
            f"R43: CREDIT_FAILURE_RATE={raw!r} was accepted: the service would boot with it"
        )
    assert "CREDIT_FAILURE_RATE" in message, "the failure does not name the variable"
    assert repr(raw) in message, f"the failure does not report the offending value {raw!r}"
