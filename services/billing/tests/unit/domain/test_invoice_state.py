"""`InvoiceState`: the closed pair `Issued | Paid(paid_at)` (task B2, B3; BI23, BI27).

Pure; nothing async. The type-checker half runs a real `mypy --strict` subprocess over a fixture
module (the shape of `packages/shared_kernel/tests/test_mypy_rejects_float.py`), with a control that
proves the checker is not simply failing on everything.
"""

import dataclasses
import subprocess
import sys
import typing
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from functools import partial
from pathlib import Path

import pytest

from otc_billing.domain.invoice_errors import (
    InvalidInvoiceSnapshotError,
    InvalidInvoiceStateError,
    UnknownInvoiceStatusError,
)
from otc_billing.domain.invoice_state import (
    InvoiceState,
    InvoiceStatus,
    Issued,
    Paid,
    paid_at_of,
    parse_invoice_state,
    state_token,
)

PAID_AT = datetime(2026, 10, 9, 10, 15, 30, 123000, tzinfo=UTC)

REPO_SRC = [
    Path(__file__).resolve().parents[5] / "packages" / "shared_kernel" / "src",
    Path(__file__).resolve().parents[3] / "src",
]


def outcome(call: Callable[[], object]) -> Exception | None:
    """The exception a call raised, or None: lets a test say which claim failed."""
    try:
        call()
    except Exception as error:
        return error
    return None


def test_bi23_the_state_is_exactly_issued_or_paid_and_paid_cannot_exist_without_an_aware_instant() -> (  # noqa: E501
    None
):
    # the alias names EXACTLY these two classes, in this order
    assert typing.get_args(InvoiceState.__value__) == (Issued, Paid), (
        "BI23: the InvoiceState alias must name exactly (Issued, Paid)"
    )
    for case in (Issued, Paid):
        assert dataclasses.is_dataclass(case)
        assert hasattr(case, "__slots__"), f"BI23: {case.__name__} is not slotted"
        # final: a subclass would be a third case that `match` and `assert_never` never see
        with pytest.raises(TypeError, match="is final"):
            type("Voided", (case,), {})
    with pytest.raises(dataclasses.FrozenInstanceError):
        Paid(PAID_AT).paid_at = PAID_AT + timedelta(seconds=1)  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        Issued().anything = 1  # type: ignore[attr-defined]

    # `paid` cannot exist without an aware instant: three values that are not one
    naive = datetime(2026, 10, 9, 10, 15, 30)
    bad: list[object] = [None, "2026-10-09", naive]
    for offending in bad:
        with pytest.raises(InvalidInvoiceStateError) as caught:
            Paid(offending)  # type: ignore[arg-type]
        assert caught.value.code == "invoice_state.invalid_paid_at"
    # controls: an aware instant in UTC and in another zone are accepted
    assert Paid(PAID_AT).paid_at == PAID_AT
    assert Paid(PAID_AT.astimezone(timezone(timedelta(hours=2)))).paid_at == PAID_AT


_FIXTURE_HEAD = """\
from typing import assert_never

from otc_billing.domain.invoice_state import InvoiceState, Issued, Paid


"""

_COMPLETE = (
    _FIXTURE_HEAD
    + """\
def describe(state: InvoiceState) -> str:
    match state:
        case Issued():
            return "issued"
        case Paid():
            return "paid"
        case _:
            assert_never(state)
"""
)

_OMITS_PAID = (
    _FIXTURE_HEAD
    + """\
def describe(state: InvoiceState) -> str:
    match state:
        case Issued():
            return "issued"
        case _:
            assert_never(state)
"""
)


def _mypy(tmp_path: Path, source: str) -> tuple[int, str]:
    module = tmp_path / "snippet.py"
    module.write_text(source)
    config = tmp_path / "mypy.ini"
    config.write_text(
        "[mypy]\nstrict = True\nexplicit_package_bases = True\nnamespace_packages = True\n"
        f"mypy_path = {':'.join(str(p) for p in REPO_SRC)}\n"
        "[mypy-aiokafka.*]\nignore_missing_imports = True\n"
    )
    completed = subprocess.run(  # noqa: S603 - fixed argv: this interpreter running mypy
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(config),
            "--cache-dir",
            str(tmp_path / ".mypy_cache"),
            str(module),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    return completed.returncode, completed.stdout + completed.stderr


def test_bi23_mypy_rejects_a_match_that_omits_a_case(tmp_path: Path) -> None:
    (tmp_path / "control").mkdir()
    (tmp_path / "omits").mkdir()
    code, output = _mypy(tmp_path / "control", _COMPLETE)
    assert code == 0, f"BI23 control: a complete match was rejected by mypy --strict:\n{output}"
    code, output = _mypy(tmp_path / "omits", _OMITS_PAID)
    assert code != 0, "BI23: mypy --strict accepted a match over InvoiceState that omits `Paid`"
    assert "assert_never" in output, f"BI23: mypy failed for another reason:\n{output}"


def test_bi27_the_status_token_parse_is_exact_and_closed_and_only_lower_case_tokens_are_written() -> (  # noqa: E501
    None
):
    tokens: list[object] = ["Paid", " paid", "settled", "", 1, None, "ISSUED", "paid\n", "Issued "]
    for token in tokens:
        for paid_at in (None, PAID_AT):
            error = outcome(partial(parse_invoice_state, token, paid_at))
            assert isinstance(error, UnknownInvoiceStatusError), (
                f"BI27: the unknown token {token!r} (paid_at {paid_at!r}) was not refused as "
                f"unknown: {error!r}"
            )
            assert error.code == "invoice_status.unknown"

    # a str subclass is refused too: the parse is `type(token) is str`
    class Loud(str):
        __slots__ = ()

    with pytest.raises(UnknownInvoiceStatusError):
        parse_invoice_state(Loud("paid"), PAID_AT)

    # the two agreeing pairs
    assert parse_invoice_state("issued", None) == Issued()
    assert parse_invoice_state("paid", PAID_AT) == Paid(PAID_AT)
    # the two disagreeing pairs, and a paid_at that is not an aware instant (BI10's parse half)
    naive = datetime(2026, 10, 9, 10, 15, 30)
    pairs: list[tuple[object, object]] = [
        ("paid", None),
        ("issued", PAID_AT),
        ("paid", "2026-10-09"),
        ("paid", naive),
    ]
    for token, stored in pairs:
        with pytest.raises(InvalidInvoiceSnapshotError) as refused:
            parse_invoice_state(token, stored, invoice_reference="INV-000777")
        assert refused.value.code == "invoice.invalid_snapshot", f"{token!r} / {stored!r}"
        assert "INV-000777" in refused.value.message, "BI10: the error does not name the invoice"

    # only the lower-case contract tokens are written, from the one state
    assert state_token(Issued()) is InvoiceStatus.ISSUED
    assert state_token(Issued()).value == "issued"
    assert state_token(Paid(PAID_AT)) is InvoiceStatus.PAID
    assert state_token(Paid(PAID_AT)).value == "paid"
    assert paid_at_of(Issued()) is None
    assert paid_at_of(Paid(PAID_AT)) == PAID_AT
