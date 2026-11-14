"""Feature 31 support: the instruments of the black-box API suite, as plain functions so each
one can be armed WITHOUT a fleet (the meta-guards in `test_api_instruments.py`) and then driven by
the tests that do use one.

* `MoneySweep` / `check_money_findings` / `find_decimal_numbers` - R1. Shape-based, ported from #8
  (`tests/Gateway.IntegrationTests/MoneyFieldSweep.cs`) and #7 (`money-field-sweep.ts`): the walk
  carries the nearest `currency` seen at or above the current object and flags every JSON NUMBER
  under it, plus an `amount` key sitting directly beside its own `currency` whatever its kind. The
  Python-specific half is the parser: `json.loads` is told to turn every float token (`100.0`,
  `1e2`, `1E+2`) into a `DecimalToken`, so a decimal can never hide as a Python `int` or be
  rounded into one, and a JSON `true` is never mistaken for a number (`bool` is an `int` subclass).
* `assert_causal_order` / `fact_edges` - R24 and #8 id 105. The required number of edges is derived
  from the brokers (the facts the three services published for the order), never from the
  timeline under test.
* `dump_database` / `diff_tables` - "nothing changed", for R49 and R61: every row of every table.
* `poll` - the one bounded, paced wait of this suite (#8 id 63): `PACING_SECONDS` between probes,
  `asyncio.timeout` around the whole loop.
"""

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import asyncpg
import httpx

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
CURRENCY_SHAPE = re.compile(r"[A-Z]{3}")  # used with fullmatch: `$` would accept "EUR\n"
CURRENCY_KEY = "currency"
CANONICAL_AMOUNT_KEY = "amount"
PACING_SECONDS = 0.1


class DecimalToken:
    """A JSON number written with a fraction or an exponent (`100.0`, `1e2`): R1 forbids it."""

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text

    def __repr__(self) -> str:
        return f"DecimalToken({self.text})"


def parse_json(text: str) -> Any:
    """The suite's ONE parser: floats stay visible as `DecimalToken`, integers stay `int` with no
    size limit (Python ints are unbounded, so the int64 bound is checked, not assumed)."""
    return json.loads(text, parse_float=DecimalToken)


# ------------------------------------------------------------------------------------------ R1


@dataclass(frozen=True, slots=True)
class MoneyFinding:
    path: str
    amount: object
    currency: object  # MISSING when no `currency` exists at or above the amount
    currency_path: str


class _Missing:
    def __repr__(self) -> str:
        return "<no currency>"


MISSING = _Missing()


def _is_json_number(value: object) -> bool:
    # `bool` is an `int` subclass: `True` must NOT count as a number; a DecimalToken IS one.
    return isinstance(value, DecimalToken) or (
        isinstance(value, int) and not isinstance(value, bool)
    )


def sweep_for_money_fields(body: object) -> list[MoneyFinding]:
    findings: list[MoneyFinding] = []
    _walk(body, "$", MISSING, "", findings)
    return findings


def _walk(
    node: object, path: str, inherited: object, inherited_path: str, findings: list[MoneyFinding]
) -> None:
    if isinstance(node, list):
        for index, item in enumerate(node):
            _walk(item, f"{path}[{index}]", inherited, inherited_path, findings)
        return
    if not isinstance(node, dict):
        return
    has_own = CURRENCY_KEY in node
    effective = node[CURRENCY_KEY] if has_own else inherited
    effective_path = f"{path}.{CURRENCY_KEY}" if has_own else inherited_path
    for name, value in node.items():
        if name == CURRENCY_KEY:
            continue
        canonical = name == CANONICAL_AMOUNT_KEY and has_own
        under_currency = _is_json_number(value) and effective is not MISSING
        if effective is not MISSING and (canonical or under_currency):
            findings.append(MoneyFinding(f"{path}.{name}", value, effective, effective_path))
            continue  # a recognised money field is a leaf
        if isinstance(value, dict | list):
            _walk(value, f"{path}.{name}", effective, effective_path, findings)


def money_problems(findings: Iterable[MoneyFinding]) -> list[str]:
    """One sentence per violation, each naming the field path. R1: an integer count of minor
    units (a JSON integer - not `true`, not `100.0`, not `1e2`, not a string, within int64)
    accompanied by an ISO 4217 alpha-3 shaped code (exactly three capitals; no whitespace)."""
    problems: list[str] = []
    for finding in findings:
        amount = finding.amount
        if isinstance(amount, bool) or not isinstance(amount, int):
            problems.append(
                f"{finding.path}: R1 requires an integer count of minor units, got {amount!r}"
            )
        elif not INT64_MIN <= amount <= INT64_MAX:
            problems.append(f"{finding.path}: R1 amount {amount} is beyond the bigint column")
        currency = finding.currency
        if not (isinstance(currency, str) and CURRENCY_SHAPE.fullmatch(currency)):
            problems.append(
                f"{finding.path}: R1 requires an ISO 4217 alpha-3 currency code beside the amount, "
                f"got {currency!r} (at {finding.currency_path or 'nowhere'})"
            )
    return problems


def check_money_findings(label: str, findings: Sequence[MoneyFinding], *, minimum: int) -> None:
    """Fail naming `label` and the path of EVERY violation; fail also when fewer than `minimum`
    money fields were found (an empty sweep must never pass, R1 sentinel)."""
    assert len(findings) >= minimum, (
        f"{label}: the sweep found {len(findings)} monetary field(s), fewer than the {minimum} "
        "that a response of this kind always carries - the sweep would be vacuous"
    )
    problems = money_problems(findings)
    assert not problems, f"{label}: " + "; ".join(problems)


def find_decimal_numbers(body: object, path: str = "$") -> list[str]:
    """The path of every JSON number written as a decimal, anywhere in the body, money or not."""
    if isinstance(body, DecimalToken):
        return [f"{path}={body.text}"]
    if isinstance(body, list):
        return [p for i, v in enumerate(body) for p in find_decimal_numbers(v, f"{path}[{i}]")]
    if isinstance(body, dict):
        return [p for k, v in body.items() for p in find_decimal_numbers(v, f"{path}.{k}")]
    return []


# --------------------------------------------------------------------------------- R24 / id 105


def timeline_edges(events: Sequence[Mapping[str, Any]]) -> list[tuple[int, int]]:
    """(cause index, effect index) for every entry whose `causationId` names another entry's
    `eventId` in the same timeline."""
    position = {str(e["eventId"]): i for i, e in enumerate(events)}
    return [
        (position[str(e["causationId"])], i)
        for i, e in enumerate(events)
        if e.get("causationId") is not None
        and str(e["causationId"]) in position
        and position[str(e["causationId"])] != i
    ]


def assert_causal_order(events: Sequence[Mapping[str, Any]], *, required_edges: int) -> int:
    """The GENERAL invariant (amendment A1): for every entry whose `causationId` names another
    entry's `eventId`, the cause precedes the effect. #8 id 105: the check also fails when it
    resolved FEWER than `required_edges` edges, so a timeline that lost every `causationId` cannot
    pass by checking nothing. `required_edges` must be at least 1."""
    assert required_edges >= 1, "a causal-order check must require at least one edge"
    types = [str(e["eventType"]) for e in events]
    edges = timeline_edges(events)
    for cause, effect in edges:
        assert cause < effect, (
            f"causal order violated: {types[effect]} (index {effect}) precedes its cause "
            f"{types[cause]} (index {cause}): {types}"
        )
    assert len(edges) >= required_edges, (
        f"causal-order check resolved only {len(edges)} causal edge(s), fewer than the "
        f"{required_edges} the order's facts require - no causal edges were checked: {types}"
    )
    return len(edges)


def fact_edges(facts: Sequence[Mapping[str, Any]]) -> int:
    """The number of cause -> effect pairs among the facts the services PUBLISHED for one order
    (envelopes read off the topics): an independent count of what the timeline must resolve."""
    ids = {str(f["eventId"]) for f in facts}
    return sum(
        1 for f in facts if str(f["causationId"]) in ids and f["causationId"] != f["eventId"]
    )


# ------------------------------------------------------------------------------ "nothing changed"

Row = dict[str, Any]
Dump = dict[str, list[Row]]


async def dump_database(dsn: str) -> Dump:
    """Every row of every table of the `public` schema, ordered by its first column."""
    connection = await asyncpg.connect(dsn)
    try:
        names = [
            r["table_name"]
            for r in await connection.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY 1"
            )
        ]
        return {
            name: [dict(r) for r in await connection.fetch(f'SELECT * FROM "{name}" ORDER BY 1')]  # noqa: S608 - names come from information_schema
            for name in names
        }
    finally:
        await connection.close()


def diff_tables(before: Dump, after: Dump) -> list[str]:
    """One sentence per table whose rows differ (count or content), naming the table."""
    problems: list[str] = []
    for name in sorted(set(before) | set(after)):
        if before.get(name) != after.get(name):
            problems.append(
                f"{name}: {len(before.get(name, []))} row(s) before, "
                f"{len(after.get(name, []))} after"
            )
    return problems


def rows_where(dump: Dump, table: str, **match: Any) -> list[Row]:
    return [r for r in dump[table] if all(r[k] == v for k, v in match.items())]


# ------------------------------------------------------------------------------------------ poll


async def poll[T](
    probe: Callable[[], Awaitable[T | None]], what: str, *, seconds: float = 60.0
) -> T:
    """Probe every `PACING_SECONDS` until the answer is truthy; fail naming `what` when `seconds`
    have passed. The bound is `asyncio.timeout` around the whole loop; the pacing is the sleep
    between two probes (armed by `test_poll_waits_between_probes_and_gives_up_naming_what`)."""
    try:
        async with asyncio.timeout(seconds):
            while True:
                found = await probe()
                if found:
                    return found
                await asyncio.sleep(PACING_SECONDS)
    except TimeoutError:
        raise TimeoutError(f"never happened within {seconds} s: {what}") from None


# ------------------------------------------------------------------------------- the black box


JSON_MEDIA_TYPES = ("application/json", "application/problem+json")


def assert_response_money(seen: Seen) -> None:
    """R1 at the moment of receipt, for every JSON response: each money field found by shape is an
    integer with a currency code, and no number anywhere is a decimal. The per-kind MINIMUM of
    money fields (the vacuity guard) is the sweep test's, which knows the operation."""
    if not seen.content_type.startswith(JSON_MEDIA_TYPES):
        return
    label = f"{seen.method} {seen.template} {seen.status}"
    body = parse_json(seen.text)
    check_money_findings(label, sweep_for_money_fields(body), minimum=0)
    assert not find_decimal_numbers(body), f"{label}: a decimal number on the wire"


@dataclass(frozen=True, slots=True)
class Seen:
    """One response the suite received, keyed by the OPERATION (method + path template)."""

    method: str
    template: str
    status: int
    content_type: str
    text: str


FACT_TOPIC_BY_SERVICE = {
    "orders": "otc.orders.facts.v1",
    "fulfillment": "otc.fulfillment.facts.v1",
    "billing": "otc.billing.facts.v1",
}
SERVICES = ("orders", "fulfillment", "billing")


class BlackBox:
    """The Gateway on a real socket with `httpx` as the only client of the system under test.
    The fleet's databases and topics are EVIDENCE the tests read, never a way to drive."""

    def __init__(self, http: httpx.AsyncClient, fleet: Any, operator_password: str) -> None:
        self.operator_password = operator_password
        self.http = http
        self.fleet = fleet
        self.seen: list[Seen] = []

    async def call(
        self, method: str, template: str, path: str | None = None, **kwargs: Any
    ) -> httpx.Response:
        response = await self.http.request(method, path or template, **kwargs)
        seen = Seen(
            method,
            template,
            response.status_code,
            response.headers.get("content-type", ""),
            response.text,
        )
        self.seen.append(seen)
        assert_response_money(seen)  # R1 on EVERY response any test of this suite receives
        return response

    async def place(
        self, *, unit_price: int, quantity: int, product: str = "PRD-0002", discount: int = 0
    ) -> dict[str, Any]:
        response = await self.call(
            "POST",
            "/orders",
            json={
                "retailerCode": "AldiEs",
                "companyCode": "SPANATURAL",
                "currency": "EUR",
                "lines": [
                    {
                        "productCode": product,
                        "quantity": quantity,
                        "unitPrice": unit_price,
                        "lineDiscount": discount,
                    }
                ],
            },
        )
        assert response.status_code == 201, f"POST /orders: {response.status_code} {response.text}"
        body: dict[str, Any] = parse_json(response.text)
        return body

    async def wait_order(
        self, order_id: str, status: str, *, seconds: float = 60.0
    ) -> dict[str, Any]:
        async def reached() -> dict[str, Any] | None:
            response = await self.call("GET", "/orders/{id}", f"/orders/{order_id}")
            if response.status_code != 200:
                return None  # 202 projection pending: not there yet
            body: dict[str, Any] = parse_json(response.text)
            return body if body["status"] == status else None

        return await poll(
            reached, f"order {order_id} is {status} in GET /orders/{{id}}", seconds=seconds
        )

    async def invoice_of(self, order_reference: str) -> dict[str, Any]:
        async def listed() -> dict[str, Any] | None:
            response = await self.call(
                "GET", "/invoices", f"/invoices?orderReference={order_reference}"
            )
            items = parse_json(response.text).get("items") if response.status_code == 200 else None
            found: dict[str, Any] | None = items[0] if items else None
            return found

        return await poll(listed, f"an invoice of {order_reference} is listed")

    async def pay(
        self,
        invoice: Mapping[str, Any],
        reference: str,
        *,
        amount: int | None = None,
        currency: str | None = None,
    ) -> httpx.Response:
        return await self.call(
            "POST",
            "/invoices/{id}/payments",
            f"/invoices/{invoice['invoiceId']}/payments",
            json={
                "paymentReference": reference,
                "amount": {
                    "amount": invoice["totalAmount"] if amount is None else amount,
                    "currency": "EUR"
                    if currency is None
                    else currency,  # every order of this suite is in EUR
                },
                "valueDate": "2026-10-13T08:30:00.000Z",
                "source": "test",
            },
        )

    async def facts(self, order_id: str) -> list[dict[str, Any]]:
        """Every envelope the three services published for the order, read off the topics."""
        found: list[dict[str, Any]] = []
        for topic in FACT_TOPIC_BY_SERVICE.values():
            found += [json.loads(r.value) for r in await self.fleet.records(topic, order_id)]
        return found

    async def all_fact_counts(self) -> dict[str, int]:
        return {
            service: len(await self.fleet.read_all(topic))
            for service, topic in FACT_TOPIC_BY_SERVICE.items()
        }

    async def dump_all(self) -> dict[str, Dump]:
        return {s: await dump_database(self.fleet.databases[s].dsn) for s in SERVICES}

    async def quiesce(self) -> dict[str, Dump]:
        """Wait (bounded, paced) until every outbox is published and two consecutive dumps of the
        three write models are identical: the baseline a 'nothing changed' claim is read against."""
        previous: dict[str, Dump] | None = None

        async def stable() -> dict[str, Dump] | None:
            nonlocal previous
            current = await self.dump_all()
            unpublished = any(
                r["published_at"] is None for s in SERVICES for r in current[s]["outbox"]
            )
            settled = previous == current and not unpublished
            previous = current
            return current if settled else None

        return await poll(stable, "the three write models are quiescent")
