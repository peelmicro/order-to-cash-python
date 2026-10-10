"""Every write path into a service's database is enumerated and classified (backlog 204(a)).

The range guard is an ORM attribute event (`persistence/range_guards.py`), so the claim "every
write into a guarded integer column is range-checked" is a claim about the POPULATION of write
paths in `services/<name>/src`, and a population is a search result. The first instrument for it,
`grep -n "insert(\\|update(\\|text(\\|bulk_"`, found only call syntax: it MISSED a raw SQL string
held in a module constant (`sequences.py`'s `ADVANCE_ORDER_SEQUENCE = "UPDATE order_number_..."`,
`SEED_ORDER_SEQUENCE = "INSERT INTO ..."`, executed by whoever imports them), which has no `(`
after the keyword. This guard reads the AST and looks for BOTH forms:

* a call whose name is a DML constructor, a bulk helper, a raw-SQL entry point or an ORM
  unit-of-work method (`insert`, `update`, `delete`, `text`, `execute`, `bulk_*`, `add`, ...);
* a string literal, in ANY position (module constant, default argument, docstring, one half of an
  implicit concatenation, the literal parts of an f-string) that contains a DML statement:
  `INSERT INTO`, `UPDATE <table> SET`, `DELETE FROM`, `MERGE INTO`, `COPY ... FROM`, `TRUNCATE`,
  in any letter case and across line breaks. `SELECT ... FOR UPDATE` is a lock, not a write.

Instrument (round 2 of the sweep, after the reviewer planted three writers that passed): the scan
returns a `Counter` of `(kind, detail)` per file, NOT a set, and `EXPECTED` holds the COUNT of each
entry, so a second writer with the same call name or the same statement in an already-classified
file raises a count and fails. A SQL detail is the WHOLE normalised statement, not its first words.
Strings are joined before they are scanned: a `+` chain, a `.join([...])` of literals and an
f-string become one text with `{}` for each non-literal part, so a `+` chain is seen;
`{}` / `%s` / `:name` placeholders, `ONLY` and `AS alias` are accepted between `UPDATE` and `SET`;
`bytes` literals are decoded; an aliased import of a DML constructor (`from sqlalchemy import insert
as ins`) is resolved to its canonical name and the import itself is a hit. Why not a behavioural
check (capture the SQL a driver sees)? A writer nobody executes in a test is exactly the writer this
guard exists to find, and a runtime capture only sees executed statements, so the static scan stays
and the DB-level guard (`test_every_integer_column_of_the_live_database_is_guarded`) is the
behavioural half. Out of scope, by service: see `EXCLUDED`.

Round 3: SQL comments (`/* ... */`, `-- ...`) are blanked before the statement pattern is applied,
and
`Insert` / `Update` / `Delete` are constructors like their lower-case functions.

Accepted residuals (computed or unidiomatic; a syntax scan cannot close them, the live-database
guard is the behavioural half): a statement whose verb sits in a separate NAME
(`_V = "UPDATE "`, `Q = _V + _R`), `getattr(sa, "update")`, a quoted table name containing a
space, and a DML constructor stored in a dict and called through it (`{"u": update}["u"](...)`,
the dict-alias form; the `update` Name is still an import hit, the call is not).

The expected counts are the literal below, one classification per entry. A new writer fails the test
by name until it is added here WITH a classification: guarded (goes through the ORM unit of work,
so `install_range_guards` fires), `ensure_in_range` (the caller checks first), or
`no guarded column` (it writes none, with the reason). The sentinels prove the instrument sees
each hiding place; a pattern that "finds nothing" would otherwise mean nothing.
"""

import ast
import re
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
# Every service with a `src` is scanned unless it is named here WITH a reason, so a NEW service
# fails `test_the_scanned_population_is_every_service_minus_the_literal_exclusions`.
EXCLUDED = {
    "gateway": "no database: it forwards over NATS and holds no connection",
    "projector": "writes MongoDB read models: no guarded integer column exists in a document store",
    "seed": "its own population test, services/seed/tests/unit/test_write_path_population.py",
}

CALL_NAMES = {
    "insert",
    "pg_insert",
    "update",
    "delete",
    # SQLAlchemy's DML classes: constructable and importable under any alias, like the functions.
    "Insert",
    "Update",
    "Delete",
    "text",
    "execute",
    "executemany",
    "exec_driver_sql",
    "add",
    "add_all",
    "merge",
    "copy_records_to_table",
    # asyncpg's other write-side COPY (a bulk load from a file); `copy_from_*` are reads.
    "copy_to_table",
}
# `\s+` spans line breaks and tab runs. Between the verb and its keyword may sit a schema-qualified
# or quoted table, a placeholder (`{}`, `%s`, `%(t)s`, `:t`) standing for one, `ONLY`, `AS alias`.
_TABLE = r"(?:only\s+)?(?:[\w\".]+|\{\w*\}|%s|%\(\w+\)s|:\w+)(?:\s+(?:as\s+)?\w+)?"
DML_TEXT = re.compile(
    rf"\b(insert\s+into|update\s+{_TABLE}\s+set|delete\s+from|merge\s+into|truncate\b|copy\s+\S+\s+from)",
    re.IGNORECASE,
)
_HOLE = "{}"
# SQL comments are not statement text: `UPDATE /* c */ t SET` is the same write as without them.
_SQL_COMMENT = re.compile(r"/\*.*?\*/|--[^\n]*", re.DOTALL)


def _is_call_name(name: str | None) -> bool:
    return name is not None and (name in CALL_NAMES or name.startswith("bulk_"))


def _leaves(node: ast.expr) -> list[ast.expr] | None:
    """The operands of a `+` chain; None when `node` is not one."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _leaves(node.left), _leaves(node.right)
        return [*(left if left is not None else [node.left]), *(right or [node.right])]
    return None


def _text_of(node: ast.expr) -> str | None:
    """The text a string-valued expression stands for, `{}` for each part not known statically;
    None when the expression is not string-shaped at all."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return node.value
        if isinstance(node.value, bytes):
            return node.value.decode("latin-1")
        return None
    if isinstance(node, ast.JoinedStr):
        pieces: list[str] = []
        for value in node.values:
            literal = value.value if isinstance(value, ast.Constant) else None
            pieces.append(literal if isinstance(literal, str) else _HOLE)
        return "".join(pieces)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        parts = [_text_of(leaf) for leaf in _leaves(node) or []]
        if any(part is not None for part in parts):
            return "".join(_HOLE if part is None else part for part in parts)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.List | ast.Tuple)
    ):
        separator = _text_of(node.func.value) or ""
        items = [_text_of(item) for item in node.args[0].elts]
        if any(item is not None for item in items):
            return separator.join(_HOLE if item is None else item for item in items)
    return None


def _scan_text(text: str, found: Counter[tuple[str, str]]) -> None:
    """One occurrence per DML statement start; the detail is the whole statement, normalised."""
    text = _SQL_COMMENT.sub(" ", text)
    starts = [m.start() for m in DML_TEXT.finditer(text)]
    for begin, end in zip(starts, [*starts[1:], len(text)][: len(starts)], strict=True):
        found[("sql", " ".join(text[begin:end].split()).lower())] += 1


def hits(source: str) -> Counter[tuple[str, str]]:
    """`(kind, detail)` -> occurrences, for every write-looking call or reference, every aliased
    import of a DML constructor and every DML-bearing string expression."""
    tree = ast.parse(source)
    found: Counter[tuple[str, str]] = Counter()
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if _is_call_name(alias.name):
                    aliases[alias.asname or alias.name] = alias.name
                    if alias.asname:
                        found[("import", f"{alias.name} as {alias.asname}")] += 1
    called: set[int] = set()
    consumed: set[int] = set()  # operands already read as part of a longer string expression
    for node in ast.walk(tree):  # breadth first: a parent is seen before its operands
        if id(node) in consumed:
            continue
        if isinstance(node, ast.Call):
            func = node.func
            called.add(id(func))
            name: str | None = (
                aliases.get(func.id, func.id)
                if isinstance(func, ast.Name)
                else getattr(func, "attr", None)
            )
            if _is_call_name(name):
                found[("call", str(name))] += 1
        elif (
            isinstance(node, ast.Attribute) and id(node) not in called and _is_call_name(node.attr)
        ):
            found[("ref", node.attr)] += 1  # `x = sa.insert`, passed on without being called
        if isinstance(node, ast.expr) and (text := _text_of(node)) is not None:
            consumed.update(
                id(n)
                for n in ast.walk(node)
                if n is not node and isinstance(n, ast.expr) and _text_of(n) is not None
            )
            _scan_text(text, found)
    return found


# service -> relative path under src/otc_<service> -> expected hits and their COUNTS (the
# classification is the comment). Empty for a service means "no write path exists yet".
EXPECTED: dict[str, dict[str, Counter[tuple[str, str]]]] = {
    "orders": {
        # kernel `Money.add` arithmetic, not a write: the domain imports no driver (domain-purity
        # contract). Three calls in `compute_totals`: the running initial amount, the running line
        # discounts, and the line discounts plus the (zero) order-level discount. Counts read from
        # `scan_service("orders")`, never predicted.
        "domain/totals.py": Counter({("call", "add"): 3}),
        # Feature 14. The idempotent consumer's dedup row: `INSERT ... ON CONFLICT DO NOTHING`
        # through a Core `insert` (imported as `pg_insert`, which the instrument resolves to
        # `insert` and counts as an aliased-import hit) executed once. NO GUARDED COLUMN:
        # `processed_events` has no integer column (uuid, varchar and timestamptz only).
        "infrastructure/messaging/idempotent_consumer.py": Counter(
            {("import", "insert as pg_insert"): 1, ("call", "execute"): 1, ("call", "insert"): 1}
        ),
        # The relay's stamp: `session.execute(update(Outbox)...values(published_at=...))`. NO
        # GUARDED COLUMN: it writes one timestamptz and no integer (`seq` is never assigned).
        "infrastructure/outbox/relay.py": Counter({("call", "execute"): 1, ("call", "update"): 1}),
        # The writer's `session.add(Outbox(...))`, one per event: GUARDED (the ORM unit of work, so
        # `install_range_guards` fires on every integer column of the row).
        "infrastructure/outbox/writer.py": Counter({("call", "add"): 1}),
        # DDL defaults `server_default=text("0")` and `text("'{}'")`: schema, not a write. Two.
        "infrastructure/persistence/models.py": Counter({("call", "text"): 2}),
        # Feature 14's repository, six `add`, one `update`, one `delete`, two `execute`, each
        # classified (counts read from `scan_service("orders")`, never predicted):
        #  * `session.add` x3 (the new `orders` row, a new `order_items` row on insert, a new
        #    `order_items` row on update): GUARDED (the ORM unit of work, `install_range_guards`
        #    fires on every integer column, `order_items.quantity` included);
        #  * `set.add` x3 (`self._loaded.add` twice, `kept.add` once): a Python set, not a write;
        #  * `self._written_events.update(...)`: `set.update`, not a write;
        #  * `session.delete(item)`: NO GUARDED COLUMN (a delete writes no value);
        #  * `session.execute(select(...))` x2 (`_load`'s two reads): SELECTs, not writes.
        "infrastructure/persistence/order_repository.py": Counter(
            {
                ("call", "add"): 6,
                ("call", "update"): 1,
                ("call", "delete"): 1,
                ("call", "execute"): 2,
            }
        ),
        # Feature 15, the allocator: `session.execute(text(...))` x3 of the three `sequences.py`
        # constants below (seed, lock, advance), counted here as three `execute` and three `text`.
        # The two writes are classified at their constants; the third is a SELECT ... FOR UPDATE.
        # NO CALLER-SUPPLIED INTEGER reaches any of them, so there is nothing to range-check.
        "infrastructure/persistence/order_number_allocator.py": Counter(
            {("call", "execute"): 3, ("call", "text"): 3}
        ),
        # Feature 15, the reference catalogue: `session.execute(select(...))` x3 (retailer,
        # company, products). SELECTs, not writes (currency uses `session.scalar`).
        "infrastructure/persistence/reference_catalog.py": Counter({("call", "execute"): 3}),
        # Feature 15, the responder: `in_flight.add(task)`, a Python `set.add`, not a write.
        "presentation/orders_create_responder.py": Counter({("call", "add"): 1}),
        # Feature 16, the saga's owed-command queue: `session.execute(pg_insert(SagaCommand)...
        # .on_conflict_do_nothing(...).returning(...))`, one statement (`pg_insert` is the aliased
        # import the instrument resolves to `insert`, counted as an import hit and a call). NO
        # GUARDED COLUMN: `attempts` is never written (the server default `0` applies), so this
        # ORM-enabled insert writes no integer column at all. Counts read from `scan_service`.
        "infrastructure/saga/command_queue.py": Counter(
            {("import", "insert as pg_insert"): 1, ("call", "execute"): 1, ("call", "insert"): 1}
        ),
        # Feature 16 and 42, the ledger: five ORM-enabled `update(SagaCommand)` statements
        # (`try_claim`, `claim_due`, `mark_sent`, `reject`, `park`) through ONE `session.execute` in
        # `_execute`. Three write NO GUARDED COLUMN (`try_claim` and `claim_due` write two
        # timestamps, `mark_sent` a status and two timestamps). `park` and (feature 42) `reject`
        # write `attempts` (int4) and are each `ensure_in_range`: the caller's total is
        # range-checked BEFORE the statement runs, because an ORM-enabled update bypasses the
        # attribute guard (`range_guards.py`'s residual).
        "infrastructure/saga/command_ledger.py": Counter(
            {("call", "update"): 5, ("call", "execute"): 1}
        ),
        # Feature 16, the ignored-fact recorder: `session.add(SagaIgnoredFact(...))`, GUARDED (the
        # ORM unit of work, so `install_range_guards` fires on every integer column of the row;
        # the table has none).
        "infrastructure/saga/ignored_facts.py": Counter({("call", "add"): 1}),
        # Feature 16, the fast path: `self._children.add(task)`, a Python `set.add`, not a write.
        "infrastructure/saga/fast_path.py": Counter({("call", "add"): 1}),
        # Raw SQL constants; each is executed inside the caller's transaction. SEED writes the one
        # counter row (id, next_value: both computed by the statement itself, no caller-supplied
        # integer); ADVANCE is `next_value + 1`, a server-side expression on a counter the same
        # transaction just read FOR UPDATE. No caller value ever reaches either, so there is no
        # input for `ensure_in_range` to check.
        "infrastructure/persistence/sequences.py": Counter(
            {
                (
                    "sql",
                    "insert into order_number_sequences (id, next_value) select 1, "
                    "coalesce((select max(cast(substring(order_reference from 5) as bigint)) "
                    "from orders), 0) + 1 where not exists "
                    "(select 1 from order_number_sequences where id = 1) "
                    "on conflict (id) do nothing",
                ): 1,
                (
                    "sql",
                    "update order_number_sequences set next_value = next_value + 1 where id = 1",
                ): 1,
            }
        ),
    },
    # Feature 17 added the stock write path; counts read from `scan_service("fulfillment")`, never
    # predicted. The guarded integer columns (`stock.units`, `stock.reserved_units`,
    # `reservations.units`) are written ONLY by attribute assignment or constructor in
    # `infrastructure/persistence/stock_mapper.py` (design 9.2), which the scan does not count
    # because an assignment is not a call: it is the guarded path (the range guard is an ORM
    # attribute event). Any `update(Stock).values(...)`, `insert(...)` or `text()` write that gets
    # added anywhere shows up below as an unclassified hit.
    "fulfillment": {
        # The relay copy's stamp (parity-guarded against Orders'): `session.execute(update(Outbox)
        # ...values(published_at=...))`. NO GUARDED COLUMN: it writes one timestamptz.
        "infrastructure/outbox/relay.py": Counter({("call", "execute"): 1, ("call", "update"): 1}),
        # The writer copy's `session.add(Outbox(...))`, one per event: GUARDED (the ORM unit of
        # work, so `install_range_guards` fires on every integer column of the row).
        "infrastructure/outbox/writer.py": Counter({("call", "add"): 1}),
        # `session.execute(select(...))` x2 (`availability`, `stock_keys_of_order`): SELECTs, not
        # writes (`list` reads through `session.scalar` / `scalars`).
        "infrastructure/persistence/stock_reads.py": Counter({("call", "execute"): 2}),
        # `self._session.add(created)`: a NEW reservation row built by `stock_mapper`'s constructor
        # call. GUARDED (the ORM unit of work: `reservations.units` is range-checked when the
        # constructor assigns it). Every other row it writes was loaded under `FOR UPDATE` and is
        # changed by attribute assignment in the mapper. No upsert, no `ON CONFLICT` (ledger L6).
        "infrastructure/persistence/stock_repository.py": Counter({("call", "add"): 1}),
        # Feature 18, the `DES-` allocator (the Orders allocator's shape): three `execute` and three
        # `text` over the constants of `sequences.py` below (seed, lock, advance). The two writes
        # are classified at their constants; the third is a SELECT ... FOR UPDATE. NO
        # CALLER-SUPPLIED INTEGER reaches any of them (`next_value` is read from the row and
        # advanced in SQL), so there is nothing to range-check.
        "infrastructure/persistence/despatch_number_allocator.py": Counter(
            {("call", "execute"): 3, ("call", "text"): 3}
        ),
        # Feature 18: `session.add(Despatch(...))` and, in the line loop, `session.add(DespatchItem
        # (...))`. GUARDED (the ORM unit of work: `despatch_items.units` is range-checked when the
        # constructor assigns it). Plain INSERTs, no upsert and no `ON CONFLICT` (ledger L6): the
        # `despatches.order_reference` unique key is F8's last line, not a write path.
        "infrastructure/persistence/despatch_repository.py": Counter({("call", "add"): 2}),
        # `in_flight.add(task)`: a Python `set.add`, not a write.
        "presentation/stock_responder.py": Counter({("call", "add"): 1}),
        # Same two constants, same classification as orders' (no caller-supplied integer reaches
        # them).
        "infrastructure/persistence/sequences.py": Counter(
            {
                (
                    "sql",
                    "insert into despatch_number_sequences (id, next_value) select 1, "
                    "coalesce((select max(cast(substring(despatch_reference from 5) as bigint)) "
                    "from despatches), 0) + 1 where not exists "
                    "(select 1 from despatch_number_sequences where id = 1) "
                    "on conflict (id) do nothing",
                ): 1,
                (
                    "sql",
                    "update despatch_number_sequences set next_value = next_value + 1 where id = 1",
                ): 1,
            }
        ),
    },
    # Feature 19 added the credit ledger's write path; counts read from `scan_service("billing")`,
    # never predicted. `credit_items.amount` is written ONLY by the `CreditItem(...)` constructor in
    # `infrastructure/persistence/credit_mapper.py` (a constructor is not a call the scan counts:
    # it is the guarded path, the range guard being an ORM attribute event). The `credits`
    # row is never assigned. No `update(`, `delete(` or `on_conflict_*` is written by the service.
    "billing": {
        # The relay copy's stamp (parity-guarded against Orders'): `session.execute(update(Outbox)
        # ...values(published_at=...))`. NO GUARDED COLUMN: it writes one timestamptz.
        "infrastructure/outbox/relay.py": Counter({("call", "execute"): 1, ("call", "update"): 1}),
        # The writer copy's `session.add(Outbox(...))`, one per event: GUARDED (the ORM unit of
        # work, so `install_range_guards` fires on every integer column of the row).
        "infrastructure/outbox/writer.py": Counter({("call", "add"): 1}),
        # `session.execute(select(CreditItem...))` in the list view: a SELECT, not a write.
        "infrastructure/persistence/credit_reads.py": Counter({("call", "execute"): 1}),
        # `text(...)` + `session.execute(...)` of the committed-exposure scalar: a SELECT (no DML
        # `text` exists, design 9.1); `session.add(credit_mapper.new_item_row(...))`: a NEW ledger
        # row built by the mapper's constructor call. GUARDED (the ORM unit of work: the range
        # guard fires on `credit_items.amount`). Plain INSERTs, no upsert, no `ON CONFLICT` (L19).
        "infrastructure/persistence/credit_repository.py": Counter(
            {("call", "text"): 1, ("call", "add"): 1, ("call", "execute"): 1}
        ),
        # Feature 21 (counts read from `scan_service("billing")`, each classified):
        # the counter allocator's THREE `text(...)` + THREE `session.execute(...)`: the seed
        # (`INSERT ... WHERE NOT EXISTS ... ON CONFLICT DO NOTHING`), the `SELECT ... FOR UPDATE`
        # and the advance (`UPDATE ... SET next_value = next_value + 1`). The ONLY textual DML in
        # the service (L26): it bypasses the ORM range guard on `next_value` (the residual
        # `range_guards.py` names) and the engine refuses an overflow; `sequences.py`'s two DML
        # entries below are its constants. A fourth `execute(text(...))` here is a new write path.
        "infrastructure/persistence/invoice_number_allocator.py": Counter(
            {("call", "execute"): 3, ("call", "text"): 3}
        ),
        # The invoice repository's TWO `session.add(...)`: the header row (flushed first, the lines'
        # foreign key) and the line rows (one site, in a loop). GUARDED (the ORM unit of work: the
        # range guard fires on the invoice's three totals and on `invoice_items.units|price`).
        # Plain INSERTs, no upsert: issuing never updates an invoice.
        # Feature 22 (`billing.payment.register`; counts read from `scan_service("billing")`):
        # a THIRD `session.add(...)`, the `payments` row built by `invoice_mapper.new_payment_row`
        # (GUARDED: the ORM unit of work fires the range guard on `payments.amount`), and the
        # service's FIRST AND ONLY `update(Invoice)` + its `session.execute(...)`: `status`,
        # `paid_at`, `updated_at` of ONE invoice `WHERE id = :id AND status = 'issued'`, executed
        # under the `credits` line lock (BI8). It writes no guarded integer column (a text, a
        # timestamptz and a timestamptz), so it bypasses no range guard. A second `update(` here
        # is a new write path.
        "infrastructure/persistence/invoice_repository.py": Counter(
            {("call", "add"): 3, ("call", "execute"): 1, ("call", "update"): 1}
        ),
        # `in_flight.add(task)`: a Python `set.add`, not a write.
        "presentation/credit_responder.py": Counter({("call", "add"): 1}),
        "infrastructure/persistence/sequences.py": Counter(
            {
                (
                    "sql",
                    "insert into invoice_number_sequences (id, next_value) select 1, "
                    "coalesce((select max(cast(substring(invoice_reference from 5) as bigint)) "
                    "from invoices), 0) + 1 where not exists "
                    "(select 1 from invoice_number_sequences where id = 1) "
                    "on conflict (id) do nothing",
                ): 1,
                (
                    "sql",
                    "update invoice_number_sequences set next_value = next_value + 1 where id = 1",
                ): 1,
            }
        ),
    },
    # notifications: no write path exists yet.
}


def _scanned_services() -> list[str]:
    on_disk = {p.parent.name for p in (REPO_ROOT / "services").glob("*/src")}
    return sorted(on_disk - set(EXCLUDED))


SERVICES = _scanned_services()


def _files(service: str) -> list[Path]:
    root = REPO_ROOT / "services" / service / "src" / f"otc_{service}"
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _relative(service: str, path: Path) -> str:
    return path.relative_to(REPO_ROOT / "services" / service / "src" / f"otc_{service}").as_posix()


def scan_service(service: str) -> dict[str, Counter[tuple[str, str]]]:
    return {
        _relative(service, p): found_here
        for p in _files(service)
        if (found_here := hits(p.read_text(encoding="utf-8")))
    }


def test_the_scanned_population_is_every_service_minus_the_literal_exclusions() -> None:
    # The scanned set is derived from disk and the exclusions are a literal with reasons, so a new
    # service is scanned by default. The literal below makes a changed population name itself.
    assert SERVICES == ["billing", "fulfillment", "notifications", "orders"], SERVICES
    assert all(EXCLUDED.values()), "every exclusion needs a reason"


@pytest.mark.parametrize("service", SERVICES)
def test_every_write_path_in_the_service_is_a_classified_literal(service: str) -> None:
    assert len(_files(service)) >= 5, f"the scan of {service} covered {len(_files(service))} files"
    found = scan_service(service)
    assert found == EXPECTED.get(service, {}), (
        f"services/{service}/src has an unclassified write path (or lost a classified one, or "
        f"gained a second occurrence of one): add it to EXPECTED with its classification. "
        f"Found: {found}"
    )


# --- the instrument itself: each hiding place MUST be seen -----------------------------------

MUST_SEE = {
    "call insert": "def f(s):\n    s.execute(insert(T).values(a=1))\n",
    "call update": "q = update(T)\n",
    "call bulk helper": "def f(s):\n    s.bulk_insert_mappings(T, [])\n",
    "call text": "q = text('x')\n",
    "unit of work add": "def f(s):\n    s.add(row)\n",
    "upper-case constant": 'ADVANCE = "UPDATE order_number_sequences SET next_value = 1"\n',
    "lower-case constant": 'ADVANCE = "update t set a = 1"\n',
    "implicit concatenation": 'Q = (\n    "INSERT INTO t (a) "\n    "VALUES (1)"\n)\n',
    "line break between keywords": 'Q = """INSERT\n    INTO t (a) VALUES (1)"""\n',
    "delete": 'Q = "DELETE FROM t"\n',
    "merge": 'Q = "MERGE INTO t USING s ON 1=1 WHEN MATCHED THEN DELETE"\n',
    "truncate": 'Q = "TRUNCATE t"\n',
    "copy": 'Q = "COPY t FROM STDIN"\n',
    "cte write": 'Q = "WITH x AS (UPDATE t SET a = 1 RETURNING a) SELECT * FROM x"\n',
    "f-string literal part": 'def f(t):\n    return f"UPDATE {t} SET a = 1"\n',
    "dead region": 'if False:\n    Q = "DELETE FROM t"\n',
    "type-checking region": 'if TYPE_CHECKING:\n    Q = "DELETE FROM t"\n',
    "default argument": 'def f(q: str = "DELETE FROM t") -> None: ...\n',
    "inside a function": 'def f():\n    return "INSERT INTO t VALUES (1)"\n',
    "schema-qualified table": 'Q = "UPDATE public.t SET a = 1"\n',
    # the forms the reviewer's probe showed passing
    ".format placeholder": 'def f(t):\n    return "UPDATE {} SET a = 1".format(t)\n',
    ".format named placeholder": (
        'def f(t):\n    return "UPDATE {table} SET a = 1".format(table=t)\n'
    ),
    "%s placeholder": 'def f(t):\n    return "UPDATE %s SET a = 1" % t\n',
    "%(name)s placeholder": 'def f(t):\n    return "UPDATE %(t)s SET a = 1" % {"t": t}\n',
    "plus concatenation": 'def f(t):\n    return "UPDATE " + t + " SET a = 1"\n',
    "plus concatenation, table last": 'def f(t):\n    return "INSERT INTO " + t\n',
    "join of parts": 'def f(t):\n    return " ".join(["UPDATE", t, "SET a = 1"])\n',
    "UPDATE ... AS alias": 'Q = "UPDATE t AS s SET a = 1"\n',
    "UPDATE alias without AS": 'Q = "UPDATE t s SET a = 1"\n',
    "UPDATE ONLY": 'Q = "UPDATE ONLY t SET a = 1"\n',
    "UPDATE ONLY ... AS": 'Q = "UPDATE ONLY t AS s SET a = 1"\n',
    "bytes constant": 'Q = b"UPDATE t SET a = 1"\n',
    "aliased insert import": "from sqlalchemy import insert as ins\nq = ins(T)\n",
    "aliased update import": "from sqlalchemy.dialects.postgresql import insert as pg\n",
    "aliased text import": "from sqlalchemy import text as t\nq = t('x')\n",
    "non-called reference": "import sqlalchemy as sa\nw = sa.insert\n",
    # round 3 (reviewer N1, N2)
    "block comment between verb and table": (
        'Q = "UPDATE /* hot */ order_number_sequences SET next_value = :value"\n'
    ),
    "line comment inside a statement": 'Q = """UPDATE t -- c\n    SET a = 1"""\n',
    "comment between INSERT and INTO": 'Q = "INSERT /* c */ INTO t (a) VALUES (1)"\n',
    "aliased Update class import": "from sqlalchemy.sql.dml import Update as _U\n_STMT = _U\n",
    "aliased Insert class import": "from sqlalchemy import Insert as I2\n",
    "aliased Delete class import": "from sqlalchemy.sql.dml import Delete as D2\n",
    "Update class call": "from sqlalchemy.sql.dml import Update\nq = Update(T).values(a=1)\n",
    "Update class by attribute": "import sqlalchemy.sql.dml as d\nq = d.Update(T)\n",
    # round 4 (reviewer R3-B2): asyncpg's two write-side COPY methods
    "asyncpg copy_records_to_table": (
        "async def f(c):\n    await c.copy_records_to_table('t', records=[])\n"
    ),
    "asyncpg copy_to_table": (
        "async def f(c):\n    await c.copy_to_table('t', source='counters.csv')\n"
    ),
}

MUST_NOT_SEE = {
    "row lock": 'Q = "SELECT next_value FROM order_number_sequences WHERE id = 1 FOR UPDATE"\n',
    "plain select": 'Q = "SELECT * FROM t"\n',
    "word in a comment": "x = 1  # INSERT INTO t and update(T)\n",
    "ordinary prose": 'MSG = "please update the record, then insert the line"\n',
    "an attribute named like a type": "x = order.updated_at\n",
    "a sum of ints": "def f(a, b):\n    return a + b + 1\n",
    "asyncpg read-side copy": "async def f(c):\n    await c.copy_from_table('t', output='o')\n",
    "a plain import": "from sqlalchemy import select, func\nq = select(func.max(T.a))\n",
    "a comment that only names a statement": 'Q = "SELECT 1 /* UPDATE t SET a = 1 */"\n',
    "a lock with a placeholder": 'def f(t):\n    return "SELECT 1 FROM {} FOR UPDATE".format(t)\n',
}

# Occurrence counts: the same text twice is TWO writers.
MUST_COUNT = {
    "the same call twice": ("def f(s):\n    s.execute(a)\n    s.execute(b)\n", 2),
    "the same statement twice": ('A = "UPDATE t SET a = 1"\nB = "UPDATE t SET a = 1"\n', 2),
    "two statements in one string": ('Q = "UPDATE t SET a = 1; UPDATE u SET b = 2"\n', 2),
    "a concatenation counts once": ('def f(t):\n    return "UPDATE " + t + " SET a = 1"\n', 1),
    "an f-string counts once": ('def f(t):\n    return f"UPDATE {t} SET a = 1"\n', 1),
    "an alias import and its call": ("from sqlalchemy import insert as i\nq = i(T)\n", 2),
    # premise 6: the left operand is already a whole statement; scanned alone AND as part of the
    # longer string it would count twice.
    "a whole statement plus a tail counts once": (
        'Q = "UPDATE t SET a = 1" + " WHERE id = :v"\n',
        1,
    ),
    "a comment does not add or hide a statement": (
        'Q = "UPDATE /* a */ t /* b */ SET a = 1 -- UPDATE u SET b = 2"\n',
        1,
    ),
}


@pytest.mark.parametrize("shape", sorted(MUST_SEE))
def test_the_scan_sees_a_write_in_every_form(shape: str) -> None:
    assert hits(MUST_SEE[shape]), f"the write-path scan failed to see: {shape}"


@pytest.mark.parametrize("shape", sorted(MUST_NOT_SEE))
def test_the_scan_ignores_what_is_not_a_write(shape: str) -> None:
    assert hits(MUST_NOT_SEE[shape]) == Counter(), f"false positive on: {shape}"


@pytest.mark.parametrize("shape", sorted(MUST_COUNT))
def test_the_scan_counts_occurrences_not_distinct_entries(shape: str) -> None:
    source, expected = MUST_COUNT[shape]
    assert sum(hits(source).values()) == expected, f"wrong count for: {shape}: {hits(source)}"


def test_the_first_instrument_missed_what_this_one_finds() -> None:
    """The retired grep (`insert(\\|update(\\|text(\\|bulk_`) found nothing in these constants."""
    legacy = re.compile(r"insert\(|update\(|text\(|bulk_")
    sequences = (
        REPO_ROOT / "services/orders/src/otc_orders/infrastructure/persistence/sequences.py"
    ).read_text(encoding="utf-8")
    assert not legacy.search(sequences)
    assert sum(hits(sequences).values()) == 2


# --- the three writers the reviewer planted (progress/review_backlog_sweep.md B2) -------------


@pytest.mark.parametrize(
    ("label", "addition"),
    [
        (
            "a second writer with the same key in a classified file",
            '\nSET_ORDER_SEQUENCE = "UPDATE order_number_sequences SET next_value = :value '
            'WHERE id = 1"\n',
        ),
        (
            "a .format table placeholder in a new file",
            '\nQ = "UPDATE {} SET next_value = :value".format(table)\n',
        ),
        (
            "UPDATE ... AS alias in a new file",
            '\nQ = "UPDATE order_number_sequences AS s SET next_value = :value"\n',
        ),
    ],
)
def test_the_reviewers_planted_writers_each_fail_the_population(label: str, addition: str) -> None:
    sequences = "infrastructure/persistence/sequences.py"
    source = (REPO_ROOT / "services/orders/src/otc_orders" / sequences).read_text(encoding="utf-8")
    actual = scan_service("orders")
    assert actual == EXPECTED["orders"], "precondition: the real population is the classified one"
    if "classified file" in label:
        actual[sequences] = hits(source + addition)
    else:
        actual["infrastructure/persistence/planted_writer.py"] = hits(addition)
    assert actual != EXPECTED["orders"], f"the population would accept: {label}"
