"""The literal ISO 4217 exponent table (SA-5) and its JSON export for the web."""

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from otc_shared_kernel import DEFAULT_EXPONENT, NON_DEFAULT_EXPONENTS, exponent_of

REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_JSON = REPO_ROOT / "apps" / "web" / "src" / "lib" / "currency-exponents.json"


def load_unique_keys(text: str) -> dict[str, Any]:
    """`json.loads` keeps the LAST of two equal keys silently; a duplicate is a divergence."""

    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in pairs]
        duplicated = sorted({key for key in keys if keys.count(key) > 1})
        assert not duplicated, f"duplicate keys in the JSON export: {duplicated}"
        return dict(pairs)

    loaded = json.loads(text, object_pairs_hook=no_duplicates)
    assert isinstance(loaded, dict)
    return loaded


def divergences(python_table: Mapping[str, int], web_table: Mapping[str, Any]) -> list[str]:
    """Every way the two tables differ, in BOTH directions, each naming the code."""
    problems = [
        f"{code}: in Python, missing from the JSON"
        for code in python_table.keys() - web_table.keys()
    ]
    problems += [
        f"{code}: in the JSON, missing from Python"
        for code in web_table.keys() - python_table.keys()
    ]
    for code in python_table.keys() & web_table.keys():
        if type(web_table[code]) is not int or web_table[code] != python_table[code]:
            problems.append(
                f"{code}: Python says {python_table[code]}, the JSON says {web_table[code]!r}"
            )
    return sorted(problems)


# SA-5 examples and the three non-2 exponent bands, as literals.
@pytest.mark.parametrize(
    ("code", "exponent"),
    [
        ("EUR", 2),
        ("GBP", 2),
        ("USD", 2),
        ("JPY", 0),
        ("BHD", 3),
        ("CLF", 4),
        ("UYI", 0),
        ("ZZZ", 2),
    ],
)
def test_the_sa5_exponents(code: str, exponent: int) -> None:
    assert exponent_of(code) == exponent


def test_the_table_is_the_literal_twenty_six_entries_and_never_lists_the_default() -> None:
    assert len(NON_DEFAULT_EXPONENTS) == 26
    assert DEFAULT_EXPONENT == 2
    assert all(re.fullmatch(r"[A-Z]{3}", code) for code in NON_DEFAULT_EXPONENTS)
    assert all(
        type(value) is int and value != DEFAULT_EXPONENT for value in NON_DEFAULT_EXPONENTS.values()
    )
    assert set(NON_DEFAULT_EXPONENTS.values()) == {0, 3, 4}
    for code, exponent in NON_DEFAULT_EXPONENTS.items():
        assert exponent_of(code) == exponent


def test_the_table_is_read_only() -> None:
    table: Any = NON_DEFAULT_EXPONENTS
    with pytest.raises(TypeError):
        table["EUR"] = 9
    with pytest.raises(TypeError):
        del table["JPY"]


def test_the_json_export_for_the_web_equals_the_python_table_in_both_directions() -> None:
    web = load_unique_keys(WEB_JSON.read_text(encoding="utf-8"))
    assert web, "the JSON export is empty: the parity check would be vacuous"
    assert divergences(NON_DEFAULT_EXPONENTS, web) == []


# --- the instrument itself: each divergence shape MUST be reported -----------------------------


def test_parity_reports_an_entry_missing_from_the_json() -> None:
    web = dict(NON_DEFAULT_EXPONENTS)
    del web["BHD"]
    assert divergences(NON_DEFAULT_EXPONENTS, web) == ["BHD: in Python, missing from the JSON"]


def test_parity_reports_an_entry_missing_from_python() -> None:
    web = {**NON_DEFAULT_EXPONENTS, "XYZ": 3}
    assert divergences(NON_DEFAULT_EXPONENTS, web) == ["XYZ: in the JSON, missing from Python"]


def test_parity_reports_a_changed_exponent_and_a_non_int_exponent() -> None:
    changed = {**NON_DEFAULT_EXPONENTS, "JPY": 2}
    assert divergences(NON_DEFAULT_EXPONENTS, changed) == ["JPY: Python says 0, the JSON says 2"]
    stringly = {**NON_DEFAULT_EXPONENTS, "JPY": "0"}
    assert divergences(NON_DEFAULT_EXPONENTS, stringly) == ["JPY: Python says 0, the JSON says '0'"]
    boolean = {**NON_DEFAULT_EXPONENTS, "JPY": False}
    assert divergences(NON_DEFAULT_EXPONENTS, boolean) == [
        "JPY: Python says 0, the JSON says False"
    ]


def test_parity_loader_refuses_a_duplicate_key() -> None:
    with pytest.raises(AssertionError, match=r"duplicate keys.*JPY"):
        load_unique_keys('{"JPY": 0, "JPY": 2}')
