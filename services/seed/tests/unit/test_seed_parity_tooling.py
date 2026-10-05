"""`scripts/seed_parity.py`: the literal subset, the normalisers, the sqlcmd parser and the diff.

R-map (feature_list.json id 12, acceptance 5: "parity against #8's live databases by dumping rows to
files and diffing them, seeded subset isolated first"). The live run against #8 is not part of this
feature's tests; what is tested here is the instrument, because "when a diff says identical" is only
worth something if the instrument is known to say "different" (sentinels below).
"""

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID

import pytest

from otc_seed.application import default_dataset
from otc_seed.domain.deterministic import deterministic_id

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "seed_parity.py"


@pytest.fixture(scope="module")
def parity() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed_parity", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_parity"] = module
    spec.loader.exec_module(module)
    return module


def test_the_literal_keys_are_the_seeded_population(parity: Any) -> None:
    """The literals are typed in the script; THIS test (not the script) checks them against the
    seed's dataset, so a typo in a literal fails here by name."""
    data = default_dataset()
    assert [s.order_reference for s in data.sagas] == parity.ORDER_REFERENCES
    assert [s.order_id for s in data.sagas] == parity.ORDER_IDS
    assert [deterministic_id(f"order:{n}") for n in range(1, 7)] == parity.ORDER_IDS
    assert [c.code for c in data.currencies] == parity.CURRENCY_CODES
    assert [p.code for p in data.products] == parity.PRODUCT_CODES
    assert [r.code for r in data.retailers] == parity.RETAILER_CODES
    assert sorted(c.code for c in data.companies) == sorted(parity.COMPANY_CODES)
    assert len(set(parity.COMPANY_CODES)) == 22
    assert [c.code for c in data.credits] == parity.CREDIT_CODES
    assert {(s.company_code, s.product_code) for s in data.stock} == parity.STOCK_PAIRS
    assert len(parity.STOCK_PAIRS) == 215
    assert len(parity.SAGA_STOCK_PAIRS) == 11


def test_the_expected_counts_are_the_literal_row_counts_of_the_dataset(parity: Any) -> None:
    assert {(s.database, s.table.name): s.expected for s in parity.SPECS} == {
        ("orders", "currencies"): 3,
        ("orders", "products"): 12,
        ("orders", "retailers"): 7,
        ("orders", "companies"): 22,
        ("orders", "orders"): 6,
        ("orders", "order_items"): 11,
        ("orders", "outbox"): 17,
        ("fulfillment", "stock"): 215,
        ("fulfillment", "reservations"): 11,
        ("fulfillment", "despatches"): 5,
        ("fulfillment", "despatch_items"): 10,
        ("fulfillment", "outbox"): 12,
        ("billing", "credits"): 154,
        ("billing", "credit_items"): 15,
        ("billing", "invoices"): 5,
        ("billing", "invoice_items"): 10,
        ("billing", "payments"): 5,
        ("billing", "outbox"): 21,
    }


def test_the_select_is_client_side_rows_never_an_aggregate(parity: Any) -> None:
    for spec in parity.SPECS:
        sql = parity.select_sql(spec).upper()
        for banned in ("STRING_AGG", "GROUP_CONCAT", "HASHBYTES", "CHECKSUM", "MD5(", "COUNT("):
            assert banned not in sql, (spec.table.name, banned)
        assert sql.startswith("SELECT T.")
        assert "SEQ" not in sql.replace("SEQUENCE", "")  # the identity column is omitted


def test_an_instant_normalises_alike_from_tsql_text_and_from_a_postgres_datetime(
    parity: Any,
) -> None:
    column = parity.tables.ORDERS.c.order_date
    from_tsql = parity.normalise(column, "2026-06-01 09:00:00.000")
    from_pg = parity.normalise(column, datetime(2026, 6, 1, 9, 0, 0, tzinfo=UTC))
    assert from_tsql == from_pg == "2026-06-01T09:00:00.000Z"
    assert parity.normalise(column, "2026-06-02 09:00:10.123") == "2026-06-02T09:00:10.123Z"


def test_a_uuid_is_lower_cased_and_money_is_an_int(parity: Any) -> None:
    uuid_column = parity.tables.ORDERS.c.id
    upper = "1741D5AA-CFBA-4205-A1C0-82E7A5CB8984"
    assert parity.normalise(uuid_column, upper) == "1741d5aa-cfba-4205-a1c0-82e7a5cb8984"
    assert parity.normalise(uuid_column, UUID(upper)) == "1741d5aa-cfba-4205-a1c0-82e7a5cb8984"
    money = parity.tables.ORDERS.c.total_amount
    assert parity.normalise(money, "16130") == parity.normalise(money, 16130) == 16130
    assert type(parity.normalise(money, "16130")) is int


def test_null_is_none_only_for_a_nullable_column(parity: Any) -> None:
    nullable = parity.tables.ORDERS.c.cancellation_reason
    required = parity.tables.ORDERS.c.status
    assert parity.normalise(nullable, "NULL") is None
    assert parity.normalise(nullable, None) is None
    assert parity.normalise(required, "NULL") == "NULL"  # a real value of a NOT NULL column


def test_a_json_payload_is_canonical_whatever_its_key_order_or_spacing(parity: Any) -> None:
    column = parity.tables.ORDERS_OUTBOX.c.payload
    a = parity.normalise(column, '{"b": 1, "a": {"y": 2, "x": "España"}}')
    b = parity.normalise(column, '{"a":{"x":"España","y":2},"b":1}')
    assert a == b == {"a": {"x": "España", "y": 2}, "b": 1}
    spec = next(s for s in parity.SPECS if s.table.name == "outbox" and s.database == "orders")
    line_a = parity.render(spec, _outbox_row(a))
    assert '"payload":{"a":{"x":"España","y":2},"b":1}' in line_a


def test_sqlcmd_output_is_parsed_with_utf8_text_nulls_and_blank_lines(parity: Any) -> None:
    sep = parity.SEPARATOR
    printed = (
        f"AldiEs{sep}Aldi España{sep}NULL{sep}5400000000058\r\n"
        "\r\n"
        f"CarrefourEs{sep}Carrefour España{sep}x{sep}5400000000010\n"
    )
    rows = parity.parse_sqlcmd(printed, 4)
    assert rows == [
        ["AldiEs", "Aldi España", "NULL", "5400000000058"],
        ["CarrefourEs", "Carrefour España", "x", "5400000000010"],
    ]
    assert "?" not in rows[0][1]  # #8's non-UTF-8 client printed `Aldi Espa?a`


def test_a_line_with_the_wrong_number_of_fields_is_an_error_not_a_guess(parity: Any) -> None:
    sep = parity.SEPARATOR
    with pytest.raises(ValueError, match="expected 3"):
        parity.parse_sqlcmd(f"a{sep}b\n", 3)


def _outbox_row(payload: dict[str, Any]) -> list[Any]:
    """A full outbox row in column order (ids, type, payload, instants), for `render`."""
    uid = "00000000-0000-4000-8000-000000000001"
    at = "2026-06-01 09:00:00.000"
    return [uid, uid, "order.placed.v1", uid, uid, uid, payload, at, at, at, None]


def _write(directory: Path, name: str, lines: list[str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def test_the_diff_reports_identical_files_and_exits_clean(parity: Any, tmp_path: Path) -> None:
    for side in ("l", "r"):
        _write(tmp_path / side, "orders.currencies.jsonl", ['{"a":1}', '{"a":2}'])
    identical, report = parity.diff_dirs(tmp_path / "l", tmp_path / "r")
    assert identical is True
    assert report == ["orders.currencies.jsonl: 2 rows identical"]


@pytest.mark.parametrize(
    "right",
    [
        ['{"a":1}', '{"a":3}'],  # one value differs
        ['{"a":1}'],  # a row missing
        ['{"a":1}', '{"a":2}', '{"a":2}'],  # a duplicate row
    ],
)
def test_the_diff_sees_a_changed_a_missing_and_a_duplicated_row(
    parity: Any, tmp_path: Path, right: list[str]
) -> None:
    """Sentinels: the instrument must say DIFFERENT, or its 'identical' proves nothing."""
    _write(tmp_path / "l", "orders.currencies.jsonl", ['{"a":1}', '{"a":2}'])
    _write(tmp_path / "r", "orders.currencies.jsonl", right)
    identical, report = parity.diff_dirs(tmp_path / "l", tmp_path / "r")
    assert identical is False
    assert "DIFFERENT" in report[0]


def test_the_diff_sees_a_file_present_on_one_side_only_and_an_empty_pair_of_directories(
    parity: Any, tmp_path: Path
) -> None:
    _write(tmp_path / "l", "a.jsonl", ["{}"])
    _write(tmp_path / "r", "b.jsonl", ["{}"])
    identical, report = parity.diff_dirs(tmp_path / "l", tmp_path / "r")
    assert identical is False
    assert report == ["a.jsonl: only in left", "b.jsonl: only in right"]
    (tmp_path / "e1").mkdir()
    (tmp_path / "e2").mkdir()
    assert parity.diff_dirs(tmp_path / "e1", tmp_path / "e2")[0] is False  # vacuous is not "same"


def test_a_dump_with_a_missing_literal_key_or_the_wrong_row_count_fails(parity: Any) -> None:
    currencies = next(s for s in parity.SPECS if s.table.name == "currencies")
    rows = [{"code": "USD"}, {"code": "EUR"}]
    with pytest.raises(SystemExit, match="literal keys missing"):
        parity.check_subset(currencies, rows)
    orders = next(s for s in parity.SPECS if s.table.name == "orders" and s.database == "orders")
    refs = [{"order_reference": r} for r in parity.ORDER_REFERENCES]
    parity.check_subset(orders, refs)
    with pytest.raises(SystemExit, match="expected 6 seeded rows, found 7"):
        parity.check_subset(orders, [*refs, {"order_reference": "ORD-000007"}])


# ---- round 2: the sqlcmd argv (B1) and the live-mutable stock section (N4)
def test_the_sqlcmd_argv_never_pairs_dash_y_zero_with_dash_w_or_dash_h(parity: Any) -> None:
    """B1: sqlcmd rejects `-y 0` with `-W` or `-h` before connecting, and dropping `-y 0` truncates
    `nvarchar(max)` at 256. The live probe is in progress/impl_seed_job.md (Round 2); this pins
    the argv it proved."""
    argv = parity.sqlcmd_argv("c", "u", "p", "d", "SELECT 1")
    assert "-y" in argv
    assert argv[argv.index("-y") + 1] == "0"
    assert "-W" not in argv
    assert "-h" not in argv
    assert argv[argv.index("-f") + 1] == "65001"


def _stock_spec(parity: Any) -> Any:
    return next(s for s in parity.SPECS if s.table.name == "stock")


def _stock_row(spec: Any, **changes: Any) -> list[Any]:
    base: dict[str, Any] = {
        "id": UUID("11111111-1111-4111-8111-111111111111"),
        "company_code": "IBERFOODS",
        "product_code": "PRD-0001",
        "units": 500,
        "reserved_units": 0,
        "low_stock_threshold": 20,
        "created_at": datetime(2026, 6, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 1, tzinfo=UTC),
    }
    base.update(changes)
    return [base[c.name] for c in spec.table.columns]


def test_stock_live_columns_are_in_the_live_section_and_not_in_the_failing_file(
    parity: Any,
) -> None:
    spec = _stock_spec(parity)
    assert set(spec.live_columns) == {"units", "reserved_units", "updated_at"}
    row = _stock_row(spec)
    immutable = json.loads(parity.render(spec, row))
    live = json.loads(parity.render_live(spec, row))
    assert set(immutable) == {
        "id",
        "company_code",
        "product_code",
        "low_stock_threshold",
        "created_at",
    }
    assert set(live) == {
        "id",
        "company_code",
        "product_code",
        "units",
        "reserved_units",
        "updated_at",
    }


def test_a_live_stock_difference_is_reported_but_never_fails_and_an_immutable_one_does(
    parity: Any, tmp_path: Path
) -> None:
    spec = _stock_spec(parity)
    rows = {
        "mutated": _stock_row(spec, units=480, reserved_units=20),
        "threshold": _stock_row(spec, low_stock_threshold=21),
        "same": _stock_row(spec),
    }
    for side, key in (("l", "same"), ("r", "mutated")):
        _write(tmp_path / side, "fulfillment.stock.jsonl", [parity.render(spec, rows[key])])
        _write(
            tmp_path / side, "fulfillment.stock.live.jsonl", [parity.render_live(spec, rows[key])]
        )
    identical, report = parity.diff_dirs(tmp_path / "l", tmp_path / "r")
    assert identical is True
    assert any("LIVE-STATE DIFFERENCE" in line for line in report)
    assert "fulfillment.stock.jsonl: 1 rows identical" in report
    # the same instrument fails when a seed-immutable column differs
    _write(tmp_path / "r", "fulfillment.stock.jsonl", [parity.render(spec, rows["threshold"])])
    identical, report = parity.diff_dirs(tmp_path / "l", tmp_path / "r")
    assert identical is False
    assert any(line.startswith("fulfillment.stock.jsonl: DIFFERENT") for line in report)


def test_the_live_file_missing_on_one_side_still_fails(parity: Any, tmp_path: Path) -> None:
    _write(tmp_path / "l", "fulfillment.stock.live.jsonl", ["{}"])
    _write(tmp_path / "r", "other.jsonl", ["{}"])
    assert parity.diff_dirs(tmp_path / "l", tmp_path / "r")[0] is False
