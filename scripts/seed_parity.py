"""Parity of the SEEDED subset: #8's live databases against #9's, row per line, to files, diffed.

    uv run python scripts/seed_parity.py dump9 OUT9      # #9: PostgreSQL + MongoDB (the dev stack)
    uv run python scripts/seed_parity.py dump8 OUT8      # #8: MS-SQL (docker exec sqlcmd) + MongoDB
    uv run python scripts/seed_parity.py diff OUT8 OUT9  # exit 0 only if every file is identical

What it compares. Only the rows the seed made: #7's live database held 1 390 orders of which the
seed made 6, so a whole-table dump would compare live traffic. The subset is defined by the LITERAL
key lists below (`KEYS`: the constants from `ORDER_REFERENCES` to `STOCK_PAIRS`), typed here, never
derived from either database or from the seed: the six order references and their order ids, the 22
company, 7 retailer, 3 currency and 12 product codes, credit codes `CR-000001..CR-000154`, and the
215 stock `(company, product)` pairs written as the 11 pairs the sagas touch plus the 17 baseline
companies x 12 products. A table is selected with ONE SQL text that runs unchanged on PostgreSQL and
on T-SQL; stock is selected by a superset (company and product IN lists) and reduced to the literal
pairs in Python, and every dump FAILS if a literal key is missing or the row count is not the
literal one, so a vacuous or truncated dump cannot pass.

Live state. `stock.units`, `stock.reserved_units` and `stock.updated_at` are changed by live traffic
(and by #8's re-run, which re-applies every column), so they are NOT in `fulfillment.stock.jsonl`:
that file holds the seed-immutable columns and fails the diff on any difference. The live columns
go to `fulfillment.stock.live.jsonl`, which the diff reports but never fails on. The orders subset
(terminal orders) needs no such section.

What it writes. One file per table (`<database>.<table>.jsonl`) and `mongo.order_timeline.jsonl`:
one row per line, a JSON object with sorted keys, compact separators, non-ASCII written raw, the
file encoded UTF-8 (never the console's code page: #8 printed `Aldi Espa?a`), lines sorted so row
order is not a claim. Normalised: uuid lower-case; instants `YYYY-MM-DDTHH:MM:SS.mmmZ` (T-SQL's
`2026-06-01 09:00:00.000` and PostgreSQL's aware datetimes alike); money and quantities `int`;
`json` payloads parsed and re-written canonically (key order is never a parity claim); `outbox.seq`
omitted (a database-assigned identity). Rows are read CLIENT-side and never aggregated or hashed on
the server (#8: `STRING_AGG` truncated, `GROUP_CONCAT` cut at 1 024 bytes).

#8's half needs #8's `otcnet-mssql` and `otcnet-mongodb` running (`MONGO_HOST_PORT=27018` avoids
stopping `otcpy-mongodb`) and talks to MS-SQL through `docker exec ... sqlcmd -y 0` (see
`sqlcmd_argv` for why those flags), so no ODBC driver is added to this workspace. It reads
`MSSQL_APP_PASSWORD` (no default) and `EIGHT_MONGO_URI`; the #9 half reads `.env` through the
seed's own `SeedSettings`.
"""

import argparse
import asyncio
import difflib
import json
import os
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
from pymongo import AsyncMongoClient
from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import TIMESTAMP as PG_TIMESTAMP
from sqlalchemy.types import BigInteger, Integer, SmallInteger

from otc_seed.infrastructure import tables
from otc_seed.infrastructure.raw_json import RawJson
from otc_seed.infrastructure.settings import SeedSettings

# ---------------------------------------------------------------- the literal subset
ORDER_REFERENCES = [f"ORD-{n:06d}" for n in range(1, 7)]
ORDER_IDS = [
    "1741d5aa-cfba-4205-a1c0-82e7a5cb8984",
    "cf826257-6521-4471-9292-d5a81919eba6",
    "321abe6d-ee7b-465f-86d7-d65d6707d131",
    "d69b8a2a-b0c8-47d5-bf66-82720335518c",
    "6baf7a6d-aeff-46af-a629-8abe050c8699",
    "d8324836-41a0-44ab-8128-75b63039eda2",
]
CURRENCY_CODES = ["USD", "EUR", "GBP"]
PRODUCT_CODES = [f"PRD-{n:04d}" for n in range(1, 13)]
RETAILER_CODES = [
    "CarrefourEs",
    "CarrefourFr",
    "LeroyMerlinEs",
    "LeroyMerlinFr",
    "AldiEs",
    "AldiDe",
    "AldiGb",
]
SAGA_COMPANIES = ["IBERFOODS", "FRESHFR", "TOOLIBERIA", "GERMANFOODS", "UKDISTRIB"]
BASELINE_COMPANIES = [
    "SPANATURAL",
    "MEDFRESH",
    "OUTILFRANCE",
    "GALLIAGOODS",
    "BAUWERK",
    "RHEINGOODS",
    "LONDONTOOLS",
    "ALBIONFOODS",
    "ITALPASTA",
    "ROMATOOLS",
    "MILANOGOODS",
    "LUSOFOODS",
    "PORTOTOOLS",
    "DUTCHGOODS",
    "HOLLANDTOOLS",
    "BENELUXFOODS",
    "BRUSSELSTOOLS",
]
COMPANY_CODES = SAGA_COMPANIES + BASELINE_COMPANIES
CREDIT_CODES = [f"CR-{n:06d}" for n in range(1, 155)]
# the (company, product) pairs the six sagas reserve against
SAGA_STOCK_PAIRS = [
    ("IBERFOODS", "PRD-0001"),
    ("IBERFOODS", "PRD-0002"),
    ("IBERFOODS", "PRD-0003"),
    ("FRESHFR", "PRD-0002"),
    ("FRESHFR", "PRD-0008"),
    ("TOOLIBERIA", "PRD-0004"),
    ("TOOLIBERIA", "PRD-0005"),
    ("GERMANFOODS", "PRD-0002"),
    ("GERMANFOODS", "PRD-0003"),
    ("UKDISTRIB", "PRD-0009"),
    ("UKDISTRIB", "PRD-0010"),
]
STOCK_PAIRS = set(SAGA_STOCK_PAIRS) | {(c, p) for c in BASELINE_COMPANIES for p in PRODUCT_CODES}


def _in(values: Iterable[str]) -> str:
    # The values are the constants above (ASCII codes and uuids): no quoting is ever needed.
    return ", ".join(f"'{v}'" for v in values)


@dataclass(frozen=True)
class Spec:
    database: str  # orders | fulfillment | billing
    table: Table
    alias: str
    source: str  # FROM clause
    where: str
    expected: int  # the literal count of the subset
    keys: tuple[str, ...] = ()  # when set: the expected values of this column (found == expected)
    key_column: str = ""
    # Columns that live traffic changes (and that #8's resetting re-run rewrites): compared in a
    # separate, informational `<name>.live.jsonl` section, never as a parity failure.
    live_columns: tuple[str, ...] = ()


# stock is LIVE state on a running stack: reservations move `units`/`reserved_units`, and #8's
# re-run restocks them (its upsert re-applies every column), so a difference there is not a seed
# difference. The seed-immutable columns (id, codes, threshold, created_at) still fail the diff.
STOCK_LIVE_COLUMNS = ("units", "reserved_units", "updated_at")
LIVE_SUFFIX = ".live.jsonl"
LIVE_IDENTITY = ("id", "company_code", "product_code")


def _specs() -> list[Spec]:
    refs, ids = _in(ORDER_REFERENCES), _in(ORDER_IDS)
    return [
        Spec(
            "orders",
            tables.CURRENCIES,
            "t",
            "currencies t",
            f"t.code IN ({_in(CURRENCY_CODES)})",
            3,
            tuple(CURRENCY_CODES),
            "code",
        ),
        Spec(
            "orders",
            tables.PRODUCTS,
            "t",
            "products t",
            f"t.code IN ({_in(PRODUCT_CODES)})",
            12,
            tuple(PRODUCT_CODES),
            "code",
        ),
        Spec(
            "orders",
            tables.RETAILERS,
            "t",
            "retailers t",
            f"t.code IN ({_in(RETAILER_CODES)})",
            7,
            tuple(RETAILER_CODES),
            "code",
        ),
        Spec(
            "orders",
            tables.COMPANIES,
            "t",
            "companies t",
            f"t.code IN ({_in(COMPANY_CODES)})",
            22,
            tuple(COMPANY_CODES),
            "code",
        ),
        Spec(
            "orders",
            tables.ORDERS,
            "t",
            "orders t",
            f"t.order_reference IN ({refs})",
            6,
            tuple(ORDER_REFERENCES),
            "order_reference",
        ),
        Spec(
            "orders",
            tables.ORDER_ITEMS,
            "t",
            "order_items t JOIN orders o ON o.id = t.order_id",
            f"o.order_reference IN ({refs})",
            11,
        ),
        Spec("orders", tables.ORDERS_OUTBOX, "t", "outbox t", f"t.correlation_id IN ({ids})", 17),
        Spec(
            "fulfillment",
            tables.STOCK,
            "t",
            "stock t",
            f"t.company_code IN ({_in(COMPANY_CODES)}) "
            f"AND t.product_code IN ({_in(PRODUCT_CODES)})",
            215,
            live_columns=STOCK_LIVE_COLUMNS,
        ),
        Spec(
            "fulfillment",
            tables.RESERVATIONS,
            "t",
            "reservations t",
            f"t.order_reference IN ({refs})",
            11,
        ),
        Spec(
            "fulfillment",
            tables.DESPATCHES,
            "t",
            "despatches t",
            f"t.order_reference IN ({refs})",
            5,
        ),
        Spec(
            "fulfillment",
            tables.DESPATCH_ITEMS,
            "t",
            "despatch_items t JOIN despatches d ON d.id = t.despatch_id",
            f"d.order_reference IN ({refs})",
            10,
        ),
        Spec(
            "fulfillment",
            tables.FULFILLMENT_OUTBOX,
            "t",
            "outbox t",
            f"t.correlation_id IN ({ids})",
            12,
        ),
        Spec(
            "billing",
            tables.CREDITS,
            "t",
            "credits t",
            f"t.code IN ({_in(CREDIT_CODES)})",
            154,
            tuple(CREDIT_CODES),
            "code",
        ),
        Spec(
            "billing",
            tables.CREDIT_ITEMS,
            "t",
            "credit_items t",
            f"t.order_reference IN ({refs})",
            15,
        ),
        Spec("billing", tables.INVOICES, "t", "invoices t", f"t.order_reference IN ({refs})", 5),
        Spec(
            "billing",
            tables.INVOICE_ITEMS,
            "t",
            "invoice_items t JOIN invoices i ON i.id = t.invoice_id",
            f"i.order_reference IN ({refs})",
            10,
        ),
        Spec(
            "billing",
            tables.PAYMENTS,
            "t",
            "payments t JOIN invoices i ON i.id = t.invoice_id",
            f"i.order_reference IN ({refs})",
            5,
        ),
        Spec("billing", tables.BILLING_OUTBOX, "t", "outbox t", f"t.correlation_id IN ({ids})", 21),
    ]


SPECS = _specs()
EXCLUDED_COLUMNS = {"seq"}  # the outbox identity: assigned by each database


def columns_of(spec: Spec) -> list[str]:
    return [c.name for c in spec.table.columns if c.name not in EXCLUDED_COLUMNS]


def select_sql(spec: Spec) -> str:
    cols = ", ".join(f"{spec.alias}.{c}" for c in columns_of(spec))
    # table, alias and keys are this module's own constants, never input
    return f"SELECT {cols} FROM {spec.source} WHERE {spec.where}"  # noqa: S608


def file_name(spec: Spec) -> str:
    return f"{spec.database}.{spec.table.name}.jsonl"


def live_name(spec: Spec) -> str:
    return f"{spec.database}.{spec.table.name}{LIVE_SUFFIX}"


# ---------------------------------------------------------------- normalisation
def _instant(value: datetime) -> str:
    utc = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    return f"{utc:%Y-%m-%dT%H:%M:%S}.{utc.microsecond // 1000:03d}Z"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def normalise(column: Any, raw: Any) -> Any:
    """One value in the common form: `raw` is a driver value (#9) or sqlcmd's text (#8)."""
    if raw is None or (isinstance(raw, str) and raw == "NULL" and column.nullable):
        return None
    kind = column.type
    if isinstance(kind, RawJson):
        return json.loads(raw) if isinstance(raw, str) else raw  # the line is canonicalised whole
    if isinstance(kind, PG_TIMESTAMP):
        if isinstance(raw, datetime):
            return _instant(raw)
        return _instant(datetime.strptime(str(raw).strip()[:23], "%Y-%m-%d %H:%M:%S.%f"))
    if type(kind) in (Integer, BigInteger, SmallInteger):
        return int(raw)
    if kind.__class__.__name__ == "Uuid":
        return str(UUID(str(raw))).lower()
    return str(raw)


def render(spec: Spec, row: Sequence[Any]) -> str:
    """The seed-immutable part of a row: the live-mutable columns of the spec are not in it."""
    columns = [c for c in spec.table.columns if c.name not in EXCLUDED_COLUMNS]
    return _canonical(
        {
            c.name: normalise(c, v)
            for c, v in zip(columns, row, strict=True)
            if c.name not in spec.live_columns
        }
    )


def render_live(spec: Spec, row: Sequence[Any]) -> str:
    """The identity and the live-mutable columns of a row (informational, never a failure)."""
    columns = [c for c in spec.table.columns if c.name not in EXCLUDED_COLUMNS]
    wanted = set(LIVE_IDENTITY) | set(spec.live_columns)
    return _canonical(
        {c.name: normalise(c, v) for c, v in zip(columns, row, strict=True) if c.name in wanted}
    )


def render_files(spec: Spec, cols: list[str], kept: list[dict[str, Any]]) -> dict[str, list[str]]:
    """File name -> lines for one table: the failing file, and the live section when it has one."""
    files = {file_name(spec): [render(spec, [r[c] for c in cols]) for r in kept]}
    if spec.live_columns:
        files[live_name(spec)] = [render_live(spec, [r[c] for c in cols]) for r in kept]
    return files


def check_subset(spec: Spec, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reduce to the literal subset and fail on any missing or unexpected row."""
    if spec.table is tables.STOCK:
        rows = [r for r in rows if (r["company_code"], r["product_code"]) in STOCK_PAIRS]
        found = {(r["company_code"], r["product_code"]) for r in rows}
        missing = sorted(STOCK_PAIRS - found)
        if missing:
            raise SystemExit(
                f"{file_name(spec)}: {len(missing)} literal stock pairs missing, e.g. {missing[:3]}"
            )
    elif spec.keys:
        found_keys = {r[spec.key_column] for r in rows}
        missing_keys = sorted(set(spec.keys) - found_keys)
        if missing_keys:
            raise SystemExit(f"{file_name(spec)}: literal keys missing: {missing_keys[:5]}")
    if len(rows) != spec.expected:
        raise SystemExit(
            f"{file_name(spec)}: expected {spec.expected} seeded rows, found {len(rows)}"
        )
    return rows


def write_lines(path: Path, lines: Iterable[str]) -> int:
    ordered = sorted(lines)
    path.write_text("".join(f"{line}\n" for line in ordered), encoding="utf-8", newline="\n")
    return len(ordered)


# ---------------------------------------------------------------- #9: PostgreSQL + MongoDB
def mongo_filter() -> dict[str, Any]:
    return {"orderReference": {"$in": ORDER_REFERENCES}}


async def _mongo_lines(uri: str, database: str) -> list[str]:
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(uri)
    try:
        documents = [
            d
            async for d in client.get_database(database)
            .get_collection("order_timeline")
            .find(mongo_filter())
        ]
    finally:
        await client.close()
    if len(documents) != len(ORDER_REFERENCES):
        raise SystemExit(f"mongo.order_timeline: expected 6 documents, found {len(documents)}")
    return [_canonical(d) for d in documents]


async def collect_nine(settings: SeedSettings | None = None) -> dict[str, list[str]]:
    """File name -> its lines, read from #9's databases (no file is touched here)."""
    config = settings or SeedSettings()
    urls = {
        "orders": config.orders_url,
        "fulfillment": config.fulfillment_url,
        "billing": config.billing_url,
    }
    files: dict[str, list[str]] = {}
    for database, url in urls.items():
        conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://", 1))
        try:
            for spec in (s for s in SPECS if s.database == database):
                records = await conn.fetch(select_sql(spec))
                cols = columns_of(spec)
                rows = [dict(zip(cols, list(r.values()), strict=True)) for r in records]
                kept = check_subset(spec, rows)
                files.update(render_files(spec, cols, kept))
        finally:
            await conn.close()
    files["mongo.order_timeline.jsonl"] = await _mongo_lines(
        config.mongo_connection_uri, config.mongo_database
    )
    return files


def write_files(out: Path, files: dict[str, list[str]]) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    return {name: write_lines(out / name, lines) for name, lines in files.items()}


def dump_nine(out: Path, settings: SeedSettings | None = None) -> dict[str, int]:
    return write_files(out, asyncio.run(collect_nine(settings)))


# ---------------------------------------------------------------- #8: MS-SQL via sqlcmd + MongoDB
SEPARATOR = "\x1f"  # the ASCII unit separator: no seeded value contains it


def parse_sqlcmd(text: str, width: int) -> list[list[str]]:
    """Rows printed by `sqlcmd -y 0 -s <US>` (no header, no padding): one row per line.

    Each row has `width` fields.

    A line with another number of fields is an error, never a guess (a value holding the separator
    or a newline would show up here)."""
    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.rstrip("\r")
        if not stripped.strip():
            continue
        fields = stripped.split(SEPARATOR)
        if len(fields) != width:
            if stripped.lstrip().startswith("(") and "rows affected" in stripped:
                continue
            raise ValueError(
                f"sqlcmd line has {len(fields)} fields, expected {width}: {stripped[:120]!r}"
            )
        rows.append(fields)
    return rows


def sqlcmd_argv(container: str, user: str, password: str, database: str, sql: str) -> list[str]:
    """The exact argv. Three flags are traps, each proved against a real SQL Server (round 2):

    * `-y 0` removes sqlcmd's default 256-character cut on `nvarchar(max)` (a `payload` is longer).
    * `-y 0` is mutually exclusive with `-W` and with `-h` ("The y and the W options are mutually
      exclusive"; "The -h and the -y 0 options are mutually exclusive"), so neither is passed.
    * With `-y 0` and neither flag, sqlcmd prints no header and no padding: a fixed-width
      `nvarchar(60)` comes back unpadded, a NULL as `NULL`, one row per line.
    Dropping `-y 0` instead would truncate every payload at 256 characters."""
    return [
        "docker",
        "exec",
        "-i",
        container,
        "/opt/mssql-tools18/bin/sqlcmd",
        "-S",
        "localhost",
        "-U",
        user,
        "-P",
        password,
        "-C",
        "-d",
        database,
        "-s",
        SEPARATOR,
        "-y",
        "0",
        "-f",
        "65001",
        "-Q",
        f"SET NOCOUNT ON; {sql}",
    ]


def sqlcmd(container: str, user: str, password: str, database: str, sql: str) -> str:
    command = sqlcmd_argv(container, user, password, database, sql)
    done = subprocess.run(command, capture_output=True, check=False)  # noqa: S603 - fixed argv, no shell
    if done.returncode != 0:
        raise SystemExit(
            f"sqlcmd failed ({done.returncode}): {done.stderr.decode('utf-8', 'replace')[:300]}"
        )
    return done.stdout.decode("utf-8")


def dump_eight(out: Path, container: str = "otcnet-mssql") -> dict[str, int]:
    password = os.environ.get("MSSQL_APP_PASSWORD")
    if not password:
        raise SystemExit(
            "MSSQL_APP_PASSWORD is not set (see order-to-cash-dotnet/.env; there is no default)"
        )
    user = os.environ.get("MSSQL_APP_USER", "otc_app")
    names = {
        "orders": os.environ.get("MSSQL_DB_ORDERS", "otc_orders"),
        "fulfillment": os.environ.get("MSSQL_DB_FULFILLMENT", "otc_fulfillment"),
        "billing": os.environ.get("MSSQL_DB_BILLING", "otc_billing"),
    }
    out.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for spec in SPECS:
        cols = columns_of(spec)
        printed = sqlcmd(container, user, password, names[spec.database], select_sql(spec))
        rows = [dict(zip(cols, r, strict=True)) for r in parse_sqlcmd(printed, len(cols))]
        kept = check_subset(spec, rows)
        for name, lines in render_files(spec, cols, kept).items():
            counts[name] = write_lines(out / name, lines)
    uri = os.environ.get("EIGHT_MONGO_URI")
    if not uri:
        raise SystemExit(
            "EIGHT_MONGO_URI is not set, e.g. mongodb://otc_mongo_root:...@localhost:27018/?authSource=admin"
        )
    database = os.environ.get("MONGO_DB_READMODEL", "otc_read_model")
    counts["mongo.order_timeline.jsonl"] = write_lines(
        out / "mongo.order_timeline.jsonl", asyncio.run(_mongo_lines(uri, database))
    )
    return counts


# ---------------------------------------------------------------- diff
def diff_dirs(left: Path, right: Path) -> tuple[bool, list[str]]:
    """Compare two dump directories file by file. Returns (identical, report lines).

    `*.live.jsonl` (live-mutable columns) are reported but never make the result False, unless one
    side lacks the file."""
    report: list[str] = []
    names_left = {p.name for p in left.glob("*.jsonl")}
    names_right = {p.name for p in right.glob("*.jsonl")}
    identical = True
    for name in sorted(names_left | names_right):
        if name not in names_left or name not in names_right:
            report.append(f"{name}: only in {'right' if name in names_right else 'left'}")
            identical = False
            continue
        a = (left / name).read_text(encoding="utf-8").splitlines()
        b = (right / name).read_text(encoding="utf-8").splitlines()
        if a == b:
            report.append(f"{name}: {len(a)} rows identical")
            continue
        live = name.endswith(LIVE_SUFFIX)
        identical = identical and live  # a live-state difference is reported, never a failure
        verdict = "LIVE-STATE DIFFERENCE (informational)" if live else "DIFFERENT"
        report.append(f"{name}: {verdict} ({len(a)} vs {len(b)} rows)")
        report.extend(
            f"    {line[:200]}"
            for line in list(difflib.unified_diff(a, b, "left", "right", lineterm="", n=0))[:12]
        )
    if not (names_left | names_right):
        report.append("no .jsonl file in either directory")
        identical = False
    return identical, report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("dump9", "dump8"):
        sub.add_parser(name).add_argument("out", type=Path)
    both = sub.add_parser("diff")
    both.add_argument("left", type=Path)
    both.add_argument("right", type=Path)
    args = parser.parse_args(argv)
    if args.command == "dump9":
        counts = dump_nine(args.out)
    elif args.command == "dump8":
        counts = dump_eight(args.out)
    else:
        identical, report = diff_dirs(args.left, args.right)
        print("\n".join(report))
        return 0 if identical else 1
    for name, count in sorted(counts.items()):
        print(f"{name}: {count} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
